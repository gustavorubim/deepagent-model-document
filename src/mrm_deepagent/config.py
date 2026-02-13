"""Configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from mrm_deepagent.exceptions import MissingRuntimeConfigError
from mrm_deepagent.models import AppConfig


def load_config(
    config_path: Path | None = None,
    overrides: dict[str, Any] | None = None,
    require_api_key: bool = True,
) -> AppConfig:
    """Load config from defaults, yaml file, env, and explicit overrides."""
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

    payload["google_api_key"] = os.getenv("GOOGLE_API_KEY")

    config = AppConfig(**payload)

    if config.provider != "google_ai_studio":
        raise MissingRuntimeConfigError(
            f"Unsupported provider '{config.provider}'. Expected 'google_ai_studio'."
        )

    if require_api_key and not config.google_api_key:
        raise MissingRuntimeConfigError("GOOGLE_API_KEY is required for draft generation.")

    return config


def ensure_output_root(path_value: str) -> Path:
    """Ensure output root exists."""
    path = Path(path_value)
    path.mkdir(parents=True, exist_ok=True)
    return path
