from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mrm_deepagent.auth import M2MTokenCredentials, apply_network_settings
from mrm_deepagent.models import AppConfig


def test_apply_network_settings_sets_proxy_and_cert(monkeypatch, tmp_path: Path) -> None:
    cert_file = tmp_path / "corp.pem"
    cert_file.write_text("dummy", encoding="utf-8")
    config = AppConfig(
        google_api_key="x",
        https_proxy="https://proxy.example:8443",
        ssl_cert_file=str(cert_file),
    )
    apply_network_settings(config)
    assert os.environ["HTTPS_PROXY"] == "https://proxy.example:8443"
    assert os.environ["SSL_CERT_FILE"] == str(cert_file)
    assert os.environ["REQUESTS_CA_BUNDLE"] == str(cert_file)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)


def test_m2m_token_credentials_refresh(monkeypatch) -> None:
    called = {"count": 0}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"access_token": "abc123", "expires_in": 120}

    def _fake_post(*args, **kwargs):  # noqa: ANN002, ANN003
        called["count"] += 1
        assert kwargs["data"]["grant_type"] == "client_credentials"
        return _Response()

    monkeypatch.setattr("mrm_deepagent.auth.requests.post", _fake_post)

    creds = M2MTokenCredentials(
        token_url="https://auth/token",
        client_id="cid",
        client_secret="secret",
        scope="scope1",
        audience=None,
        grant_type="client_credentials",
        token_field="access_token",
        expires_in_field="expires_in",
        auth_style="body",
        timeout_s=10,
        https_proxy=None,
        ssl_cert_file=None,
    )
    creds.refresh(None)
    assert creds.token == "abc123"
    assert creds.valid
    assert called["count"] == 1

    creds.expiry = datetime.now(UTC) + timedelta(minutes=5)
    creds.refresh(None)
    assert called["count"] == 1
