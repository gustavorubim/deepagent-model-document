"""Authentication and network helpers for Gemini runtime."""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

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


def build_h2m_credentials(config: AppConfig) -> Credentials:
    """Create refreshable credentials using human-to-machine token callback."""
    return H2MTokenCredentials(default_ttl_s=config.h2m_token_ttl)


def call_h2m_token() -> str | tuple[str, int] | dict[str, Any]:
    """Return an H2M token payload.

    Implement this hook in your environment to return one of:
    - token string
    - tuple: (token, expires_in_seconds)
    - dict: {"access_token": "...", "expires_in": 3600}
    """
    raise NotImplementedError(
        "call_h2m_token() is not implemented. Provide an implementation that returns a token."
    )


class H2MTokenCredentials(Credentials):
    """Refreshable credentials using a local H2M token callback hook."""

    def __init__(self, *, default_ttl_s: int = 3600) -> None:
        super().__init__()
        self.token = None
        self.expiry = None
        self._default_ttl_s = default_ttl_s
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
        payload = call_h2m_token()
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
