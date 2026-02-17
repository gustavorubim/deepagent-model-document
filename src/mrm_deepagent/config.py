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
    validate_llm_config: bool = True,
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

    if config.provider not in {"google_ai_studio", "google_vertex_ai"}:
        raise MissingRuntimeConfigError(f"Unsupported provider '{config.provider}'.")

    if config.ssl_cert_file and not Path(config.ssl_cert_file).exists():
        raise MissingRuntimeConfigError(f"SSL cert file does not exist: {config.ssl_cert_file}")

    if validate_llm_config:
        _validate_h2m_config(config)

    return config


def ensure_output_root(path_value: str) -> Path:
    """Ensure output root exists."""
    path = Path(path_value)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _validate_h2m_config(config: AppConfig) -> None:
    missing: list[str] = []
    if not config.google_project:
        missing.append("google_project")
    if config.h2m_token_ttl <= 0:
        missing.append("h2m_token_ttl>0")

    if missing:
        raise MissingRuntimeConfigError(
            "H2M runtime requires the following config values: " + ", ".join(missing)
        )
