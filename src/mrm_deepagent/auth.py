"""Authentication and network helpers for Gemini runtime."""

from __future__ import annotations

import os
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
