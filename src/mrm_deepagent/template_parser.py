"""DOCX template parsing and validation."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document

from mrm_deepagent.models import ParsedTemplate, SectionType, TemplateSection

_MARKER_RE = re.compile(
    r"^\[(FILL|SKIP|VALIDATOR)\]\[ID:([A-Za-z0-9_-]+)\]\s+(.+?)\s*$",
    re.IGNORECASE,
)
_CHECKBOX_RE = re.compile(r"\[\[CHECK:([A-Za-z0-9_-]+)\]\]")


def parse_template(docx_path: Path) -> ParsedTemplate:
    """Parse template headings and gather section bodies."""
    document = Document(str(docx_path))
    parsed = ParsedTemplate(source_path=str(docx_path), sections=[], parser_errors=[])

    current_section: TemplateSection | None = None
    body_lines: list[str] = []

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

    for idx, paragraph in enumerate(document.paragraphs):
        text = paragraph.text.strip()
        if _is_heading(paragraph.style.name if paragraph.style else ""):
            flush_current()
            match = _MARKER_RE.match(text)
            if match:
                section_type = SectionType(match.group(1).lower())
                current_section = TemplateSection(
                    id=match.group(2),
                    title=match.group(3),
                    section_type=section_type,
                    marker_text=text,
                    heading_index=idx,
                )
            else:
                if _looks_like_marker(text):
                    parsed.parser_errors.append(
                        f"Malformed marker heading at paragraph {idx + 1}: '{text}'"
                    )
                current_section = None
        elif current_section is not None:
            body_lines.append(paragraph.text)

    flush_current()
    return parsed


def validate_template(parsed: ParsedTemplate) -> list[str]:
    """Return validation errors for parsed template."""
    errors = list(parsed.parser_errors)
    if not parsed.sections:
        errors.append("No template sections found with marker tags.")
        return errors

    seen: set[str] = set()
    for section in parsed.sections:
        if section.id in seen:
            errors.append(f"Duplicate section ID: {section.id}")
        seen.add(section.id)

    if not any(section.section_type == SectionType.FILL for section in parsed.sections):
        errors.append("Template must contain at least one [FILL] section.")

    return errors


def extract_checkbox_tokens(text: str) -> list[str]:
    """Extract checkbox token names from body text."""
    return list(dict.fromkeys(_CHECKBOX_RE.findall(text)))


def _is_heading(style_name: str) -> bool:
    return style_name.lower().startswith("heading")


def _looks_like_marker(text: str) -> bool:
    marker_tokens = ("[FILL]", "[SKIP]", "[VALIDATOR]", "[ID:")
    return any(token in text.upper() for token in marker_tokens)
