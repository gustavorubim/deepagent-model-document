from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mrm_deepagent.auth import H2MTokenCredentials


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
