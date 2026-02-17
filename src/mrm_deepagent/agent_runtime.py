"""Deep agent runtime and invocation helpers."""

from __future__ import annotations

import inspect
import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any

from mrm_deepagent.models import AppConfig
from mrm_deepagent.prompts import SYSTEM_PROMPT
from mrm_deepagent.tracing import RunTraceCollector

_PAYLOAD_LABELS = ("raw-string", "input-dict", "messages-dict")


def _make_payloads(prompt: str) -> list[tuple[str, Any]]:
    return [
        ("raw-string", prompt),
        ("input-dict", {"input": prompt}),
        ("messages-dict", {"messages": [{"role": "user", "content": prompt}]}),
    ]


class AgentRuntime:
    """Runtime wrapper that normalizes agent invocation behavior."""

    def __init__(
        self,
        agent: Any,
        log: Callable[[str], None] | None = None,
        trace: RunTraceCollector | None = None,
    ):
        self._agent = agent
        self._log = log or (lambda _message: None)
        self._trace = trace
        self._payload_format: str | None = None

    def invoke_with_retry(
        self,
        section_prompt: str,
        retries: int = 3,
        timeout_s: int = 90,
        context_label: str | None = None,
    ) -> str:
        """Invoke the agent with retry and timeout control."""
        label = context_label or "agent-call"
        section_id = _section_id_from_label(label)
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            self._log(f"{label}: attempt {attempt}/{retries} (timeout={timeout_s}s) started.")
            self._trace_event(
                action="attempt_start",
                status="start",
                section_id=section_id,
                attempt=attempt,
                details={"retries": retries, "timeout_s": timeout_s},
            )
            started_at = time.perf_counter()
            try:
                response = self._invoke_with_timeout(
                    section_prompt,
                    timeout_s=timeout_s,
                    context_label=label,
                )
                elapsed = time.perf_counter() - started_at
                self._log(f"{label}: attempt {attempt}/{retries} succeeded in {elapsed:.1f}s.")
                self._trace_event(
                    action="attempt_complete",
                    status="ok",
                    section_id=section_id,
                    attempt=attempt,
                    duration_ms=int(elapsed * 1000),
                )
                return response
            except Exception as exc:  # noqa: BLE001 - intentional retry wrapper
                last_error = exc
                elapsed = time.perf_counter() - started_at
                self._log(
                    f"{label}: attempt {attempt}/{retries} failed in {elapsed:.1f}s "
                    f"({type(exc).__name__}: {exc})"
                )
                self._trace_event(
                    action="attempt_complete",
                    status="error",
                    section_id=section_id,
                    attempt=attempt,
                    duration_ms=int(elapsed * 1000),
                    details={"error_type": type(exc).__name__, "error": str(exc)},
                )
                if attempt < retries:
                    backoff = 0.5 * attempt
                    self._log(f"{label}: sleeping {backoff:.1f}s before retry.")
                    time.sleep(0.5 * attempt)
        raise RuntimeError(
            f"Agent invocation failed after {retries} attempts: {last_error}"
        ) from last_error

    def _invoke_with_timeout(self, section_prompt: str, timeout_s: int, context_label: str) -> str:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._invoke_once, section_prompt, context_label)
        try:
            return future.result(timeout=timeout_s)
        except FutureTimeoutError as exc:
            future.cancel()
            executor.shutdown(wait=False)
            self._trace_event(
                action="timeout",
                status="error",
                section_id=_section_id_from_label(context_label),
                details={"timeout_s": timeout_s},
            )
            raise TimeoutError(f"Agent invocation timed out after {timeout_s}s.") from exc
        finally:
            executor.shutdown(wait=False)

    def _invoke_once(self, section_prompt: str, context_label: str = "agent-call") -> str:
        section_id = _section_id_from_label(context_label)
        if hasattr(self._agent, "invoke"):
            if self._payload_format:
                self._log(
                    f"{context_label}: using cached payload format {self._payload_format}."
                )
                payload = self._build_payload(section_prompt, self._payload_format)
                self._trace_event(
                    action="payload_attempt",
                    status="start",
                    section_id=section_id,
                    payload_format=self._payload_format,
                )
                result = self._agent.invoke(payload)
                usage = _extract_token_usage(result)
                self._trace_event(
                    action="payload_attempt",
                    status="ok",
                    section_id=section_id,
                    payload_format=self._payload_format,
                    details=usage,
                )
                return _response_to_text(result)

            candidates = _make_payloads(section_prompt)
            for label, payload in candidates:
                try:
                    self._log(f"{context_label}: trying payload format {label}.")
                    self._trace_event(
                        action="payload_attempt",
                        status="start",
                        section_id=section_id,
                        payload_format=label,
                    )
                    result = self._agent.invoke(payload)
                    usage = _extract_token_usage(result)
                    text = _response_to_text(result)
                    self._payload_format = label
                    self._log(f"{context_label}: locked payload format to {label}.")
                    self._trace_event(
                        action="payload_attempt",
                        status="ok",
                        section_id=section_id,
                        payload_format=label,
                        details=usage,
                    )
                    return text
                except Exception as exc:  # noqa: BLE001 - trying alternate payload shapes
                    self._trace_event(
                        action="payload_attempt",
                        status="error",
                        section_id=section_id,
                        payload_format=label,
                        details={"error_type": type(exc).__name__, "error": str(exc)},
                    )
                    continue
            raise RuntimeError("Agent invoke failed for all payload formats.")
        if callable(self._agent):
            self._log(f"{context_label}: invoking callable agent.")
            self._trace_event(
                action="callable_invoke",
                status="start",
                section_id=section_id,
            )
            return _response_to_text(self._agent(section_prompt))
        raise RuntimeError("Agent object is not invokable.")

    def _trace_event(
        self,
        *,
        action: str,
        status: str,
        section_id: str | None = None,
        attempt: int | None = None,
        payload_format: str | None = None,
        duration_ms: int | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> None:
        if self._trace is None:
            return
        self._trace.log(
            event_type="llm_call",
            component="agent_runtime",
            action=action,
            status=status,
            section_id=section_id,
            attempt=attempt,
            payload_format=payload_format,
            duration_ms=duration_ms,
            details=details,
        )

    @staticmethod
    def _build_payload(prompt: str, fmt: str) -> Any:
        if fmt == "input-dict":
            return {"input": prompt}
        if fmt == "messages-dict":
            return {"messages": [{"role": "user", "content": prompt}]}
        return prompt


def build_agent(
    config: AppConfig,
    tools: list[Any],
    log: Callable[[str], None] | None = None,
    trace: RunTraceCollector | None = None,
) -> AgentRuntime:
    """Build deep agent with Gemini model."""
    logger = log or (lambda _message: None)
    logger("Initializing Gemini runtime using direct API key auth.")
    if trace is not None:
        trace.log(
            event_type="run",
            component="agent_runtime",
            action="build_agent",
            status="start",
            details={"tool_count": len(tools), "model": config.model},
        )

    model = _build_chat_model(config.model, config, log=logger)
    try:
        logger(f"Creating deep agent with {len(tools)} tools.")
        agent = _build_deep_agent(model=model, tools=tools)
    except Exception:  # noqa: BLE001 - fallback to direct model invoke
        logger("Deep agent creation failed, using direct chat model fallback.")
        agent = model
    if trace is not None:
        trace.log(
            event_type="run",
            component="agent_runtime",
            action="build_agent",
            status="ok",
            details={"tool_count": len(tools), "model": config.model},
        )
    return AgentRuntime(agent=agent, log=logger, trace=trace)


def _build_chat_model(
    _model_name: str,
    config: AppConfig,
    log: Callable[[str], None] | None = None,
) -> Any:
    from langchain_google_genai import ChatGoogleGenerativeAI

    logger = log or (lambda _message: None)
    logger(f"Constructing chat model '{config.model}'.")
    return ChatGoogleGenerativeAI(
        model=config.model,
        google_api_key="AIzaSyDxja9kAnDW7YbHjzhu-Ktol-jkkSHZuU8",
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


def _section_id_from_label(context_label: str | None) -> str | None:
    if not context_label:
        return None
    if context_label.startswith("section:"):
        return context_label.split(":", maxsplit=1)[1] or None
    return None


def _extract_token_usage(response: Any) -> dict[str, int] | None:
    usage_entries: list[dict[str, int]] = []
    _collect_usage_entries(response, usage_entries)
    if not usage_entries:
        return None
    input_tokens = sum(entry.get("input_tokens", 0) for entry in usage_entries)
    output_tokens = sum(entry.get("output_tokens", 0) for entry in usage_entries)
    total_tokens = sum(entry.get("total_tokens", 0) for entry in usage_entries)
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens
    if input_tokens == 0 and output_tokens == 0 and total_tokens == 0:
        return None
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _collect_usage_entries(value: Any, entries: list[dict[str, int]]) -> None:
    usage = _parse_usage_dict(value)
    if usage is not None:
        entries.append(usage)

    if isinstance(value, dict):
        for nested in value.values():
            if isinstance(nested, (dict, list, tuple)):
                _collect_usage_entries(nested, entries)
        return

    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_usage_entries(item, entries)
        return

    usage_metadata = getattr(value, "usage_metadata", None)
    usage = _parse_usage_dict(usage_metadata)
    if usage is not None:
        entries.append(usage)

    response_metadata = getattr(value, "response_metadata", None)
    if isinstance(response_metadata, dict):
        usage = _parse_usage_dict(response_metadata.get("token_usage"))
        if usage is not None:
            entries.append(usage)


def _parse_usage_dict(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    input_tokens = _coerce_token_count(
        value.get("input_tokens"),
        value.get("prompt_tokens"),
        value.get("prompt_token_count"),
    )
    output_tokens = _coerce_token_count(
        value.get("output_tokens"),
        value.get("completion_tokens"),
        value.get("candidates_token_count"),
    )
    total_tokens = _coerce_token_count(
        value.get("total_tokens"),
        value.get("total_token_count"),
    )
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens
    if input_tokens == 0 and output_tokens == 0 and total_tokens == 0:
        return None
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _coerce_token_count(*values: Any) -> int:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return max(value, 0)
        if isinstance(value, float):
            return max(int(value), 0)
        if isinstance(value, str):
            raw = value.strip()
            if raw.isdigit():
                return int(raw)
    return 0
