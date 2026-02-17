"""Simplified deep-agent scaffold for markdown-only governance templates."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver

from mrm_deepagent.marker_utils import parse_heading_marker
from mrm_deepagent.models import SectionType

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_SECTION_CONTENT_TOKEN = "[[SECTION_CONTENT]]"


@dataclass(frozen=True)
class MarkedSection:
    """Template section with body boundaries in the source markdown."""

    section_type: SectionType
    section_id: str
    title: str
    body_start: int
    body_end: int


def execute_tests(test_paths: list[str], timeout_s: int = 300) -> dict[str, Any]:
    """Run pytest for each path and return stdout/stderr payloads."""
    targets = test_paths or ["tests"]
    results: dict[str, Any] = {}
    for target in targets:
        try:
            completed = subprocess.run(
                ["pytest", target],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            results[target] = {
                "success": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        except Exception as exc:  # noqa: BLE001 - tool must return structured errors
            results[target] = {"success": False, "error": str(exc)}
    return results


def list_fill_sections(template_path: str) -> list[str]:
    """Return fillable section IDs in a markdown template."""
    text = Path(template_path).read_text(encoding="utf-8")
    sections = _parse_marked_sections(text)
    return [section.section_id for section in sections if section.section_type == SectionType.FILL]


def fill_markdown_template(
    template_path: str,
    section_content: dict[str, str],
    output_path: str,
) -> str:
    """Replace [[SECTION_CONTENT]] in fill sections and write output markdown."""
    template_text = Path(template_path).read_text(encoding="utf-8")
    sections = _parse_marked_sections(template_text)
    replacements: list[tuple[int, int, str]] = []
    applied_ids: list[str] = []

    for section in sections:
        if section.section_type != SectionType.FILL:
            continue
        content = section_content.get(section.section_id)
        if content is None:
            continue
        body = template_text[section.body_start : section.body_end]
        if _SECTION_CONTENT_TOKEN not in body:
            raise ValueError(
                f"Section '{section.section_id}' is missing required token "
                f"{_SECTION_CONTENT_TOKEN}."
            )
        replacements.append(
            (
                section.body_start,
                section.body_end,
                body.replace(_SECTION_CONTENT_TOKEN, str(content), 1),
            )
        )
        applied_ids.append(section.section_id)

    rendered = template_text
    for start, end, replacement in sorted(replacements, reverse=True):
        rendered = f"{rendered[:start]}{replacement}{rendered[end:]}"

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    filled = ", ".join(applied_ids) if applied_ids else "<none>"
    return f"Template filled and saved to {output_path}. Filled sections: {filled}"


def create_doc_gen_agent(
    template_paths: list[str],
    model_name: str = "gemini-3-flash-preview",
    *,
    api_key: str | None = None,
    root_dir: str = ".",
) -> Any:
    """Create a markdown-only deep agent with Gemini API key auth."""
    if not template_paths:
        raise ValueError("At least one markdown template path is required.")
    if any(Path(path).suffix.lower() not in {".md", ".markdown"} for path in template_paths):
        raise ValueError("Only markdown templates are supported in this simplified agent.")

    key = api_key or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise ValueError("GOOGLE_API_KEY is required.")

    system_prompt = _build_system_prompt(template_paths)
    model = ChatGoogleGenerativeAI(model=model_name, google_api_key=key, temperature=0.1)
    tools = [execute_tests, list_fill_sections, fill_markdown_template]

    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        backend=FilesystemBackend(root_dir=root_dir, virtual_mode=False),
        memory=["ANALYSIS_NOTES.md", "MODEL_INSIGHTS.md"],
        checkpointer=MemorySaver(),
        interrupt_on={"execute_tests": True, "fill_markdown_template": True},
    )


def _build_system_prompt(template_paths: list[str]) -> str:
    template_list = ", ".join(template_paths)
    return (
        "You are a Documentation Generator Agent for ML governance markdown templates.\n"
        "You must only work with markdown templates using heading markers like "
        "[FILL][ID:section_id] Title.\n\n"
        "Always follow this sequence:\n"
        "1. Scan the repository and README for factual evidence.\n"
        "2. Run tests only when needed to verify behavior or metrics.\n"
        "3. Extract concrete facts with file references.\n"
        "4. Fill markdown sections by replacing [[SECTION_CONTENT]] with factual text.\n"
        "5. If evidence is missing, write explicit missing-information questions.\n\n"
        f"Templates provided: {template_list}"
    )


def _parse_marked_sections(text: str) -> list[MarkedSection]:
    matches = list(_HEADING_RE.finditer(text))
    sections: list[MarkedSection] = []
    used_ids: set[str] = set()
    for idx, match in enumerate(matches):
        parsed_marker = parse_heading_marker(
            match.group(2).strip(),
            fallback_fill=False,
            used_ids=used_ids,
        )
        if parsed_marker is None:
            continue
        section_type, section_id, title = parsed_marker
        body_start = match.end()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sections.append(
            MarkedSection(
                section_type=section_type,
                section_id=section_id,
                title=title,
                body_start=body_start,
                body_end=body_end,
            )
        )
    return sections
