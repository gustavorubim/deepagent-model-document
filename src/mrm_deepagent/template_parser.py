"""DOCX template parsing and validation."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from mrm_deepagent.docx_utils import iter_block_items, table_to_text
from mrm_deepagent.marker_utils import parse_heading_marker
from mrm_deepagent.models import ParsedTemplate, SectionType, TemplateSection

_CHECKBOX_RE = re.compile(r"\[\[CHECK:([A-Za-z0-9_-]+)\]\]")


def parse_template(docx_path: Path) -> ParsedTemplate:
    """Parse template headings and gather section bodies.

    Parsing is tolerant: untagged headings are treated as fillable sections.
    """
    document = Document(str(docx_path))
    parsed = ParsedTemplate(source_path=str(docx_path), sections=[], parser_errors=[])

    current_section: TemplateSection | None = None
    body_lines: list[str] = []
    used_ids: set[str] = set()

    def flush_current() -> None:
        nonlocal current_section, body_lines
        if current_section is None:
            return
        body_text = "\n".join(line for line in body_lines if line.strip()).strip()
        current_section.body_text = body_text
        current_section.checkbox_tokens = extract_checkbox_tokens(body_text)
        parsed.sections.append(current_section)
        current_section = None
        body_lines = []

    for idx, block in enumerate(iter_block_items(document)):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            style_name = block.style.name if block.style else ""
            if _is_heading(style_name):
                flush_current()
                parsed_marker = parse_heading_marker(text, fallback_fill=True, used_ids=used_ids)
                if parsed_marker is None:
                    current_section = None
                    continue
                section_type, section_id, title = parsed_marker
                current_section = TemplateSection(
                    id=section_id,
                    title=title,
                    section_type=section_type,
                    marker_text=text,
                    heading_index=idx,
                )
            elif current_section is not None and text:
                body_lines.append(text)
            continue

        if isinstance(block, Table):
            if current_section is None:
                continue
            table_text = table_to_text(block)
            if table_text:
                body_lines.append(table_text)

    flush_current()
    return parsed


def validate_template(parsed: ParsedTemplate) -> list[str]:
    """Return validation errors for parsed template."""
    errors = list(parsed.parser_errors)
    if not parsed.sections:
        errors.append("No template sections found with marker tags or heading sections.")
        return errors

    seen: set[str] = set()
    for section in parsed.sections:
        if section.id in seen:
            errors.append(f"Duplicate section ID: {section.id}")
        seen.add(section.id)

    if not any(section.section_type == SectionType.FILL for section in parsed.sections):
        errors.append("Template must contain at least one fillable section.")

    return errors


def extract_checkbox_tokens(text: str) -> list[str]:
    """Extract checkbox token names from body text."""
    return list(dict.fromkeys(_CHECKBOX_RE.findall(text)))


def _is_heading(style_name: str) -> bool:
    style_lower = style_name.lower()
    return style_lower.startswith("heading")


def _looks_like_marker(text: str) -> bool:
    marker_tokens = ("[FILL]", "[SKIP]", "[VALIDATOR]", "[ID:")
    return any(token in text.upper() for token in marker_tokens)
