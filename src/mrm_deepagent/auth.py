"""Authentication and network helpers for Gemini runtime."""

from __future__ import annotations

import os
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from google.auth.credentials import Credentials

from mrm_deepagent.models import AppConfig


def apply_network_settings(config: AppConfig) -> None:
    """Apply network-related environment settings."""
    if config.https_proxy:
        for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            os.environ[key] = config.https_proxy

    if config.ssl_cert_file:
        os.environ["SSL_CERT_FILE"] = config.ssl_cert_file
        os.environ["REQUESTS_CA_BUNDLE"] = config.ssl_cert_file


def build_m2m_credentials(config: AppConfig) -> Credentials:
    """Create refreshable OAuth2 credentials using client-credentials grant."""
    return M2MTokenCredentials(
        token_url=config.m2m_token_url or "",
        client_id=config.m2m_client_id or "",
        client_secret=config.m2m_client_secret or "",
        scope=config.m2m_scope,
        audience=config.m2m_audience,
        grant_type=config.m2m_grant_type,
        token_field=config.m2m_token_field,
        expires_in_field=config.m2m_expires_in_field,
        auth_style=config.m2m_auth_style,
        timeout_s=config.m2m_token_timeout,
        https_proxy=config.https_proxy,
        ssl_cert_file=config.ssl_cert_file,
    )


def build_h2m_credentials(config: AppConfig) -> Credentials:
    """Create refreshable credentials using human-to-machine token callback."""
    return H2MTokenCredentials(
        default_ttl_s=config.h2m_token_ttl,
        token_cmd=config.h2m_token_cmd,
    )


def call_h2m_token(cmd: str | None = None) -> str | tuple[str, int] | dict[str, Any]:
    """Return an H2M token payload.

    When *cmd* is provided, it is executed as a shell command and the
    stdout output is returned as the token string (leading/trailing
    whitespace stripped).

    Without *cmd*, callers can monkeypatch this function for custom
    token retrieval logic.
    """
    if cmd:
        return (
            subprocess.check_output(cmd, shell=True)  # noqa: S602
            .decode()
            .strip()
        )
    raise NotImplementedError(
        "call_h2m_token() requires either H2M_TOKEN_CMD in configuration "
        "or a monkeypatched implementation."
    )


class M2MTokenCredentials(Credentials):
    """Refreshable credentials using OAuth2 client credentials flow."""

    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str | None,
        audience: str | None,
        grant_type: str,
        token_field: str,
        expires_in_field: str,
        auth_style: str,
        timeout_s: int,
        https_proxy: str | None,
        ssl_cert_file: str | None,
    ) -> None:
        super().__init__()
        self.token = None
        self.expiry = None
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._audience = audience
        self._grant_type = grant_type
        self._token_field = token_field
        self._expires_in_field = expires_in_field
        self._auth_style = auth_style.lower()
        self._timeout_s = timeout_s
        self._proxies = (
            {"http": https_proxy, "https": https_proxy} if https_proxy else None
        )
        self._verify = ssl_cert_file if ssl_cert_file else True
        self._lock = threading.Lock()

    @property
    def expired(self) -> bool:
        if self.expiry is None:
            return True
        return datetime.now(UTC) >= (self.expiry - timedelta(seconds=60))

    @property
    def valid(self) -> bool:
        return bool(self.token) and not self.expired

    @property
    def requires_scopes(self) -> bool:
        return False

    def refresh(self, request: Any) -> None:  # noqa: ARG002 - Google auth interface
        with self._lock:
            if self.valid:
                return
            token, expiry = self._fetch_token()
            self.token = token
            self.expiry = expiry

    def _fetch_token(self) -> tuple[str, datetime]:
        payload: dict[str, str] = {"grant_type": self._grant_type}
        headers = {"Accept": "application/json"}
        auth: tuple[str, str] | None = None

        if self._scope:
            payload["scope"] = self._scope
        if self._audience:
            payload["audience"] = self._audience

        if self._auth_style == "basic":
            auth = (self._client_id, self._client_secret)
        else:
            payload["client_id"] = self._client_id
            payload["client_secret"] = self._client_secret

        response = requests.post(
            self._token_url,
            data=payload,
            headers=headers,
            auth=auth,
            timeout=self._timeout_s,
            proxies=self._proxies,
            verify=self._verify,
        )
        response.raise_for_status()
        token_payload = response.json()

        token = token_payload.get(self._token_field)
        if not token:
            raise RuntimeError(
                f"M2M token response missing field '{self._token_field}': {token_payload}"
            )

        raw_expiry = token_payload.get(self._expires_in_field, 3600)
        expires_in = int(float(raw_expiry))
        expiry = datetime.now(UTC) + timedelta(seconds=max(60, expires_in))
        return str(token), expiry


class H2MTokenCredentials(Credentials):
    """Refreshable credentials using a local H2M token callback hook."""

    def __init__(self, *, default_ttl_s: int = 3600, token_cmd: str | None = None) -> None:
        super().__init__()
        self.token = None
        self.expiry = None
        self._default_ttl_s = default_ttl_s
        self._token_cmd = token_cmd
        self._lock = threading.Lock()

    @property
    def expired(self) -> bool:
        if self.expiry is None:
            return True
        return datetime.now(UTC) >= (self.expiry - timedelta(seconds=60))

    @property
    def valid(self) -> bool:
        return bool(self.token) and not self.expired

    @property
    def requires_scopes(self) -> bool:
        return False

    def refresh(self, request: Any) -> None:  # noqa: ARG002 - Google auth interface
        with self._lock:
            if self.valid:
                return
            token, expiry = self._fetch_token()
            self.token = token
            self.expiry = expiry

    def _fetch_token(self) -> tuple[str, datetime]:
        payload = call_h2m_token(cmd=self._token_cmd)
        token: str | None = None
        expires_in = self._default_ttl_s

        if isinstance(payload, str):
            token = payload
        elif isinstance(payload, tuple) and len(payload) >= 1:
            token = str(payload[0])
            if len(payload) >= 2:
                expires_in = int(float(payload[1]))
        elif isinstance(payload, dict):
            raw_token = payload.get("access_token") or payload.get("token")
            if raw_token:
                token = str(raw_token)
            raw_expiry = payload.get("expires_in")
            if raw_expiry is not None:
                expires_in = int(float(raw_expiry))
        else:
            raise RuntimeError(
                "call_h2m_token() returned an unsupported payload type. "
                "Expected str, tuple(token, expires_in), or dict."
            )

        if not token:
            raise RuntimeError("call_h2m_token() did not return a usable token.")

        expiry = datetime.now(UTC) + timedelta(seconds=max(60, expires_in))
        return token, expiry
