from __future__ import annotations

import json
from pathlib import Path

from mrm_deepagent.context_manager import load_context, merge_missing_items, write_context
from mrm_deepagent.draft_generator import collect_missing_items, generate_draft, write_run_artifacts
from mrm_deepagent.repo_indexer import index_repo
from mrm_deepagent.template_applier import apply_draft_to_template
from mrm_deepagent.template_parser import parse_template


class _MarkdownIntegrationRuntime:
    def invoke_with_retry(self, prompt: str, retries: int = 3, timeout_s: int = 90) -> str:
        if "model_overview" in prompt:
            return json.dumps(
                {
                    "body": "Generated model overview.",
                    "checkboxes": [],
                    "attachments": [],
                    "evidence": ["README.md:1"],
                    "missing_items": [],
                }
            )
        return json.dumps(
            {
                "body": "Generated partial section.",
                "checkboxes": [{"name": "intended_use_defined", "checked": True}],
                "attachments": [],
                "evidence": ["README.md:2"],
                "missing_items": [{"id": "missing_scope", "question": "Need scope details."}],
            }
        )


def test_end_to_end_markdown_draft_and_apply(
    tmp_path: Path,
    markdown_template_path: Path,
) -> None:
    codebase = tmp_path / "repo"
    codebase.mkdir()
    (codebase / "README.md").write_text("Model details", encoding="utf-8")

    parsed_template = parse_template(markdown_template_path)
    index = index_repo(codebase, allowlist=["*.md"], denylist=[])
    draft = generate_draft(parsed_template, index, [], _MarkdownIntegrationRuntime())

    run_dir = tmp_path / "outputs" / "run1"
    write_run_artifacts(run_dir, draft)
    assert (run_dir / "draft.md").exists()

    missing_items = collect_missing_items(draft)
    context_path = tmp_path / "contexts" / "template-additional-context.md"
    write_context(merge_missing_items([], missing_items), context_path)
    loaded = load_context(context_path)
    assert loaded and loaded[0].id == "missing_scope"

    applied_path = tmp_path / "outputs" / "run1" / "applied-document.md"
    apply_draft_to_template(
        markdown_template_path,
        draft,
        applied_path,
        context_reference=str(context_path),
    )
    assert applied_path.exists()
    text = applied_path.read_text(encoding="utf-8")
    assert "Generated model overview." in text
    assert "UNRESOLVED" in text
