"""Apply reviewed draft content to a markdown governance template copy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from mrm_deepagent.exceptions import AlreadyAppliedError, UnsupportedTemplateError
from mrm_deepagent.marker_utils import parse_heading_marker
from mrm_deepagent.models import ApplyReport, DraftDocument, DraftSection, SectionType

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_CHECKBOX_RE = re.compile(r"\[\[CHECK:([A-Za-z0-9_-]+)\]\]")
_SECTION_CONTENT_TOKEN = "[[SECTION_CONTENT]]"
_APPLIED_MARKER = "<!-- MRM_AGENT_APPLIED -->"


@dataclass(slots=True)
class _SectionRange:
    section_type: SectionType
    section_id: str
    body_start: int
    body_end: int


def apply_draft_to_markdown_template(
    template_path: Path,
    draft: DraftDocument,
    out_path: Path,
    *,
    force: bool = False,
    context_reference: str = "additional-context.md",
) -> ApplyReport:
    """Apply draft markdown model onto a markdown template copy."""
    source_text = template_path.read_text(encoding="utf-8")
    already_applied = _APPLIED_MARKER in source_text
    if already_applied and not force:
        raise AlreadyAppliedError(
            "Template already contains apply marker. Use --force to override."
        )

    section_ranges = _collect_section_ranges(source_text)
    fill_ranges = {
        section.section_id: section
        for section in section_ranges
        if section.section_type == SectionType.FILL
    }
    replacements: list[tuple[int, int, str]] = []
    unresolved_ids: list[str] = []

    for section in draft.sections:
        target = fill_ranges.get(section.id)
        if target is None:
            continue

        existing_body = source_text[target.body_start : target.body_end]
        replacement_body = _replace_section_body(
            existing_body,
            section,
            context_reference,
            require_token=not (force and already_applied),
        )
        replacements.append((target.body_start, target.body_end, replacement_body))
        if section.status.value == "partial":
            unresolved_ids.append(section.id)

    output_text = source_text
    for start, end, value in sorted(replacements, key=lambda item: item[0], reverse=True):
        output_text = output_text[:start] + value + output_text[end:]

    if not output_text.endswith("\n"):
        output_text += "\n"
    output_text += f"\n{_APPLIED_MARKER}\n"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output_text, encoding="utf-8")
    return ApplyReport(output_path=str(out_path), unresolved_section_ids=unresolved_ids)


def _collect_section_ranges(text: str) -> list[_SectionRange]:
    heading_matches = list(_HEADING_RE.finditer(text))
    used_ids: set[str] = set()
    ranges: list[_SectionRange] = []

    for idx, match in enumerate(heading_matches):
        heading_text = match.group(2).strip()
        parsed = parse_heading_marker(
            heading_text,
            fallback_fill=False,
            used_ids=used_ids,
        )
        if parsed is None:
            continue
        section_type, section_id, _title = parsed
        body_start = match.end()
        body_end = heading_matches[idx + 1].start() if idx + 1 < len(heading_matches) else len(text)
        ranges.append(
            _SectionRange(
                section_type=section_type,
                section_id=section_id,
                body_start=body_start,
                body_end=body_end,
            )
        )
    return ranges


def _replace_section_body(
    existing_body: str,
    section: DraftSection,
    context_reference: str,
    *,
    require_token: bool,
) -> str:
    if _SECTION_CONTENT_TOKEN not in existing_body:
        if not require_token:
            return existing_body
        raise UnsupportedTemplateError(
            f"Section '{section.id}' is missing required token {_SECTION_CONTENT_TOKEN}."
        )

    replacement_text = section.body.strip()
    if section.checkboxes:
        checkbox_lines = [f"{item.name}: [[CHECK:{item.name}]]" for item in section.checkboxes]
        replacement_text += "\n\n" + "\n".join(checkbox_lines)
    if section.status.value == "partial":
        replacement_text += (
            "\n\nUNRESOLVED: This section includes missing information. "
            f"Review {context_reference} and update."
        )

    output = existing_body.replace(_SECTION_CONTENT_TOKEN, replacement_text)
    checkbox_map = {checkbox.name: checkbox.checked for checkbox in section.checkboxes}
    return _replace_checkbox_tokens(output, checkbox_map)


def _replace_checkbox_tokens(text: str, checkbox_map: dict[str, bool]) -> str:
    def replacement(match: re.Match[str]) -> str:
        token_name = match.group(1)
        return "\u2612" if checkbox_map.get(token_name, False) else "\u2610"

    return _CHECKBOX_RE.sub(replacement, text)
