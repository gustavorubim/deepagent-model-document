from __future__ import annotations

from pathlib import Path

import pytest

from mrm_deepagent.draft_parser import (
    parse_draft_markdown,
    parse_draft_text,
    serialize_draft_markdown,
)
from mrm_deepagent.exceptions import DraftParseError
from mrm_deepagent.models import (
    CheckboxToken,
    DraftDocument,
    DraftSection,
    DraftStatus,
    MissingItem,
)


def test_parse_draft_text_valid() -> None:
    text = """
## [ID:exec_summary] Executive Summary
```yaml
status: complete
checkboxes:
  - name: model_validated
    checked: true
attachments: []
evidence: ["train.py:10"]
missing_items: []
```
Body text here.
""".strip()

    draft = parse_draft_text(text)
    assert len(draft.sections) == 1
    assert draft.sections[0].id == "exec_summary"
    assert draft.sections[0].status == DraftStatus.COMPLETE


def test_parse_draft_text_missing_yaml_raises() -> None:
    text = "## [ID:exec_summary] Executive Summary\nNo yaml block"
    with pytest.raises(DraftParseError):
        parse_draft_text(text)


def test_serialize_roundtrip() -> None:
    draft = DraftDocument(
        sections=[
            DraftSection(
                id="data_description",
                title="Data Description",
                status=DraftStatus.PARTIAL,
                checkboxes=[CheckboxToken(name="data_checked", checked=False)],
                attachments=["results/metrics.json"],
                evidence=["evaluate.py:12"],
                missing_items=[
                    MissingItem(
                        id="missing_data_owner",
                        section_id="data_description",
                        question="Who owns data quality checks?",
                    )
                ],
                body="Content body",
            )
        ]
    )

    markdown = serialize_draft_markdown(draft)
    reparsed = parse_draft_text(markdown)
    assert reparsed.sections[0].id == "data_description"
    assert reparsed.sections[0].missing_items[0].id == "missing_data_owner"


def test_parse_draft_markdown_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(DraftParseError):
        parse_draft_markdown(tmp_path / "missing.md")


def test_parse_draft_text_no_headings_raises() -> None:
    with pytest.raises(DraftParseError, match="No section headings"):
        parse_draft_text("plain text only")


def test_parse_draft_text_metadata_validation_errors() -> None:
    missing_key = """
## [ID:x] T
```yaml
status: complete
checkboxes: []
attachments: []
evidence: []
```
Body
""".strip()
    with pytest.raises(DraftParseError, match="missing metadata keys"):
        parse_draft_text(missing_key)

    bad_status = """
## [ID:x] T
```yaml
status: unknown
checkboxes: []
attachments: []
evidence: ["x"]
missing_items: []
```
Body
""".strip()
    with pytest.raises(DraftParseError, match="invalid status"):
        parse_draft_text(bad_status)

    bad_checkbox = """
## [ID:x] T
```yaml
status: complete
checkboxes: [1]
attachments: []
evidence: ["x"]
missing_items: []
```
Body
""".strip()
    with pytest.raises(DraftParseError, match="checkbox entries"):
        parse_draft_text(bad_checkbox)
