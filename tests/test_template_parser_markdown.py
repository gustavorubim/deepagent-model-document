from __future__ import annotations

from pathlib import Path

from mrm_deepagent.models import SectionType, TemplateFormat
from mrm_deepagent.template_parser import parse_template, validate_template


def test_parse_markdown_template_extracts_sections(markdown_template_path: Path) -> None:
    parsed = parse_template(markdown_template_path)
    assert parsed.template_format == TemplateFormat.MARKDOWN
    assert len(parsed.sections) == 4
    fill_sections = [
        section for section in parsed.sections if section.section_type == SectionType.FILL
    ]
    assert len(fill_sections) == 2
    assert "intended_use_defined" in fill_sections[1].checkbox_tokens


def test_validate_markdown_template_requires_section_content_token(
    markdown_template_missing_token_path: Path,
) -> None:
    parsed = parse_template(markdown_template_missing_token_path)
    errors = validate_template(parsed)
    assert any("[[SECTION_CONTENT]]" in error for error in errors)


def test_validate_markdown_template_detects_duplicate_ids(tmp_path: Path) -> None:
    template_path = tmp_path / "dup.md"
    template_path.write_text(
        (
            "# [FILL][ID:same] One\n\nResponse:\n[[SECTION_CONTENT]]\n\n"
            "# [FILL][ID:same] Two\n\nResponse:\n[[SECTION_CONTENT]]\n"
        ),
        encoding="utf-8",
    )
    parsed = parse_template(template_path)
    errors = validate_template(parsed)
    assert any("Duplicate section ID: same" in error for error in errors)
