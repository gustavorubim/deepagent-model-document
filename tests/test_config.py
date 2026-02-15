from __future__ import annotations

from pathlib import Path

import pytest

from mrm_deepagent.config import ensure_output_root, load_config
from mrm_deepagent.exceptions import MissingRuntimeConfigError


def test_load_config_with_yaml_and_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "model: gemini-2.5-flash\noutput_root: alt_outputs\nprovider: google_ai_studio\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    config = load_config(
        config_path=config_path,
        overrides={"model": "gemini-3-flash-preview", "context_file": "ctx.md"},
        require_api_key=True,
    )

    assert config.model == "gemini-3-flash-preview"
    assert config.output_root == "alt_outputs"
    assert config.context_file == "ctx.md"
    assert config.google_api_key == "test-key"


def test_load_config_requires_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("provider: google_ai_studio\n", encoding="utf-8")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(MissingRuntimeConfigError):
        load_config(config_path=config_path, require_api_key=True)


def test_load_config_rejects_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("provider: invalid_provider\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    with pytest.raises(MissingRuntimeConfigError):
        load_config(config_path=config_path, require_api_key=False)


def test_load_config_reads_api_key_from_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    dotenv_path = tmp_path / ".env"
    config_path.write_text("provider: google_ai_studio\n", encoding="utf-8")
    dotenv_path.write_text("GOOGLE_API_KEY=dotenv-test-key\n", encoding="utf-8")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    config = load_config(config_path=config_path, require_api_key=True, dotenv_path=dotenv_path)
    assert config.google_api_key == "dotenv-test-key"


def test_load_config_cli_overrides_take_precedence_over_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    dotenv_path = tmp_path / ".env"
    config_path.write_text("provider: google_ai_studio\n", encoding="utf-8")
    dotenv_path.write_text("MRM_AUTH_MODE=m2m\nGOOGLE_VERTEXAI=true\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    config = load_config(
        config_path=config_path,
        dotenv_path=dotenv_path,
        require_api_key=True,
        overrides={"auth_mode": "api", "vertexai": False},
    )
    assert config.auth_mode.value == "api"
    assert config.vertexai is False


def test_load_config_m2m_requires_vertex_and_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("provider: google_ai_studio\nauth_mode: m2m\n", encoding="utf-8")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(MissingRuntimeConfigError, match="M2M auth requires"):
        load_config(config_path=config_path, require_api_key=True)


def test_load_config_h2m_requires_vertex_and_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("provider: google_ai_studio\nauth_mode: h2m\n", encoding="utf-8")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("MRM_AUTH_MODE", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(MissingRuntimeConfigError, match="H2M auth requires"):
        load_config(config_path=config_path, require_api_key=True)


def test_load_config_m2m_from_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    dotenv_path = tmp_path / ".env"
    config_path.write_text("provider: google_ai_studio\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    dotenv_path.write_text(
        "\n".join(
            [
                "MRM_AUTH_MODE=m2m",
                "GOOGLE_VERTEXAI=true",
                "GOOGLE_PROJECT=my-proj",
                "GOOGLE_LOCATION=us-central1",
                "M2M_TOKEN_URL=https://auth/token",
                "M2M_CLIENT_ID=cid",
                "M2M_CLIENT_SECRET=secret",
                "M2M_SCOPE=scope1",
                "M2M_TOKEN_TIMEOUT=45",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    config = load_config(config_path=config_path, require_api_key=True, dotenv_path=dotenv_path)
    assert config.auth_mode.value == "m2m"
    assert config.vertexai is True
    assert config.google_project == "my-proj"
    assert config.m2m_client_id == "cid"
    assert config.m2m_token_timeout == 45


def test_load_config_h2m_from_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    dotenv_path = tmp_path / ".env"
    config_path.write_text("provider: google_ai_studio\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MRM_AUTH_MODE", raising=False)
    monkeypatch.delenv("GOOGLE_VERTEXAI", raising=False)
    monkeypatch.delenv("GOOGLE_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_LOCATION", raising=False)
    monkeypatch.delenv("H2M_TOKEN_TTL", raising=False)
    dotenv_path.write_text(
        "\n".join(
            [
                "MRM_AUTH_MODE=h2m",
                "GOOGLE_VERTEXAI=true",
                "GOOGLE_PROJECT=my-proj",
                "GOOGLE_LOCATION=us-central1",
                "H2M_TOKEN_TTL=600",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    config = load_config(config_path=config_path, require_api_key=True, dotenv_path=dotenv_path)
    assert config.auth_mode.value == "h2m"
    assert config.vertexai is True
    assert config.google_project == "my-proj"
    assert config.h2m_token_ttl == 600


def test_load_config_rejects_missing_ssl_cert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "provider: google_ai_studio\nauth_mode: api\nssl_cert_file: C:/nope.pem\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    with pytest.raises(MissingRuntimeConfigError, match="SSL cert file does not exist"):
        load_config(config_path=config_path, require_api_key=False)


def test_load_config_vertex_base_url_and_headers_from_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    dotenv_path = tmp_path / ".env"
    config_path.write_text("provider: google_ai_studio\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.delenv("VERTEX_BASE_URL", raising=False)
    monkeypatch.delenv("VERTEX_HEADERS", raising=False)
    dotenv_path.write_text(
        "\n".join(
            [
                "GOOGLE_API_KEY=test-key",
                "VERTEX_BASE_URL=https://gateway.corp/vertex",
                'VERTEX_HEADERS={"x-custom-header": "value1"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config = load_config(config_path=config_path, require_api_key=True, dotenv_path=dotenv_path)
    assert config.vertex_base_url == "https://gateway.corp/vertex"
    assert config.vertex_headers == {"x-custom-header": "value1"}


def test_load_config_h2m_token_cmd_from_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    dotenv_path = tmp_path / ".env"
    config_path.write_text("provider: google_ai_studio\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MRM_AUTH_MODE", raising=False)
    monkeypatch.delenv("GOOGLE_VERTEXAI", raising=False)
    monkeypatch.delenv("GOOGLE_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_LOCATION", raising=False)
    monkeypatch.delenv("H2M_TOKEN_CMD", raising=False)
    monkeypatch.delenv("H2M_TOKEN_TTL", raising=False)
    dotenv_path.write_text(
        "\n".join(
            [
                "MRM_AUTH_MODE=h2m",
                "GOOGLE_VERTEXAI=true",
                "GOOGLE_PROJECT=my-proj",
                "H2M_TOKEN_CMD=helix auth access-token print -a",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    config = load_config(config_path=config_path, require_api_key=True, dotenv_path=dotenv_path)
    assert config.h2m_token_cmd == "helix auth access-token print -a"
    assert config.auth_mode.value == "h2m"


def test_ensure_output_root_creates_directory(tmp_path: Path) -> None:
    out = ensure_output_root(str(tmp_path / "nested" / "out"))
    assert out.exists()
    assert out.is_dir()
