from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mrm_deepagent.auth import H2MTokenCredentials, apply_network_settings
from mrm_deepagent.models import AppConfig


def test_apply_network_settings_sets_proxy_and_cert(monkeypatch, tmp_path: Path) -> None:
    cert_file = tmp_path / "corp.pem"
    cert_file.write_text("dummy", encoding="utf-8")
    config = AppConfig(
        google_project="proj",
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


def test_h2m_token_credentials_refresh_from_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"count": 0}

    def _fake_call_h2m_token() -> dict[str, object]:
        called["count"] += 1
        return {"access_token": "h2m-token", "expires_in": 120}

    monkeypatch.setattr("mrm_deepagent.auth.call_h2m_token", _fake_call_h2m_token)
    creds = H2MTokenCredentials(default_ttl_s=3600)
    creds.refresh(None)
    assert creds.token == "h2m-token"
    assert creds.valid
    assert called["count"] == 1

    creds.expiry = datetime.now(UTC) + timedelta(minutes=5)
    creds.refresh(None)
    assert called["count"] == 1
