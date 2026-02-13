"""Deep agent runtime and invocation helpers."""

from __future__ import annotations

import inspect
import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any

from mrm_deepagent.auth import apply_network_settings, build_m2m_credentials
from mrm_deepagent.models import AppConfig
from mrm_deepagent.prompts import SYSTEM_PROMPT


class AgentRuntime:
    """Runtime wrapper that normalizes agent invocation behavior."""

    def __init__(self, agent: Any, log: Callable[[str], None] | None = None):
        self._agent = agent
        self._log = log or (lambda _message: None)

    def invoke_with_retry(
        self,
        section_prompt: str,
        retries: int = 3,
        timeout_s: int = 90,
        context_label: str | None = None,
    ) -> str:
        """Invoke the agent with retry and timeout control."""
        label = context_label or "agent-call"
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            self._log(f"{label}: attempt {attempt}/{retries} (timeout={timeout_s}s) started.")
            started_at = time.perf_counter()
            try:
                response = self._invoke_with_timeout(
                    section_prompt,
                    timeout_s=timeout_s,
                    context_label=label,
                )
                elapsed = time.perf_counter() - started_at
                self._log(f"{label}: attempt {attempt}/{retries} succeeded in {elapsed:.1f}s.")
                return response
            except Exception as exc:  # noqa: BLE001 - intentional retry wrapper
                last_error = exc
                elapsed = time.perf_counter() - started_at
                self._log(
                    f"{label}: attempt {attempt}/{retries} failed in {elapsed:.1f}s "
                    f"({type(exc).__name__}: {exc})"
                )
                if attempt < retries:
                    backoff = 0.5 * attempt
                    self._log(f"{label}: sleeping {backoff:.1f}s before retry.")
                    time.sleep(0.5 * attempt)
        raise RuntimeError(
            f"Agent invocation failed after {retries} attempts: {last_error}"
        ) from last_error

    def _invoke_with_timeout(self, section_prompt: str, timeout_s: int, context_label: str) -> str:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._invoke_once, section_prompt, context_label)
            try:
                return future.result(timeout=timeout_s)
            except FutureTimeoutError as exc:
                raise TimeoutError(f"Agent invocation timed out after {timeout_s}s.") from exc

    def _invoke_once(self, section_prompt: str, context_label: str = "agent-call") -> str:
        if hasattr(self._agent, "invoke"):
            payload_candidates = [
                section_prompt,
                {"input": section_prompt},
                {"messages": [{"role": "user", "content": section_prompt}]},
            ]
            payload_labels = ["raw-string", "input-dict", "messages-dict"]
            for idx, payload in enumerate(payload_candidates):
                try:
                    self._log(
                        f"{context_label}: trying payload format {payload_labels[idx]}."
                    )
                    result = self._agent.invoke(payload)
                    return _response_to_text(result)
                except Exception:  # noqa: BLE001 - trying alternate payload shapes
                    continue
            raise RuntimeError("Agent invoke failed for all payload formats.")
        if callable(self._agent):
            self._log(f"{context_label}: invoking callable agent.")
            return _response_to_text(self._agent(section_prompt))
        raise RuntimeError("Agent object is not invokable.")


def build_agent(
    config: AppConfig,
    tools: list[Any],
    log: Callable[[str], None] | None = None,
) -> AgentRuntime:
    """Build deep agent with Gemini model."""
    logger = log or (lambda _message: None)
    logger(
        "Initializing Gemini runtime "
        f"(auth_mode={config.auth_mode.value}, vertexai={config.vertexai})."
    )

    model = _build_chat_model(config.model, config, log=logger)
    try:
        logger(f"Creating deep agent with {len(tools)} tools.")
        agent = _build_deep_agent(model=model, tools=tools)
    except Exception:  # noqa: BLE001 - fallback to direct model invoke
        logger("Deep agent creation failed, using direct chat model fallback.")
        agent = model
    return AgentRuntime(agent=agent, log=logger)


def _build_chat_model(
    model_name: str,
    config: AppConfig,
    log: Callable[[str], None] | None = None,
) -> Any:
    from langchain_google_genai import ChatGoogleGenerativeAI

    logger = log or (lambda _message: None)
    apply_network_settings(config)
    logger("Applied network settings (proxy/cert if configured).")
    common_kwargs = _chat_model_kwargs(config)
    logger(f"Constructing chat model '{model_name}'.")

    try:
        return ChatGoogleGenerativeAI(model=model_name, **common_kwargs)
    except Exception:  # noqa: BLE001
        logger(f"Primary model '{model_name}' failed. Falling back to '{config.fallback_model}'.")
        return ChatGoogleGenerativeAI(model=config.fallback_model, **common_kwargs)


def _chat_model_kwargs(config: AppConfig) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"temperature": config.temperature}

    if config.auth_mode.value == "m2m":
        kwargs["credentials"] = build_m2m_credentials(config)
        kwargs["vertexai"] = True
        kwargs["project"] = config.google_project
        kwargs["location"] = config.google_location
        return kwargs

    if config.google_api_key:
        kwargs["google_api_key"] = config.google_api_key

    if config.vertexai:
        kwargs["vertexai"] = True
        kwargs["project"] = config.google_project
        kwargs["location"] = config.google_location

    return kwargs


def _build_deep_agent(model: Any, tools: list[Any]) -> Any:
    from deepagents import create_deep_agent

    signature = inspect.signature(create_deep_agent)
    kwargs: dict[str, Any] = {}
    if "model" in signature.parameters:
        kwargs["model"] = model
    if "tools" in signature.parameters:
        kwargs["tools"] = tools
    if "system_prompt" in signature.parameters:
        kwargs["system_prompt"] = SYSTEM_PROMPT
    if "instructions" in signature.parameters:
        kwargs["instructions"] = SYSTEM_PROMPT
    if kwargs:
        return create_deep_agent(**kwargs)
    return create_deep_agent(model, tools)


def _response_to_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        if isinstance(response.get("output"), str):
            return response["output"]
        if isinstance(response.get("content"), str):
            return response["content"]
        if isinstance(response.get("messages"), list) and response["messages"]:
            return _response_to_text(response["messages"][-1])
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"])
        if texts:
            return "\n".join(texts)
    if hasattr(response, "model_dump"):
        dumped = response.model_dump()
        try:
            return json.dumps(dumped)
        except TypeError:
            return str(dumped)
    return str(response)
