"""Markdown governance template parsing and validation."""

from __future__ import annotations

import re
from pathlib import Path

from mrm_deepagent.marker_utils import parse_heading_marker
from mrm_deepagent.models import ParsedTemplate, SectionType, TemplateFormat, TemplateSection

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_CHECKBOX_RE = re.compile(r"\[\[CHECK:([A-Za-z0-9_-]+)\]\]")
_SECTION_CONTENT_TOKEN = "[[SECTION_CONTENT]]"


def parse_markdown_template(markdown_path: Path) -> ParsedTemplate:
    """Parse markdown template sections from tagged headings."""
    text = markdown_path.read_text(encoding="utf-8")
    matches = list(_HEADING_RE.finditer(text))

    parsed = ParsedTemplate(
        source_path=str(markdown_path),
        template_format=TemplateFormat.MARKDOWN,
        template_stem=markdown_path.stem,
        sections=[],
        parser_errors=[],
    )
    used_ids: set[str] = set()

    for idx, match in enumerate(matches):
        heading_text = match.group(2).strip()
        parsed_marker = parse_heading_marker(heading_text, fallback_fill=False, used_ids=used_ids)
        if parsed_marker is None:
            continue

        section_type, section_id, title = parsed_marker
        body_start = match.end()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body_text = text[body_start:body_end].strip()
        parsed.sections.append(
            TemplateSection(
                id=section_id,
                title=title,
                section_type=section_type,
                marker_text=heading_text,
                heading_index=idx,
                body_text=body_text,
                checkbox_tokens=extract_checkbox_tokens(body_text),
            )
        )

    return parsed


def validate_markdown_template(parsed: ParsedTemplate) -> list[str]:
    """Validate markdown template requirements."""
    errors = list(parsed.parser_errors)
    if not parsed.sections:
        errors.append("No template sections found with markdown marker headings.")
        return errors

    if not any(section.section_type == SectionType.FILL for section in parsed.sections):
        errors.append("Template must contain at least one fillable section.")

    for section in parsed.sections:
        if section.section_type != SectionType.FILL:
            continue
        if _SECTION_CONTENT_TOKEN not in section.body_text:
            errors.append(
                f"Fill section '{section.id}' is missing required token [[SECTION_CONTENT]]."
            )
    return errors


def extract_checkbox_tokens(text: str) -> list[str]:
    """Extract checkbox token names from body text."""
    return list(dict.fromkeys(_CHECKBOX_RE.findall(text)))
