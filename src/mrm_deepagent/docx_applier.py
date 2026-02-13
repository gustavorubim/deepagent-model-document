"""Apply reviewed draft content to a DOCX template copy."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from docx import Document

from mrm_deepagent.exceptions import AlreadyAppliedError, UnsupportedTemplateError
from mrm_deepagent.models import ApplyReport, DraftDocument, DraftSection, SectionType

_MARKER_RE = re.compile(
    r"^\[(FILL|SKIP|VALIDATOR)\]\[ID:([A-Za-z0-9_-]+)\]\s+(.+?)\s*$", re.IGNORECASE
)
_CHECKBOX_RE = re.compile(r"\[\[CHECK:([A-Za-z0-9_-]+)\]\]")
_APPLIED_MARKER = "[MRM_AGENT_APPLIED]"


@dataclass(slots=True)
class _SectionRange:
    section_type: SectionType
    section_id: str
    heading_index: int
    body_start: int
    body_end: int


def apply_draft_to_template(
    template_path: Path,
    draft: DraftDocument,
    out_path: Path,
    force: bool = False,
) -> ApplyReport:
    """Apply draft markdown model onto a template copy."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template_path, out_path)
    document = Document(str(out_path))

    if any(_APPLIED_MARKER in paragraph.text for paragraph in document.paragraphs) and not force:
        raise AlreadyAppliedError(
            "Template already contains apply marker. Use --force to override."
        )

    if document.tables:
        raise UnsupportedTemplateError(
            "Template contains tables. This applier supports paragraph-only templates."
        )

    section_ranges = _collect_section_ranges(document)
    fill_ranges = {
        section.section_id: section
        for section in section_ranges
        if section.section_type == SectionType.FILL
    }
    unresolved_ids: list[str] = []

    for section in draft.sections:
        if section.id not in fill_ranges:
            continue
        target = fill_ranges[section.id]
        if target.body_start >= target.body_end:
            raise UnsupportedTemplateError(
                f"Section '{section.id}' has no writable body paragraph beneath heading."
            )
        _replace_section_body(document, target, section)
        _apply_checkboxes(document, target, section)
        if section.status.value == "partial":
            unresolved_ids.append(section.id)

    document.add_paragraph(_APPLIED_MARKER)
    document.save(str(out_path))
    return ApplyReport(output_path=str(out_path), unresolved_section_ids=unresolved_ids)


def _collect_section_ranges(document: Document) -> list[_SectionRange]:
    headings: list[int] = []
    marker_headings: list[tuple[int, SectionType, str]] = []
    for idx, paragraph in enumerate(document.paragraphs):
        style_name = paragraph.style.name if paragraph.style else ""
        if style_name.lower().startswith("heading"):
            headings.append(idx)
            match = _MARKER_RE.match(paragraph.text.strip())
            if match:
                marker_headings.append((idx, SectionType(match.group(1).lower()), match.group(2)))

    ranges: list[_SectionRange] = []
    for heading_idx, section_type, section_id in marker_headings:
        next_heading = next(
            (value for value in headings if value > heading_idx), len(document.paragraphs)
        )
        ranges.append(
            _SectionRange(
                section_type=section_type,
                section_id=section_id,
                heading_index=heading_idx,
                body_start=heading_idx + 1,
                body_end=next_heading,
            )
        )
    return ranges


def _replace_section_body(document: Document, target: _SectionRange, section: DraftSection) -> None:
    paragraphs = document.paragraphs[target.body_start : target.body_end]
    if not paragraphs:
        raise UnsupportedTemplateError(
            f"Section '{section.id}' has unsupported structure (no body paragraphs)."
        )
    checkbox_block = ""
    if section.checkboxes:
        checkbox_lines = [f"{item.name}: [[CHECK:{item.name}]]" for item in section.checkboxes]
        checkbox_block = "\n\n" + "\n".join(checkbox_lines)
    unresolved_note = ""
    if section.status.value == "partial":
        unresolved_note = (
            "\n\nUNRESOLVED: This section includes missing information. "
            "Review additinal-context.md and update."
        )
    paragraphs[0].text = section.body.strip() + checkbox_block + unresolved_note
    for paragraph in paragraphs[1:]:
        paragraph.text = ""


def _apply_checkboxes(document: Document, target: _SectionRange, section: DraftSection) -> None:
    checkbox_map = {checkbox.name: checkbox.checked for checkbox in section.checkboxes}
    for paragraph in document.paragraphs[target.body_start : target.body_end]:
        if "[[CHECK:" not in paragraph.text:
            continue

        def replacement(match: re.Match[str]) -> str:
            name = match.group(1)
            return "☒" if checkbox_map.get(name, False) else "☐"

        paragraph.text = _CHECKBOX_RE.sub(replacement, paragraph.text)
