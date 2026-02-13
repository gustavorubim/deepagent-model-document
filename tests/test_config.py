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

    with pytest.raises(MissingRuntimeConfigError):
        load_config(config_path=config_path, require_api_key=True)


def test_load_config_rejects_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("provider: invalid_provider\n", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    with pytest.raises(MissingRuntimeConfigError):
        load_config(config_path=config_path, require_api_key=False)


def test_ensure_output_root_creates_directory(tmp_path: Path) -> None:
    out = ensure_output_root(str(tmp_path / "nested" / "out"))
    assert out.exists()
    assert out.is_dir()
