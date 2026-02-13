from __future__ import annotations

from pathlib import Path

from mrm_deepagent.context_manager import (
    context_lookup,
    load_context,
    merge_missing_items,
    write_context,
)
from mrm_deepagent.models import MissingItem


def test_write_and_load_context_roundtrip(tmp_path: Path) -> None:
    items = [
        MissingItem(id="m1", section_id="exec_summary", question="Need owner"),
        MissingItem(
            id="m2", section_id="exec_summary", question="Need date", user_response="2026-01-01"
        ),
    ]
    output = tmp_path / "additional-context.md"
    write_context(items, output)
    loaded = load_context(output)
    assert len(loaded) == 2
    assert loaded[1].user_response == "2026-01-01"


def test_merge_missing_items_preserves_user_response() -> None:
    existing = [MissingItem(id="m1", section_id="exec_summary", question="Q", user_response="A")]
    new = [MissingItem(id="m1", section_id="exec_summary", question="Q updated", user_response="")]
    merged = merge_missing_items(existing, new)
    assert merged[0].question == "Q updated"
    assert merged[0].user_response == "A"


def test_context_lookup_only_includes_filled_responses() -> None:
    items = [
        MissingItem(id="m1", section_id="s1", question="Q1", user_response="Answer one"),
        MissingItem(id="m2", section_id="s1", question="Q2", user_response=""),
    ]
    lookup = context_lookup(items)
    assert "s1" in lookup
    assert "m1: Answer one" in lookup["s1"]
    assert "m2" not in lookup["s1"]


def test_load_context_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_context(tmp_path / "not-found.md") == []
