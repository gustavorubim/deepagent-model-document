from __future__ import annotations

import os
import sys
import time
import types

import pytest

from mrm_deepagent.agent_runtime import (
    AgentRuntime,
    _build_chat_model,
    _build_deep_agent,
    _response_to_text,
    build_agent,
)
from mrm_deepagent.models import AppConfig


class _FlakyAgent:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, payload: object) -> dict[str, str]:
        self.calls += 1
        if self.calls < 2:
            raise RuntimeError("temporary failure")
        return {"output": f"ok:{payload}"}


def test_invoke_with_retry_retries_then_succeeds() -> None:
    runtime = AgentRuntime(_FlakyAgent())
    output = runtime.invoke_with_retry("prompt", retries=3, timeout_s=1)
    assert output.startswith("ok:")


def test_response_to_text_handles_dict_message_shapes() -> None:
    assert _response_to_text({"output": "x"}) == "x"
    assert _response_to_text({"content": "y"}) == "y"
    assert _response_to_text({"messages": [{"content": "z"}]}) == "z"


def test_build_agent_falls_back_when_deepagents_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeModel:
        def invoke(self, payload: object) -> str:
            return str(payload)

    monkeypatch.setattr(
        "mrm_deepagent.agent_runtime._build_chat_model", lambda *_, **__: _FakeModel()
    )
    monkeypatch.setattr(
        "mrm_deepagent.agent_runtime._build_deep_agent",
        lambda *_, **__: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    config = AppConfig(google_project="proj")
    runtime = build_agent(config, tools=[])
    assert runtime.invoke_with_retry("hello", retries=1, timeout_s=1) == "hello"


def test_invoke_with_retry_raises_after_all_attempts() -> None:
    class _AlwaysFail:
        def invoke(self, payload: object) -> str:
            raise RuntimeError(f"fail:{payload}")

    runtime = AgentRuntime(_AlwaysFail())
    with pytest.raises(RuntimeError, match="failed after 2 attempts"):
        runtime.invoke_with_retry("prompt", retries=2, timeout_s=1)


def test_invoke_with_timeout_raises_timeout_error() -> None:
    class _SlowCallable:
        def __call__(self, prompt: str) -> str:
            time.sleep(0.2)
            return prompt

    runtime = AgentRuntime(_SlowCallable())
    with pytest.raises(RuntimeError, match="timed out"):
        runtime.invoke_with_retry("x", retries=1, timeout_s=0)


def test_invoke_once_rejects_non_invokable_agent() -> None:
    runtime = AgentRuntime(agent=object())
    with pytest.raises(RuntimeError, match="not invokable"):
        runtime._invoke_once("prompt")  # noqa: SLF001 - intentional branch coverage


def test_response_to_text_handles_content_list_and_model_dump() -> None:
    class _ContentObj:
        content = ["line1", {"text": "line2"}]

    class _ModelDumpObj:
        def model_dump(self) -> dict[str, str]:
            return {"k": "v"}

    assert _response_to_text(_ContentObj()) == "line1\nline2"
    assert _response_to_text(_ModelDumpObj()) == '{"k": "v"}'


def test_response_to_text_handles_non_json_model_dump() -> None:
    class _BadModelDump:
        def model_dump(self) -> dict[str, object]:
            return {"bad": object()}

    text = _response_to_text(_BadModelDump())
    assert "bad" in text


def test_build_chat_model_uses_fallback_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class _FakeChatModel:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)
            if kwargs.get("model") == "primary":
                raise ValueError("bad primary")
            self.model = kwargs["model"]
            self.project = kwargs.get("project")
            self.base_url = kwargs.get("base_url")
            self.temperature = kwargs.get("temperature")

    monkeypatch.setitem(
        sys.modules,
        "langchain_google_genai",
        types.SimpleNamespace(ChatGoogleGenerativeAI=_FakeChatModel),
    )
    monkeypatch.setattr(
        "mrm_deepagent.agent_runtime.H2MTokenCredentials",
        lambda **_kwargs: "creds",
    )
    config = AppConfig(
        model="primary",
        fallback_model="fallback",
        google_project="proj",
        base_url="https://vertex.example",
        additional_headers={"x-tenant": "acme"},
    )
    model = _build_chat_model("primary", config)
    assert getattr(model, "model") == "fallback"
    assert [call["model"] for call in calls] == ["primary", "fallback"]
    assert calls[1]["vertexai"] is True
    assert calls[1]["project"] == "proj"
    assert calls[1]["credentials"] == "creds"
    assert calls[1]["base_url"] == "https://vertex.example"
    assert calls[1]["additional_headers"] == {"x-tenant": "acme"}


def test_build_chat_model_h2m_uses_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeChatModel:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "langchain_google_genai",
        types.SimpleNamespace(ChatGoogleGenerativeAI=_FakeChatModel),
    )
    monkeypatch.setattr(
        "mrm_deepagent.agent_runtime.H2MTokenCredentials",
        lambda **_kwargs: "h2m-creds",
    )
    config = AppConfig(
        google_project="proj",
        google_location="us-central1",
    )
    _build_chat_model("gemini-model", config)
    assert captured["credentials"] == "h2m-creds"
    assert captured["vertexai"] is True
    assert captured["project"] == "proj"


def test_build_chat_model_sets_ssl_cert_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cert_file = tmp_path / "root-ca.pem"
    cert_file.write_text("dummy", encoding="utf-8")

    class _FakeChatModel:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    monkeypatch.setitem(
        sys.modules,
        "langchain_google_genai",
        types.SimpleNamespace(ChatGoogleGenerativeAI=_FakeChatModel),
    )
    monkeypatch.setattr(
        "mrm_deepagent.agent_runtime.H2MTokenCredentials",
        lambda **_kwargs: "h2m-creds",
    )
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    config = AppConfig(
        google_project="proj",
        ssl_cert_file=str(cert_file),
    )
    _build_chat_model("gemini-model", config)
    assert os.environ["SSL_CERT_FILE"] == str(cert_file)
    assert os.environ["REQUESTS_CA_BUNDLE"] == str(cert_file)


def test_build_deep_agent_prefers_kwargs_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def create_deep_agent(
        model: object | None = None,
        tools: list[object] | None = None,
        system_prompt: str | None = None,
        instructions: str | None = None,
    ) -> dict[str, object]:
        seen["model"] = model
        seen["tools"] = tools
        seen["system_prompt"] = system_prompt
        seen["instructions"] = instructions
        return {"ok": True}

    monkeypatch.setitem(
        sys.modules,
        "deepagents",
        types.SimpleNamespace(create_deep_agent=create_deep_agent),
    )
    out = _build_deep_agent(model="m", tools=["t"])
    assert out == {"ok": True}
    assert seen["model"] == "m"
    assert seen["tools"] == ["t"]
    assert isinstance(seen["system_prompt"], str)


def test_build_deep_agent_uses_positional_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    def create_deep_agent(*args: object) -> tuple[object, ...]:
        return args

    monkeypatch.setitem(
        sys.modules,
        "deepagents",
        types.SimpleNamespace(create_deep_agent=create_deep_agent),
    )
    out = _build_deep_agent(model="m", tools=["t"])
    assert out == ("m", ["t"])
