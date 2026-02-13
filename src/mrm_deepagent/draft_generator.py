"""Draft generation workflow."""

from __future__ import annotations

import csv
import inspect
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from mrm_deepagent.context_manager import context_lookup
from mrm_deepagent.draft_parser import serialize_draft_markdown
from mrm_deepagent.models import (
    CheckboxToken,
    DraftDocument,
    DraftSection,
    DraftStatus,
    MissingItem,
    ParsedTemplate,
    SectionType,
)
from mrm_deepagent.prompts import build_section_prompt
from mrm_deepagent.repo_indexer import RepoIndex, list_repo_files, read_index_file, search_repo
from mrm_deepagent.tracing import RunTraceCollector


def build_tools(
    repo_index: RepoIndex,
    context_items: list[MissingItem],
    trace: RunTraceCollector | None = None,
) -> list[Any]:
    """Build toolset for deep agent."""
    try:
        from langchain_core.tools import tool
    except Exception:  # noqa: BLE001
        return []

    context_by_section = context_lookup(context_items)

    @tool
    def list_files(limit: int = 200) -> str:
        """List repository files available for evidence extraction."""
        started_at = perf_counter()
        _log_tool_trace(trace, "list_files", "start", details={"limit": limit})
        try:
            files = list_repo_files(repo_index, limit=limit)
            _log_tool_trace(
                trace,
                "list_files",
                "ok",
                duration_ms=int((perf_counter() - started_at) * 1000),
                details={"limit": limit, "result_count": len(files)},
            )
            return "\n".join(files)
        except Exception as exc:  # noqa: BLE001
            _log_tool_trace(
                trace,
                "list_files",
                "error",
                duration_ms=int((perf_counter() - started_at) * 1000),
                details={"limit": limit, "error_type": type(exc).__name__, "error": str(exc)},
            )
            raise

    @tool
    def read_file(path: str) -> str:
        """Read repository file content by relative path."""
        started_at = perf_counter()
        _log_tool_trace(trace, "read_file", "start", details={"path": path})
        try:
            value = read_index_file(repo_index, path)
            _log_tool_trace(
                trace,
                "read_file",
                "ok",
                duration_ms=int((perf_counter() - started_at) * 1000),
                details={"path": path, "size": len(value)},
            )
            return value
        except Exception as exc:  # noqa: BLE001
            _log_tool_trace(
                trace,
                "read_file",
                "error",
                duration_ms=int((perf_counter() - started_at) * 1000),
                details={"path": path, "error_type": type(exc).__name__, "error": str(exc)},
            )
            raise

    @tool
    def search_files(query: str, limit: int = 10) -> str:
        """Search repository files containing a text query."""
        started_at = perf_counter()
        _log_tool_trace(
            trace,
            "search_files",
            "start",
            details={"query": query, "limit": limit},
        )
        try:
            matches = search_repo(repo_index, query, limit=limit)
            _log_tool_trace(
                trace,
                "search_files",
                "ok",
                duration_ms=int((perf_counter() - started_at) * 1000),
                details={"query": query, "limit": limit, "result_count": len(matches)},
            )
            return "\n".join(matches)
        except Exception as exc:  # noqa: BLE001
            _log_tool_trace(
                trace,
                "search_files",
                "error",
                duration_ms=int((perf_counter() - started_at) * 1000),
                details={
                    "query": query,
                    "limit": limit,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            raise

    @tool
    def read_context(section_id: str) -> str:
        """Read user-provided additional context for a section ID."""
        started_at = perf_counter()
        _log_tool_trace(
            trace,
            "read_context",
            "start",
            details={"section_id": section_id},
            section_id=section_id,
        )
        value = context_by_section.get(section_id, "")
        _log_tool_trace(
            trace,
            "read_context",
            "ok",
            duration_ms=int((perf_counter() - started_at) * 1000),
            details={"section_id": section_id, "has_context": bool(value)},
            section_id=section_id,
        )
        return value

    return [list_files, read_file, search_files, read_context]


def generate_draft(
    parsed_template: ParsedTemplate,
    repo_index: RepoIndex,
    context_items: list[MissingItem],
    runtime: Any,
    retries: int = 3,
    timeout_s: int = 90,
    progress_callback: Callable[[str], None] | None = None,
    trace: RunTraceCollector | None = None,
) -> DraftDocument:
    """Generate draft content section-by-section in deterministic order."""
    progress = progress_callback or (lambda _message: None)
    context_by_section = context_lookup(context_items)
    sections: list[DraftSection] = []
    fill_sections = [
        section for section in parsed_template.sections if section.section_type == SectionType.FILL
    ]
    progress(f"Preparing to draft {len(fill_sections)} fillable sections.")
    if trace is not None:
        trace.log(
            event_type="run",
            component="draft_generator",
            action="draft_start",
            status="start",
            details={
                "fill_sections": len(fill_sections),
                "repo_file_count": len(repo_index.files),
                "context_items": len(context_items),
            },
        )

    for idx, section in enumerate(fill_sections, start=1):
        progress(f"[{idx}/{len(fill_sections)}] Drafting section '{section.id}' ({section.title}).")
        if trace is not None:
            trace.log(
                event_type="section",
                component="draft_generator",
                action="section_start",
                status="start",
                section_id=section.id,
                details={"title": section.title, "index": idx, "total": len(fill_sections)},
            )
        prompt = build_section_prompt(
            section,
            extra_context=context_by_section.get(section.id, ""),
            template_format=parsed_template.template_format.value,
        )
        started_at = perf_counter()
        try:
            response = _invoke_runtime_with_progress(
                runtime,
                prompt,
                retries=retries,
                timeout_s=timeout_s,
                section_id=section.id,
            )
            parsed_section = _response_to_draft_section(response, section.id, section.title)
        except Exception as exc:  # noqa: BLE001 - per-section resilience
            elapsed = perf_counter() - started_at
            progress(
                f"[{idx}/{len(fill_sections)}] FAILED '{section.id}' after {elapsed:.1f}s "
                f"({type(exc).__name__}: {exc}). Producing partial stub."
            )
            if trace is not None:
                trace.log(
                    event_type="section",
                    component="draft_generator",
                    action="section_complete",
                    status="error",
                    section_id=section.id,
                    duration_ms=int(elapsed * 1000),
                    details={"error_type": type(exc).__name__, "error": str(exc)},
                )
            parsed_section = DraftSection(
                id=section.id,
                title=section.title,
                status=DraftStatus.PARTIAL,
                body="Section could not be generated due to an agent error.",
                missing_items=[
                    MissingItem(
                        id=f"{section.id}_agent_error",
                        section_id=section.id,
                        question=f"Agent failed to generate this section: {exc}",
                    )
                ],
            )
        else:
            elapsed = perf_counter() - started_at
            if trace is not None:
                trace.log(
                    event_type="section",
                    component="draft_generator",
                    action="section_complete",
                    status=parsed_section.status.value,
                    section_id=section.id,
                    duration_ms=int(elapsed * 1000),
                    details={
                        "evidence_count": len(parsed_section.evidence),
                        "missing_count": len(parsed_section.missing_items),
                    },
                )
        progress(
            f"[{idx}/{len(fill_sections)}] Completed '{section.id}' in {elapsed:.1f}s "
            f"(status={parsed_section.status.value}, evidence={len(parsed_section.evidence)}, "
            f"missing={len(parsed_section.missing_items)})."
        )
        sections.append(parsed_section)

    if trace is not None:
        partial_count = len(
            [section for section in sections if section.status == DraftStatus.PARTIAL]
        )
        trace.log(
            event_type="run",
            component="draft_generator",
            action="draft_complete",
            status="ok",
            details={"sections": len(sections), "partial_sections": partial_count},
        )
    return DraftDocument(sections=sections)


def write_run_artifacts(run_dir: Path, draft: DraftDocument) -> None:
    """Write markdown and supporting run artifacts."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "draft.md").write_text(serialize_draft_markdown(draft), encoding="utf-8")

    partial_ids = [
        section.id for section in draft.sections if section.status == DraftStatus.PARTIAL
    ]
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "section_count": len(draft.sections),
        "partial_sections": partial_ids,
    }
    (run_dir / "draft-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    missing_items = [
        item.model_dump() for section in draft.sections for item in section.missing_items
    ]
    (run_dir / "missing-items.json").write_text(
        json.dumps(missing_items, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with (run_dir / "attachments-manifest.csv").open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["section_id", "attachment"])
        for section in draft.sections:
            for attachment in section.attachments:
                writer.writerow([section.id, attachment])


def collect_missing_items(draft: DraftDocument) -> list[MissingItem]:
    """Collect missing items from generated draft."""
    return [item for section in draft.sections for item in section.missing_items]


def _response_to_draft_section(response_text: str, section_id: str, title: str) -> DraftSection:
    payload = _parse_response_payload(response_text)

    body = str(payload.get("body", "")).strip()
    if not body:
        body = "Information could not be generated from repository evidence."

    checkboxes = _parse_checkboxes(payload.get("checkboxes", []))
    attachments = _coerce_str_list(payload.get("attachments", []))
    evidence = _coerce_str_list(payload.get("evidence", []))
    missing_items = _parse_missing_items(payload.get("missing_items", []), section_id=section_id)

    if not evidence and not missing_items:
        missing_items = [
            MissingItem(
                id=f"{section_id}_missing_info",
                section_id=section_id,
                question="Required information was not provided by the codebase.",
            )
        ]

    status = DraftStatus.PARTIAL if missing_items else DraftStatus.COMPLETE

    return DraftSection(
        id=section_id,
        title=title,
        status=status,
        checkboxes=checkboxes,
        attachments=attachments,
        evidence=evidence,
        missing_items=missing_items,
        body=body,
    )


def _parse_response_payload(response_text: str) -> dict[str, Any]:
    try:
        loaded = json.loads(response_text)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass

    start = response_text.find("{")
    end = response_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = response_text[start : end + 1]
        try:
            loaded = json.loads(candidate)
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            pass
    return {}


def _parse_checkboxes(raw: Any) -> list[CheckboxToken]:
    if not isinstance(raw, list):
        return []
    parsed: list[CheckboxToken] = []
    for item in raw:
        if isinstance(item, dict) and "name" in item:
            parsed.append(
                CheckboxToken(name=str(item["name"]), checked=bool(item.get("checked", False)))
            )
    return parsed


def _coerce_str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def _parse_missing_items(raw: Any, section_id: str) -> list[MissingItem]:
    if not isinstance(raw, list):
        return []
    parsed: list[MissingItem] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if "id" not in item or "question" not in item:
            continue
        parsed.append(
            MissingItem(
                id=str(item["id"]),
                section_id=section_id,
                question=str(item["question"]),
                user_response=str(item.get("user_response", "")),
            )
        )
    return parsed


def _invoke_runtime_with_progress(
    runtime: Any,
    prompt: str,
    retries: int,
    timeout_s: int,
    section_id: str,
) -> str:
    invoke_method = runtime.invoke_with_retry
    parameters = inspect.signature(invoke_method).parameters
    if "context_label" in parameters:
        return invoke_method(
            prompt,
            retries=retries,
            timeout_s=timeout_s,
            context_label=f"section:{section_id}",
        )
    return invoke_method(prompt, retries=retries, timeout_s=timeout_s)


def _log_tool_trace(
    trace: RunTraceCollector | None,
    action: str,
    status: str,
    *,
    section_id: str | None = None,
    duration_ms: int | None = None,
    details: dict[str, Any] | str | None = None,
) -> None:
    if trace is None:
        return
    trace.log(
        event_type="tool_call",
        component="agent_tool",
        action=action,
        status=status,
        section_id=section_id,
        duration_ms=duration_ms,
        details=details,
    )
