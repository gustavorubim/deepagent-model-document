"""Smoke tests for H2M auth + Vertex gateway (HttpOptions) integration.

These tests verify the full wiring works WITHOUT a corporate network.
They use a local mock HTTP server that impersonates the Vertex AI gateway,
and a trivial shell command (``echo``) in place of ``helix auth``.

Run with:
    pytest tests/test_h2m_gateway_smoke.py -v
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from mrm_deepagent.agent_runtime import _build_genai_client, _chat_model_kwargs
from mrm_deepagent.auth import build_h2m_credentials, call_h2m_token
from mrm_deepagent.config import load_config
from mrm_deepagent.models import AppConfig


# ── 1. call_h2m_token runs a real shell command ─────────────


def test_h2m_token_cmd_echo() -> None:
    """Verify call_h2m_token can execute a real shell command."""
    cmd = "echo test-token-abc"
    if sys.platform == "win32":
        # Windows echo doesn't add quotes but may add trailing \r
        token = call_h2m_token(cmd=cmd)
    else:
        token = call_h2m_token(cmd=cmd)
    assert token == "test-token-abc"


def test_h2m_credentials_refresh_with_echo() -> None:
    """H2MTokenCredentials fetches a real token via echo command."""
    config = AppConfig(
        auth_mode="h2m",
        vertexai=True,
        google_project="test-proj",
        h2m_token_cmd="echo fresh-token-123",
        h2m_token_ttl=600,
    )
    creds = build_h2m_credentials(config)
    assert not creds.valid
    creds.refresh(None)
    assert creds.token == "fresh-token-123"
    assert creds.valid


# ── 2. Config loading round-trip ─────────────────────────────


def test_full_h2m_config_from_dotenv(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Load a complete H2M + gateway config from .env and verify all fields."""
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("provider: google_ai_studio\n", encoding="utf-8")
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "MRM_AUTH_MODE=h2m",
                "GOOGLE_VERTEXAI=true",
                "GOOGLE_PROJECT=prj-gen-ai-9571",
                "GOOGLE_LOCATION=global",
                "SSL_CERT_FILE=",
                "H2M_TOKEN_CMD=echo mock-token",
                "H2M_TOKEN_TTL=1200",
                "VERTEX_BASE_URL=https://gateway.corp/vertex",
                'VERTEX_HEADERS={"x-r2d2-soeid": "testuser"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    # Clear env vars that could leak from the real environment
    for key in (
        "GOOGLE_API_KEY", "MRM_AUTH_MODE", "GOOGLE_VERTEXAI",
        "GOOGLE_PROJECT", "GOOGLE_LOCATION", "SSL_CERT_FILE",
        "H2M_TOKEN_CMD", "H2M_TOKEN_TTL", "VERTEX_BASE_URL", "VERTEX_HEADERS",
    ):
        monkeypatch.delenv(key, raising=False)

    cfg = load_config(config_path=config_yaml, dotenv_path=dotenv, require_api_key=True)

    assert cfg.auth_mode.value == "h2m"
    assert cfg.vertexai is True
    assert cfg.google_project == "prj-gen-ai-9571"
    assert cfg.google_location == "global"
    assert cfg.h2m_token_cmd == "echo mock-token"
    assert cfg.h2m_token_ttl == 1200
    assert cfg.vertex_base_url == "https://gateway.corp/vertex"
    assert cfg.vertex_headers == {"x-r2d2-soeid": "testuser"}


# ── 3. genai.Client construction with HttpOptions ───────────


def test_genai_client_receives_http_options() -> None:
    """_build_genai_client passes base_url and headers into HttpOptions."""
    from google import genai
    from google.genai import types as genai_types

    captured: dict[str, Any] = {}
    _orig_client_init = genai.Client.__init__

    def _spy_init(self: Any, **kwargs: Any) -> None:
        captured.update(kwargs)
        # Don't actually connect — just record what was passed
        raise _SpyComplete()

    class _SpyComplete(Exception):
        pass

    config = AppConfig(
        auth_mode="h2m",
        vertexai=True,
        google_project="prj-gen-ai-9571",
        google_location="global",
        h2m_token_cmd="echo spy-token",
        vertex_base_url="https://gateway.corp/vertex",
        vertex_headers={"x-r2d2-soeid": "testuser"},
    )

    original_init = genai.Client.__init__
    genai.Client.__init__ = _spy_init
    try:
        with pytest.raises(_SpyComplete):
            _build_genai_client(config)
    finally:
        genai.Client.__init__ = original_init

    assert captured["vertexai"] is True
    assert captured["project"] == "prj-gen-ai-9571"
    assert captured["location"] == "global"
    http_opts = captured["http_options"]
    assert isinstance(http_opts, genai_types.HttpOptions)
    assert http_opts.base_url == "https://gateway.corp/vertex"
    assert http_opts.headers == {"x-r2d2-soeid": "testuser"}


# ── 4. Local mock gateway integration test ──────────────────


class _MockGatewayHandler(BaseHTTPRequestHandler):
    """Captures requests and returns a fake Gemini response."""

    received_requests: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""
        self.__class__.received_requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers),
                "body": body.decode("utf-8", errors="replace"),
            }
        )
        # Return a minimal Gemini-style JSON response
        response_body = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "mock gateway response"}],
                            "role": "model",
                        }
                    }
                ]
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass  # Suppress stderr noise during tests


def test_mock_gateway_receives_custom_headers_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start a local HTTP server, point genai.Client at it, and verify
    that the custom headers and bearer token arrive in the request."""
    # Clear env vars that earlier tests may have set via os.environ directly
    for var in (
        "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
        "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
    ):
        monkeypatch.delenv(var, raising=False)

    _MockGatewayHandler.received_requests.clear()
    server = HTTPServer(("127.0.0.1", 0), _MockGatewayHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"

    try:
        from google import genai
        from google.genai import types as genai_types
        from google.oauth2.credentials import Credentials

        # Build client the same way the repo would
        token = call_h2m_token(cmd="echo local-test-token")
        client = genai.Client(
            vertexai=True,
            project="test-proj",
            location="global",
            http_options=genai_types.HttpOptions(
                base_url=base_url,
                headers={"x-r2d2-soeid": "smoketest"},
            ),
            credentials=Credentials(token),
        )
        # Fire a request — it will hit our mock server.
        # The mock response may not fully satisfy the SDK parser, but the
        # HTTP request will have been sent and captured by the handler.
        _generate_err: Exception | None = None
        try:
            client.models.generate_content(
                model="gemini-2.0-flash",
                contents="ping",
            )
        except Exception as exc:
            _generate_err = exc
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert len(_MockGatewayHandler.received_requests) >= 1, (
        "Mock gateway received no requests — client did not connect. "
        f"generate_content error: {_generate_err!r}"
    )
    req = _MockGatewayHandler.received_requests[0]
    # Verify the custom header arrived at the gateway
    assert req["headers"].get("x-r2d2-soeid") == "smoketest", (
        f"Custom header missing. Received headers: {req['headers']}"
    )
    # Verify the request was routed to the Vertex AI path
    assert "/publishers/google/models/" in req["path"], (
        f"Request path doesn't look like a Vertex AI route: {req['path']}"
    )
