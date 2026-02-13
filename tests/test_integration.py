from __future__ import annotations

import json
from pathlib import Path

from mrm_deepagent.context_manager import load_context, merge_missing_items, write_context
from mrm_deepagent.docx_applier import apply_draft_to_template
from mrm_deepagent.draft_generator import collect_missing_items, generate_draft, write_run_artifacts
from mrm_deepagent.repo_indexer import index_repo
from mrm_deepagent.template_parser import parse_template


class _IntegrationRuntime:
    def invoke_with_retry(self, prompt: str, retries: int = 3, timeout_s: int = 90) -> str:
        if "exec_summary" in prompt:
            return json.dumps(
                {
                    "body": "Generated executive summary.",
                    "checkboxes": [{"name": "model_validated", "checked": True}],
                    "attachments": [],
                    "evidence": ["README.md:1"],
                    "missing_items": [],
                }
            )
        return json.dumps(
            {
                "body": "Generated data description with gap.",
                "checkboxes": [],
                "attachments": ["results/metrics.json"],
                "evidence": [],
                "missing_items": [
                    {"id": "missing_review_date", "question": "What is review date?"}
                ],
            }
        )


def test_end_to_end_draft_and_apply(tmp_path: Path, template_path: Path) -> None:
    codebase = tmp_path / "repo"
    codebase.mkdir()
    (codebase / "README.md").write_text("Model details", encoding="utf-8")
    (codebase / "results").mkdir()
    (codebase / "results" / "metrics.json").write_text('{"r2": 0.9}\n', encoding="utf-8")

    parsed_template = parse_template(template_path)
    index = index_repo(codebase, allowlist=["*.md", "*.json"], denylist=[])
    draft = generate_draft(parsed_template, index, [], _IntegrationRuntime())

    run_dir = tmp_path / "outputs" / "run1"
    write_run_artifacts(run_dir, draft)
    assert (run_dir / "draft.md").exists()

    missing_items = collect_missing_items(draft)
    context_path = tmp_path / "additional-context.md"
    write_context(merge_missing_items([], missing_items), context_path)
    loaded = load_context(context_path)
    assert loaded and loaded[0].id == "missing_review_date"

    applied_path = tmp_path / "outputs" / "run1" / "applied-document.docx"
    apply_draft_to_template(template_path, draft, applied_path)
    assert applied_path.exists()
