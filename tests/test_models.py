from __future__ import annotations

import pytest
from pydantic import ValidationError

from mrm_deepagent.models import DraftSection, DraftStatus, MissingItem


def test_draft_section_requires_evidence_or_missing_items() -> None:
    with pytest.raises(ValidationError):
        DraftSection(
            id="x",
            title="t",
            status=DraftStatus.COMPLETE,
            checkboxes=[],
            attachments=[],
            evidence=[],
            missing_items=[],
            body="body",
        )


def test_draft_section_accepts_missing_items() -> None:
    section = DraftSection(
        id="x",
        title="t",
        status=DraftStatus.PARTIAL,
        checkboxes=[],
        attachments=[],
        evidence=[],
        missing_items=[MissingItem(id="m", section_id="x", question="q")],
        body="body",
    )
    assert section.missing_items[0].id == "m"
