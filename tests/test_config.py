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
        },
    )

    assert config.model == "gemini-3-flash-preview"
    assert config.output_root == "alt_outputs"
    assert config.context_file == "ctx.md"


def test_load_config_with_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("model: gemini-3-flash-preview\n", encoding="utf-8")
    config = load_config(config_path=config_path)
    assert config.model == "gemini-3-flash-preview"


def test_load_config_rejects_invalid_type(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("temperature: not-a-float\n", encoding="utf-8")

    with pytest.raises(MissingRuntimeConfigError):
        load_config(config_path=config_path)


def test_ensure_output_root_creates_directory(tmp_path: Path) -> None:
    out = ensure_output_root(str(tmp_path / "nested" / "out"))
    assert out.exists()
    assert out.is_dir()
