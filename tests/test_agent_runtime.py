from __future__ import annotations

import sys
import time
import types

import pytest

from mrm_deepagent.agent_runtime import (
    AgentRuntime,
    _build_chat_model,
    _build_deep_agent,
    _build_genai_client,
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

    config = AppConfig(google_api_key="x")
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
            self.google_api_key = kwargs.get("google_api_key")
            self.temperature = kwargs.get("temperature")

    monkeypatch.setitem(
        sys.modules,
        "langchain_google_genai",
        types.SimpleNamespace(ChatGoogleGenerativeAI=_FakeChatModel),
    )
    config = AppConfig(model="primary", fallback_model="fallback", google_api_key="k")
    model = _build_chat_model("primary", config)
    assert getattr(model, "model") == "fallback"
    assert [call["model"] for call in calls] == ["primary", "fallback"]
    assert calls[1]["google_api_key"] == "k"


def test_build_chat_model_m2m_uses_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
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
        "mrm_deepagent.agent_runtime.build_m2m_credentials",
        lambda _config: "creds",
    )
    config = AppConfig(
        auth_mode="m2m",
        vertexai=True,
        google_project="proj",
        google_location="us-central1",
        m2m_token_url="https://auth/token",
        m2m_client_id="cid",
        m2m_client_secret="secret",
    )
    _build_chat_model("gemini-model", config)
    assert captured["credentials"] == "creds"
    assert captured["vertexai"] is True
    assert captured["project"] == "proj"


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
        "mrm_deepagent.agent_runtime.build_h2m_credentials",
        lambda _config: "h2m-creds",
    )
    config = AppConfig(
        auth_mode="h2m",
        vertexai=True,
        google_project="proj",
        google_location="us-central1",
    )
    _build_chat_model("gemini-model", config)
    assert captured["credentials"] == "h2m-creds"
    assert captured["vertexai"] is True
    assert captured["project"] == "proj"


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


def test_build_genai_client_returns_none_without_base_url_or_headers() -> None:
    config = AppConfig(google_api_key="x")
    assert _build_genai_client(config) is None


def test_build_genai_client_constructs_client_with_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google import genai
    from google.genai import types as genai_types

    captured: dict[str, object] = {}
    _OrigClient = genai.Client  # noqa: N806

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured["client_kwargs"] = kwargs

    monkeypatch.setattr(genai, "Client", _FakeClient)

    config = AppConfig(
        google_api_key="x",
        vertexai=True,
        google_project="proj",
        google_location="global",
        vertex_base_url="https://gateway.corp/vertex",
        vertex_headers={"x-soeid": "user1"},
    )
    client = _build_genai_client(config)
    assert client is not None
    client_kwargs = captured["client_kwargs"]
    assert client_kwargs["vertexai"] is True
    assert client_kwargs["project"] == "proj"
    assert client_kwargs["location"] == "global"
    http_opts = client_kwargs["http_options"]
    assert isinstance(http_opts, genai_types.HttpOptions)
    assert http_opts.base_url == "https://gateway.corp/vertex"
    assert http_opts.headers == {"x-soeid": "user1"}


def test_build_chat_model_with_custom_client_passes_client_kwarg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        "mrm_deepagent.agent_runtime._build_genai_client",
        lambda _config: "custom-client",
    )
    config = AppConfig(
        google_api_key="x",
        vertex_base_url="https://gateway.corp/vertex",
    )
    _build_chat_model("gemini-model", config)
    assert captured["client"] == "custom-client"
    # When a custom client is used, vertexai/project/location should NOT be in kwargs
    assert "vertexai" not in captured
    assert "project" not in captured
