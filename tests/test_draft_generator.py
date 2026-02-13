from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from mrm_deepagent.context_manager import load_context, merge_missing_items
from mrm_deepagent.draft_generator import (
    _coerce_str_list,
    _parse_checkboxes,
    _parse_missing_items,
    _parse_response_payload,
    _response_to_draft_section,
    build_tools,
    collect_missing_items,
    generate_draft,
    write_run_artifacts,
)
from mrm_deepagent.models import MissingItem
from mrm_deepagent.repo_indexer import index_repo
from mrm_deepagent.template_parser import parse_template


class _FakeRuntime:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._idx = 0

    def invoke_with_retry(self, _: str, retries: int = 3, timeout_s: int = 90) -> str:
        response = self._responses[self._idx]
        self._idx += 1
        return response


def test_generate_draft_and_write_artifacts(tmp_path: Path, template_path: Path) -> None:
    codebase = tmp_path / "repo"
    codebase.mkdir()
    (codebase / "train.py").write_text("metric = 0.91\n", encoding="utf-8")

    parsed_template = parse_template(template_path)
    repo_index = index_repo(codebase, allowlist=["*.py"], denylist=[])

    responses = [
        json.dumps(
            {
                "body": "Executive summary body",
                "checkboxes": [{"name": "model_validated", "checked": True}],
                "attachments": ["results/metrics.json"],
                "evidence": ["train.py:1"],
                "missing_items": [],
            }
        ),
        "{}",
    ]
    runtime = _FakeRuntime(responses)
    draft = generate_draft(parsed_template, repo_index, [], runtime)
    assert len(draft.sections) == 2
    assert draft.sections[0].evidence == ["train.py:1"]
    assert draft.sections[1].missing_items

    run_dir = tmp_path / "run"
    write_run_artifacts(run_dir, draft)
    assert (run_dir / "draft.md").exists()
    assert (run_dir / "draft-summary.json").exists()
    assert (run_dir / "missing-items.json").exists()
    assert (run_dir / "attachments-manifest.csv").exists()

    missing = collect_missing_items(draft)
    merged = merge_missing_items([], missing)
    context_path = tmp_path / "additional-context.md"
    from mrm_deepagent.context_manager import write_context

    write_context(merged, context_path)
    loaded = load_context(context_path)
    assert loaded


def test_build_tools_returns_langchain_tools(tmp_path: Path) -> None:
    codebase = tmp_path / "repo"
    codebase.mkdir()
    (codebase / "file.md").write_text("abc", encoding="utf-8")
    index = index_repo(codebase, allowlist=["*.md"], denylist=[])
    tools = build_tools(
        index, [MissingItem(id="x", section_id="s1", question="q", user_response="a")]
    )
    assert len(tools) == 4
    listed = tools[0].invoke({"limit": 10})
    assert "file.md" in listed
    read_value = tools[1].invoke({"path": "file.md"})
    assert read_value == "abc"
    searched = tools[2].invoke({"query": "ab", "limit": 5})
    assert "file.md" in searched
    context_value = tools[3].invoke({"section_id": "s1"})
    assert "x: a" in context_value


def test_build_tools_returns_empty_when_langchain_tool_import_fails(
    tmp_path: Path, monkeypatch
) -> None:
    codebase = tmp_path / "repo"
    codebase.mkdir()
    (codebase / "file.md").write_text("abc", encoding="utf-8")
    index = index_repo(codebase, allowlist=["*.md"], denylist=[])
    monkeypatch.setitem(sys.modules, "langchain_core.tools", types.SimpleNamespace())
    assert build_tools(index, []) == []


def test_response_helpers_cover_fallback_paths() -> None:
    payload = _parse_response_payload('prefix {"body":"x","evidence":["a"]} suffix')
    assert payload["body"] == "x"
    assert _parse_response_payload("not json") == {}

    section = _response_to_draft_section("{}", section_id="s1", title="T")
    assert section.status.value == "partial"
    assert section.missing_items

    assert _parse_checkboxes("bad-type") == []
    assert _coerce_str_list("bad-type") == []
    assert _parse_missing_items("bad-type", section_id="s1") == []
    assert _parse_missing_items([{"id": "x"}, "bad"], section_id="s1") == []
