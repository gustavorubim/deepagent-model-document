"""Configuration loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from mrm_deepagent.exceptions import MissingRuntimeConfigError
from mrm_deepagent.models import AppConfig


def load_config(
    config_path: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> AppConfig:
    """Load config from defaults, optional YAML, and explicit overrides."""
    payload: dict[str, Any] = {}

    if config_path is not None:
        if not config_path.exists():
            raise MissingRuntimeConfigError(f"Config file does not exist: {config_path}")
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise MissingRuntimeConfigError("Config file must contain a top-level mapping.")
        payload.update(raw)

    if overrides:
        for key, value in overrides.items():
            if value is not None:
                payload[key] = value

    try:
        config = AppConfig(**payload)
    except ValidationError as exc:
        raise MissingRuntimeConfigError(f"Invalid configuration: {exc}") from exc

    return config


def ensure_output_root(path_value: str) -> Path:
    """Ensure output root exists."""
    path = Path(path_value)
    path.mkdir(parents=True, exist_ok=True)
    return path
