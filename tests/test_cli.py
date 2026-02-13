from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from mrm_deepagent.cli import app

runner = CliRunner()


class _FakeRuntime:
    def invoke_with_retry(self, prompt: str, retries: int = 3, timeout_s: int = 90) -> str:
        if "exec_summary" in prompt:
            return json.dumps(
                {
                    "body": "Exec summary from mock.",
                    "checkboxes": [{"name": "model_validated", "checked": True}],
                    "attachments": [],
                    "evidence": ["train.py:1"],
                    "missing_items": [],
                }
            )
        return json.dumps(
            {
                "body": "Data section partial.",
                "checkboxes": [],
                "attachments": [],
                "evidence": [],
                "missing_items": [{"id": "missing_owner", "question": "Who owns data quality?"}],
            }
        )


def test_validate_template_success(template_path: Path) -> None:
    result = runner.invoke(app, ["validate-template", "--template", str(template_path)])
    assert result.exit_code == 0
    assert "Template valid" in result.stdout


def test_validate_template_fails_with_duplicate_id(duplicate_template_path: Path) -> None:
    result = runner.invoke(app, ["validate-template", "--template", str(duplicate_template_path)])
    assert result.exit_code == 2
    assert "Duplicate section ID" in result.stdout


def test_draft_command_creates_outputs(
    tmp_path: Path,
    template_path: Path,
    monkeypatch,
) -> None:
    codebase = tmp_path / "repo"
    codebase.mkdir()
    (codebase / "train.py").write_text("metric = 0.91\n", encoding="utf-8")
    context_file = tmp_path / "additinal-context.md"
    outputs = tmp_path / "outputs"

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr("mrm_deepagent.cli.build_agent", lambda *_args, **_kwargs: _FakeRuntime())

    result = runner.invoke(
        app,
        [
            "draft",
            "--codebase",
            str(codebase),
            "--template",
            str(template_path),
            "--output-root",
            str(outputs),
            "--context-file",
            str(context_file),
        ],
    )

    assert result.exit_code == 0
    run_dirs = [item for item in outputs.iterdir() if item.is_dir()]
    assert run_dirs
    assert (run_dirs[0] / "draft.md").exists()
    assert context_file.exists()


def test_draft_command_requires_api_key(
    tmp_path: Path,
    template_path: Path,
    monkeypatch,
) -> None:
    codebase = tmp_path / "repo"
    codebase.mkdir()
    (codebase / "train.py").write_text("metric = 0.91\n", encoding="utf-8")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["draft", "--codebase", str(codebase), "--template", str(template_path)],
    )
    assert result.exit_code == 3
    assert "GOOGLE_API_KEY" in result.stdout


def test_apply_command_happy_path(tmp_path: Path, template_path: Path) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        """
## [ID:exec_summary] Executive Summary
```yaml
status: complete
checkboxes:
  - name: model_validated
    checked: true
attachments: []
evidence: ["train.py:1"]
missing_items: []
```
Filled section.

## [ID:data_description] Data Description
```yaml
status: partial
checkboxes: []
attachments: []
evidence: []
missing_items:
  - id: missing_owner
    question: "Who owns data quality?"
```
Partial section body.
""".strip(),
        encoding="utf-8",
    )
    outputs = tmp_path / "outputs"
    result = runner.invoke(
        app,
        [
            "apply",
            "--draft",
            str(draft),
            "--template",
            str(template_path),
            "--output-root",
            str(outputs),
        ],
    )

    assert result.exit_code == 0
    run_dirs = [item for item in outputs.iterdir() if item.is_dir()]
    assert run_dirs
    assert (run_dirs[0] / "applied-document.docx").exists()


def test_apply_command_invalid_draft_returns_exit_4(tmp_path: Path, template_path: Path) -> None:
    bad_draft = tmp_path / "bad.md"
    bad_draft.write_text("## [ID:x] Bad\nNo yaml", encoding="utf-8")
    result = runner.invoke(
        app,
        ["apply", "--draft", str(bad_draft), "--template", str(template_path)],
    )
    assert result.exit_code == 4
