"""Deep agent runtime and invocation helpers."""

from __future__ import annotations

import inspect
import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any

from mrm_deepagent.models import AppConfig
from mrm_deepagent.prompts import SYSTEM_PROMPT


class AgentRuntime:
    """Runtime wrapper that normalizes agent invocation behavior."""

    def __init__(self, agent: Any):
        self._agent = agent

    def invoke_with_retry(self, section_prompt: str, retries: int = 3, timeout_s: int = 90) -> str:
        """Invoke the agent with retry and timeout control."""
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                return self._invoke_with_timeout(section_prompt, timeout_s=timeout_s)
            except Exception as exc:  # noqa: BLE001 - intentional retry wrapper
                last_error = exc
                if attempt < retries:
                    time.sleep(0.5 * attempt)
        raise RuntimeError(
            f"Agent invocation failed after {retries} attempts: {last_error}"
        ) from last_error

    def _invoke_with_timeout(self, section_prompt: str, timeout_s: int) -> str:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._invoke_once, section_prompt)
            try:
                return future.result(timeout=timeout_s)
            except FutureTimeoutError as exc:
                raise TimeoutError(f"Agent invocation timed out after {timeout_s}s.") from exc

    def _invoke_once(self, section_prompt: str) -> str:
        if hasattr(self._agent, "invoke"):
            payload_candidates = [
                section_prompt,
                {"input": section_prompt},
                {"messages": [{"role": "user", "content": section_prompt}]},
            ]
            for payload in payload_candidates:
                try:
                    result = self._agent.invoke(payload)
                    return _response_to_text(result)
                except Exception:  # noqa: BLE001 - trying alternate payload shapes
                    continue
            raise RuntimeError("Agent invoke failed for all payload formats.")
        if callable(self._agent):
            return _response_to_text(self._agent(section_prompt))
        raise RuntimeError("Agent object is not invokable.")


def build_agent(config: AppConfig, tools: list[Any]) -> AgentRuntime:
    """Build deep agent with Gemini model."""

    model = _build_chat_model(config.model, config)
    try:
        agent = _build_deep_agent(model=model, tools=tools)
    except Exception:  # noqa: BLE001 - fallback to direct model invoke
        agent = model
    return AgentRuntime(agent=agent)


def _build_chat_model(model_name: str, config: AppConfig) -> Any:
    from langchain_google_genai import ChatGoogleGenerativeAI

    try:
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=config.google_api_key,
            temperature=config.temperature,
        )
    except Exception:  # noqa: BLE001
        return ChatGoogleGenerativeAI(
            model=config.fallback_model,
            google_api_key=config.google_api_key,
            temperature=config.temperature,
        )


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
