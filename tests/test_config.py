from __future__ import annotations

from pathlib import Path

import pytest

from mrm_deepagent.config import ensure_output_root, load_config
from mrm_deepagent.exceptions import MissingRuntimeConfigError


def test_load_config_with_yaml_and_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "model: gemini-2.5-flash",
                "output_root: alt_outputs",
                "provider: google_ai_studio",
                "google_project: from-yaml",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config = load_config(
        config_path=config_path,
        overrides={
            "model": "gemini-3-flash-preview",
            "context_file": "ctx.md",
            "google_project": "from-cli",
            "additional_headers": {"x-tenant": "acme"},
        },
        validate_llm_config=True,
    )

    assert config.model == "gemini-3-flash-preview"
    assert config.output_root == "alt_outputs"
    assert config.context_file == "ctx.md"
    assert config.google_project == "from-cli"
    assert config.additional_headers == {"x-tenant": "acme"}


def test_load_config_requires_h2m_project_by_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("provider: google_ai_studio\n", encoding="utf-8")

    with pytest.raises(MissingRuntimeConfigError, match="H2M runtime requires"):
        load_config(config_path=config_path, validate_llm_config=True)


def test_load_config_can_skip_llm_validation_for_apply(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("provider: google_ai_studio\n", encoding="utf-8")
    config = load_config(config_path=config_path, validate_llm_config=False)
    assert config.provider == "google_ai_studio"
    assert config.google_project is None


def test_load_config_rejects_provider(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("provider: invalid_provider\n", encoding="utf-8")

    with pytest.raises(MissingRuntimeConfigError):
        load_config(config_path=config_path, validate_llm_config=False)


def test_load_config_rejects_missing_ssl_cert(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "provider: google_ai_studio\ngoogle_project: proj\nssl_cert_file: C:/nope.pem\n",
        encoding="utf-8",
    )

    with pytest.raises(MissingRuntimeConfigError, match="SSL cert file does not exist"):
        load_config(config_path=config_path, validate_llm_config=False)


def test_load_config_rejects_non_positive_h2m_ttl(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "provider: google_ai_studio\ngoogle_project: proj\nh2m_token_ttl: 0\n",
        encoding="utf-8",
    )

    with pytest.raises(MissingRuntimeConfigError, match="h2m_token_ttl>0"):
        load_config(config_path=config_path, validate_llm_config=True)


def test_ensure_output_root_creates_directory(tmp_path: Path) -> None:
    out = ensure_output_root(str(tmp_path / "nested" / "out"))
    assert out.exists()
    assert out.is_dir()
