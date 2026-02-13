"""Apply reviewed draft content to a DOCX template copy."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from mrm_deepagent.docx_utils import iter_block_items, iter_table_paragraphs
from mrm_deepagent.exceptions import AlreadyAppliedError, UnsupportedTemplateError
from mrm_deepagent.marker_utils import parse_heading_marker
from mrm_deepagent.models import ApplyReport, DraftDocument, DraftSection, SectionType

_CHECKBOX_RE = re.compile(r"\[\[CHECK:([A-Za-z0-9_-]+)\]\]")
_SECTION_CONTENT_TOKEN = "[[SECTION_CONTENT]]"
_APPLIED_MARKER = "[MRM_AGENT_APPLIED]"


@dataclass(slots=True)
class _SectionRange:
    section_type: SectionType
    section_id: str
    heading_block_index: int
    body_start_block: int
    body_end_block: int


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

    if _document_contains_marker(document, _APPLIED_MARKER) and not force:
        raise AlreadyAppliedError(
            "Template already contains apply marker. Use --force to override."
        )

    blocks = list(iter_block_items(document))
    section_ranges = _collect_section_ranges(blocks)
    fill_ranges = {
        section.section_id: section
        for section in section_ranges
        if section.section_type == SectionType.FILL
    }
    unresolved_ids: list[str] = []

    for section in draft.sections:
        target = fill_ranges.get(section.id)
        if target is None:
            continue
        _replace_section_body(blocks, target, section)
        _apply_checkboxes(blocks, target, section)
        if section.status.value == "partial":
            unresolved_ids.append(section.id)

    document.add_paragraph(_APPLIED_MARKER)
    document.save(str(out_path))
    return ApplyReport(output_path=str(out_path), unresolved_section_ids=unresolved_ids)


def _collect_section_ranges(blocks: list[Paragraph | Table]) -> list[_SectionRange]:
    heading_positions: list[int] = []
    parsed_markers: list[tuple[int, SectionType, str]] = []
    used_ids: set[str] = set()

    for idx, block in enumerate(blocks):
        if not isinstance(block, Paragraph):
            continue
        if not _is_heading(block):
            continue
        heading_positions.append(idx)
        parsed = parse_heading_marker(
            block.text,
            fallback_fill=True,
            used_ids=used_ids,
        )
        if parsed is None:
            continue
        section_type, section_id, _title = parsed
        parsed_markers.append((idx, section_type, section_id))

    ranges: list[_SectionRange] = []
    for heading_idx, section_type, section_id in parsed_markers:
        next_heading = next(
            (position for position in heading_positions if position > heading_idx), len(blocks)
        )
        ranges.append(
            _SectionRange(
                section_type=section_type,
                section_id=section_id,
                heading_block_index=heading_idx,
                body_start_block=heading_idx + 1,
                body_end_block=next_heading,
            )
        )
    return ranges


def _replace_section_body(
    blocks: list[Paragraph | Table],
    target: _SectionRange,
    section: DraftSection,
) -> None:
    body_paragraphs = _body_paragraphs(blocks, target)
    if not body_paragraphs:
        raise UnsupportedTemplateError(
            f"Section '{section.id}' has unsupported structure (no paragraph or table cells)."
        )

    replacement_text = section.body.strip()
    if section.checkboxes:
        checkbox_lines = [f"{item.name}: [[CHECK:{item.name}]]" for item in section.checkboxes]
        replacement_text += "\n\n" + "\n".join(checkbox_lines)
    if section.status.value == "partial":
        replacement_text += (
            "\n\nUNRESOLVED: This section includes missing information. "
            "Review additinal-context.md and update."
        )

    target_paragraph = _find_section_content_target(body_paragraphs)
    if _SECTION_CONTENT_TOKEN in target_paragraph.text:
        target_paragraph.text = target_paragraph.text.replace(
            _SECTION_CONTENT_TOKEN, replacement_text
        )
    else:
        target_paragraph.text = replacement_text


def _apply_checkboxes(
    blocks: list[Paragraph | Table],
    target: _SectionRange,
    section: DraftSection,
) -> None:
    checkbox_map = {checkbox.name: checkbox.checked for checkbox in section.checkboxes}
    for paragraph in _body_paragraphs(blocks, target):
        if "[[CHECK:" not in paragraph.text:
            continue
        paragraph.text = _replace_checkbox_tokens(paragraph.text, checkbox_map)


def _body_paragraphs(
    blocks: list[Paragraph | Table],
    target: _SectionRange,
) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    for block in blocks[target.body_start_block : target.body_end_block]:
        if isinstance(block, Paragraph):
            paragraphs.append(block)
        elif isinstance(block, Table):
            paragraphs.extend(iter_table_paragraphs(block))
    return paragraphs


def _find_section_content_target(paragraphs: list[Paragraph]) -> Paragraph:
    for paragraph in paragraphs:
        if _SECTION_CONTENT_TOKEN in paragraph.text:
            return paragraph
    for paragraph in paragraphs:
        if paragraph.text.strip():
            return paragraph
    return paragraphs[0]


def _replace_checkbox_tokens(text: str, checkbox_map: dict[str, bool]) -> str:
    def replacement(match: re.Match[str]) -> str:
        token_name = match.group(1)
        return "\u2612" if checkbox_map.get(token_name, False) else "\u2610"

    return _CHECKBOX_RE.sub(replacement, text)


def _is_heading(paragraph: Paragraph) -> bool:
    style_name = paragraph.style.name if paragraph.style else ""
    return style_name.lower().startswith("heading")


def _document_contains_marker(document: Document, marker: str) -> bool:
    for block in iter_block_items(document):
        if isinstance(block, Paragraph):
            if marker in block.text:
                return True
            continue
        for paragraph in iter_table_paragraphs(block):
            if marker in paragraph.text:
                return True
    return False
