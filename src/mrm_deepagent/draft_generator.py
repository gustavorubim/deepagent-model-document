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


def build_tools(repo_index: RepoIndex, context_items: list[MissingItem]) -> list[Any]:
    """Build toolset for deep agent."""
    try:
        from langchain_core.tools import tool
    except Exception:  # noqa: BLE001
        return []

    context_by_section = context_lookup(context_items)

    @tool
    def list_files(limit: int = 200) -> str:
        """List repository files available for evidence extraction."""
        return "\n".join(list_repo_files(repo_index, limit=limit))

    @tool
    def read_file(path: str) -> str:
        """Read repository file content by relative path."""
        return read_index_file(repo_index, path)

    @tool
    def search_files(query: str, limit: int = 10) -> str:
        """Search repository files containing a text query."""
        return "\n".join(search_repo(repo_index, query, limit=limit))

    @tool
    def read_context(section_id: str) -> str:
        """Read user-provided additional context for a section ID."""
        return context_by_section.get(section_id, "")

    return [list_files, read_file, search_files, read_context]


def generate_draft(
    parsed_template: ParsedTemplate,
    repo_index: RepoIndex,
    context_items: list[MissingItem],
    runtime: Any,
    retries: int = 3,
    timeout_s: int = 90,
    progress_callback: Callable[[str], None] | None = None,
) -> DraftDocument:
    """Generate draft content section-by-section in deterministic order."""
    progress = progress_callback or (lambda _message: None)
    context_by_section = context_lookup(context_items)
    sections: list[DraftSection] = []
    fill_sections = [
        section for section in parsed_template.sections if section.section_type == SectionType.FILL
    ]
    progress(f"Preparing to draft {len(fill_sections)} fillable sections.")

    for idx, section in enumerate(fill_sections, start=1):
        progress(f"[{idx}/{len(fill_sections)}] Drafting section '{section.id}' ({section.title}).")
        prompt = build_section_prompt(section, extra_context=context_by_section.get(section.id, ""))
        started_at = perf_counter()
        response = _invoke_runtime_with_progress(
            runtime,
            prompt,
            retries=retries,
            timeout_s=timeout_s,
            section_id=section.id,
        )
        parsed_section = _response_to_draft_section(response, section.id, section.title)
        elapsed = perf_counter() - started_at
        progress(
            f"[{idx}/{len(fill_sections)}] Completed '{section.id}' in {elapsed:.1f}s "
            f"(status={parsed_section.status.value}, evidence={len(parsed_section.evidence)}, "
            f"missing={len(parsed_section.missing_items)})."
        )
        sections.append(parsed_section)

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
