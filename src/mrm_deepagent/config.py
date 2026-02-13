"""Configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from mrm_deepagent.exceptions import MissingRuntimeConfigError
from mrm_deepagent.models import AppConfig, AuthMode

_ENV_TO_CONFIG: dict[str, str] = {
    "GOOGLE_API_KEY": "google_api_key",
    "MRM_AUTH_MODE": "auth_mode",
    "GOOGLE_VERTEXAI": "vertexai",
    "GOOGLE_PROJECT": "google_project",
    "GOOGLE_LOCATION": "google_location",
    "HTTPS_PROXY": "https_proxy",
    "SSL_CERT_FILE": "ssl_cert_file",
    "M2M_TOKEN_URL": "m2m_token_url",
    "M2M_CLIENT_ID": "m2m_client_id",
    "M2M_CLIENT_SECRET": "m2m_client_secret",
    "M2M_SCOPE": "m2m_scope",
    "M2M_AUDIENCE": "m2m_audience",
    "M2M_GRANT_TYPE": "m2m_grant_type",
    "M2M_TOKEN_FIELD": "m2m_token_field",
    "M2M_EXPIRES_IN_FIELD": "m2m_expires_in_field",
    "M2M_AUTH_STYLE": "m2m_auth_style",
    "M2M_TOKEN_TIMEOUT": "m2m_token_timeout",
    "H2M_TOKEN_TTL": "h2m_token_ttl",
}

_BOOL_FIELDS = {"vertexai"}
_INT_FIELDS = {"m2m_token_timeout", "h2m_token_ttl"}


def load_config(
    config_path: Path | None = None,
    overrides: dict[str, Any] | None = None,
    require_api_key: bool = True,
    dotenv_path: Path | None = None,
) -> AppConfig:
    """Load config from defaults, yaml file, .env, env, and explicit overrides."""
    payload: dict[str, Any] = {}
    dotenv_to_load = dotenv_path if dotenv_path is not None else Path(".env")
    load_dotenv(dotenv_path=dotenv_to_load, override=False)

    if config_path is not None:
        if not config_path.exists():
            raise MissingRuntimeConfigError(f"Config file does not exist: {config_path}")
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise MissingRuntimeConfigError("Config file must contain a top-level mapping.")
        payload.update(raw)

    for env_key, config_key in _ENV_TO_CONFIG.items():
        env_value = os.getenv(env_key)
        if env_value is None or env_value == "":
            continue
        payload[config_key] = _coerce_env_value(config_key, env_value)

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

    if config.auth_mode == AuthMode.API:
        if require_api_key and not config.google_api_key and not config.vertexai:
            raise MissingRuntimeConfigError(
                "GOOGLE_API_KEY is required for draft generation when "
                "auth_mode=api and vertexai is false."
            )
    elif config.auth_mode == AuthMode.M2M:
        _validate_m2m_config(config)
    else:
        _validate_h2m_config(config)

    return config


def ensure_output_root(path_value: str) -> Path:
    """Ensure output root exists."""
    path = Path(path_value)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _coerce_env_value(config_key: str, env_value: str) -> Any:
    if config_key in _BOOL_FIELDS:
        normalized = env_value.strip().lower()
        return normalized in {"1", "true", "yes", "on"}
    if config_key in _INT_FIELDS:
        return int(env_value)
    return env_value


def _validate_m2m_config(config: AppConfig) -> None:
    missing: list[str] = []
    required_pairs = [
        ("m2m_token_url", config.m2m_token_url),
        ("m2m_client_id", config.m2m_client_id),
        ("m2m_client_secret", config.m2m_client_secret),
        ("google_project", config.google_project),
    ]
    for key, value in required_pairs:
        if not value:
            missing.append(key)
    if not config.vertexai:
        missing.append("vertexai=true")

    if missing:
        raise MissingRuntimeConfigError(
            "M2M auth requires the following config values: " + ", ".join(missing)
        )


def _validate_h2m_config(config: AppConfig) -> None:
    missing: list[str] = []
    if not config.google_project:
        missing.append("google_project")
    if not config.vertexai:
        missing.append("vertexai=true")
    if missing:
        raise MissingRuntimeConfigError(
            "H2M auth requires the following config values: " + ", ".join(missing)
        )
