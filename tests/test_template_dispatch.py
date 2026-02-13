from __future__ import annotations

from pathlib import Path

import pytest

from mrm_deepagent.exceptions import TemplateValidationError, UnsupportedTemplateError
from mrm_deepagent.models import ApplyReport, DraftDocument, TemplateFormat
from mrm_deepagent.template_applier import apply_draft_to_template
from mrm_deepagent.template_parser import parse_template


def test_parse_template_dispatch_docx_and_markdown(
    template_path: Path,
    markdown_template_path: Path,
) -> None:
    docx_parsed = parse_template(template_path)
    md_parsed = parse_template(markdown_template_path)
    assert docx_parsed.template_format == TemplateFormat.DOCX
    assert md_parsed.template_format == TemplateFormat.MARKDOWN


def test_parse_template_rejects_unsupported_extension(tmp_path: Path) -> None:
    bad = tmp_path / "bad.txt"
    bad.write_text("not a template", encoding="utf-8")
    with pytest.raises(TemplateValidationError):
        parse_template(bad)


def test_apply_dispatches_by_extension(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    draft = DraftDocument(sections=[])
    out = tmp_path / "out.docx"

    monkeypatch.setattr(
        "mrm_deepagent.template_applier.apply_draft_to_docx_template",
        lambda *_args, **_kwargs: ApplyReport(output_path="docx", unresolved_section_ids=[]),
    )
    monkeypatch.setattr(
        "mrm_deepagent.template_applier.apply_draft_to_markdown_template",
        lambda *_args, **_kwargs: ApplyReport(output_path="markdown", unresolved_section_ids=[]),
    )

    report_docx = apply_draft_to_template(tmp_path / "x.docx", draft, out)
    report_md = apply_draft_to_template(tmp_path / "x.md", draft, tmp_path / "out.md")
    assert report_docx.output_path == "docx"
    assert report_md.output_path == "markdown"


def test_apply_dispatch_rejects_unsupported_extension(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedTemplateError):
        apply_draft_to_template(
            tmp_path / "x.txt",
            DraftDocument(sections=[]),
            tmp_path / "out.txt",
        )
