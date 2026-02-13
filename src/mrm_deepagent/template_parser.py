"""Template parser dispatcher."""

from __future__ import annotations

from pathlib import Path

from mrm_deepagent.exceptions import TemplateValidationError
from mrm_deepagent.models import ParsedTemplate, TemplateFormat
from mrm_deepagent.template_parser_docx import parse_docx_template, validate_docx_template
from mrm_deepagent.template_parser_markdown import (
    parse_markdown_template,
    validate_markdown_template,
)


def parse_template(template_path: Path) -> ParsedTemplate:
    """Parse a template file into a normalized representation."""
    suffix = template_path.suffix.lower()
    if suffix == ".docx":
        return parse_docx_template(template_path)
    if suffix in {".md", ".markdown"}:
        return parse_markdown_template(template_path)
    raise TemplateValidationError(
        f"Unsupported template extension '{template_path.suffix}'. "
        "Supported extensions are .docx and .md."
    )


def validate_template(parsed: ParsedTemplate) -> list[str]:
    """Return validation errors for parsed template."""
    errors: list[str]
    if parsed.template_format == TemplateFormat.DOCX:
        errors = validate_docx_template(parsed)
    elif parsed.template_format == TemplateFormat.MARKDOWN:
        errors = validate_markdown_template(parsed)
    else:
        errors = [f"Unsupported template format '{parsed.template_format}'."]

    seen: set[str] = set()
    for section in parsed.sections:
        if section.id in seen:
            errors.append(f"Duplicate section ID: {section.id}")
        seen.add(section.id)
    return errors
