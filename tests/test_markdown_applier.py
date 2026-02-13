from __future__ import annotations

from pathlib import Path

import pytest

from mrm_deepagent.exceptions import AlreadyAppliedError
from mrm_deepagent.markdown_applier import apply_draft_to_markdown_template
from mrm_deepagent.models import (
    CheckboxToken,
    DraftDocument,
    DraftSection,
    DraftStatus,
    MissingItem,
)


def _build_markdown_draft() -> DraftDocument:
    return DraftDocument(
        sections=[
            DraftSection(
                id="model_overview",
                title="Model Overview",
                status=DraftStatus.COMPLETE,
                checkboxes=[],
                attachments=[],
                evidence=["README.md:1"],
                missing_items=[],
                body="Overview body content.",
            ),
            DraftSection(
                id="model_purpose",
                title="Purpose",
                status=DraftStatus.PARTIAL,
                checkboxes=[CheckboxToken(name="intended_use_defined", checked=True)],
                attachments=[],
                evidence=["README.md:2"],
                missing_items=[
                    MissingItem(
                        id="missing_scope",
                        section_id="model_purpose",
                        question="Need scope details.",
                    )
                ],
                body="Purpose body content.",
            ),
        ]
    )


def test_markdown_apply_updates_fill_sections(markdown_template_path: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "applied.md"
    report = apply_draft_to_markdown_template(
        markdown_template_path,
        _build_markdown_draft(),
        out_path,
        context_reference="contexts/template-additional-context.md",
    )
    assert report.unresolved_section_ids == ["model_purpose"]

    text = out_path.read_text(encoding="utf-8")
    assert "Overview body content." in text
    assert "Purpose body content." in text
    assert "\u2612" in text
    assert "UNRESOLVED" in text
    assert "contexts/template-additional-context.md" in text
    assert "[SKIP][ID:reviewer_notes]" in text
    assert "[VALIDATOR][ID:validation_signoff]" in text


def test_markdown_apply_rejects_already_applied_without_force(
    markdown_template_path: Path,
    tmp_path: Path,
) -> None:
    first_output = tmp_path / "first.md"
    apply_draft_to_markdown_template(markdown_template_path, _build_markdown_draft(), first_output)
    with pytest.raises(AlreadyAppliedError):
        apply_draft_to_markdown_template(
            first_output,
            _build_markdown_draft(),
            tmp_path / "second.md",
        )


def test_markdown_apply_allows_force(markdown_template_path: Path, tmp_path: Path) -> None:
    first_output = tmp_path / "first.md"
    second_output = tmp_path / "second.md"
    apply_draft_to_markdown_template(markdown_template_path, _build_markdown_draft(), first_output)
    apply_draft_to_markdown_template(
        first_output,
        _build_markdown_draft(),
        second_output,
        force=True,
    )
    assert second_output.exists()
