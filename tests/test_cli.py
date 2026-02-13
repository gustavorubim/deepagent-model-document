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
    assert "verbose:" in result.stdout


def test_validate_template_no_verbose_suppresses_progress(template_path: Path) -> None:
    result = runner.invoke(
        app,
        ["validate-template", "--template", str(template_path), "--no-verbose"],
    )
    assert result.exit_code == 0
    assert "Template valid" in result.stdout
    assert "verbose:" not in result.stdout


def test_validate_template_fails_with_duplicate_id(duplicate_template_path: Path) -> None:
    result = runner.invoke(app, ["validate-template", "--template", str(duplicate_template_path)])
    assert result.exit_code == 2
    assert "Duplicate section ID" in result.stdout


def test_validate_markdown_template_success(markdown_template_path: Path) -> None:
    result = runner.invoke(app, ["validate-template", "--template", str(markdown_template_path)])
    assert result.exit_code == 0
    assert "Template valid" in result.stdout


def test_validate_markdown_template_fails_on_missing_content_token(
    markdown_template_missing_token_path: Path,
) -> None:
    result = runner.invoke(
        app, ["validate-template", "--template", str(markdown_template_missing_token_path)]
    )
    assert result.exit_code == 2
    assert "[[SECTION_CONTENT]]" in result.stdout


def test_draft_command_creates_outputs(
    tmp_path: Path,
    template_path: Path,
    monkeypatch,
) -> None:
    codebase = tmp_path / "repo"
    codebase.mkdir()
    (codebase / "train.py").write_text("metric = 0.91\n", encoding="utf-8")
    context_file = tmp_path / "additional-context.md"
    outputs = tmp_path / "outputs"

    monkeypatch.chdir(tmp_path)
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
    assert (run_dirs[0] / "trace.json").exists()
    assert (run_dirs[0] / "trace.csv").exists()
    assert context_file.exists()
    assert "verbose:" in result.stdout


def test_draft_command_migrates_legacy_context_filename(
    tmp_path: Path,
    template_path: Path,
    monkeypatch,
) -> None:
    codebase = tmp_path / "repo"
    codebase.mkdir()
    (codebase / "train.py").write_text("metric = 0.91\n", encoding="utf-8")
    legacy_context_file = tmp_path / "additinal-context.md"
    legacy_context_file.write_text(
        (
            "## old_item\n"
            "section_id: exec_summary\n"
            "question: Legacy question\n"
            "user_response: Legacy response\n"
        ),
        encoding="utf-8",
    )
    new_context_file = tmp_path / "additional-context.md"

    monkeypatch.chdir(tmp_path)
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
            "--context-file",
            str(new_context_file),
        ],
    )
    assert result.exit_code == 0
    assert "Detected legacy context file" in result.stdout
    assert new_context_file.exists()
    assert "legacy response" in new_context_file.read_text(encoding="utf-8").lower()


def test_draft_markdown_template_uses_default_per_template_context(
    tmp_path: Path,
    markdown_template_path: Path,
    monkeypatch,
) -> None:
    codebase = tmp_path / "repo"
    codebase.mkdir()
    (codebase / "README.md").write_text("details\n", encoding="utf-8")
    outputs = tmp_path / "outputs"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr("mrm_deepagent.cli.build_agent", lambda *_args, **_kwargs: _FakeRuntime())

    result = runner.invoke(
        app,
        [
            "draft",
            "--codebase",
            str(codebase),
            "--template",
            str(markdown_template_path),
            "--output-root",
            str(outputs),
        ],
    )

    assert result.exit_code == 0
    assert (tmp_path / "contexts" / "template-additional-context.md").exists()


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


def test_draft_command_m2m_requires_m2m_settings(
    tmp_path: Path,
    template_path: Path,
    monkeypatch,
) -> None:
    codebase = tmp_path / "repo"
    codebase.mkdir()
    (codebase / "train.py").write_text("metric = 0.91\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "draft",
            "--codebase",
            str(codebase),
            "--template",
            str(template_path),
            "--auth-mode",
            "m2m",
        ],
    )
    assert result.exit_code == 3
    assert "M2M auth requires" in result.stdout


def test_draft_command_h2m_requires_h2m_settings(
    tmp_path: Path,
    template_path: Path,
    monkeypatch,
) -> None:
    codebase = tmp_path / "repo"
    codebase.mkdir()
    (codebase / "train.py").write_text("metric = 0.91\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "draft",
            "--codebase",
            str(codebase),
            "--template",
            str(template_path),
            "--auth-mode",
            "h2m",
        ],
    )
    assert result.exit_code == 3
    assert "H2M auth requires" in result.stdout


def test_draft_command_h2m_with_vertex_and_project_succeeds(
    tmp_path: Path,
    template_path: Path,
    monkeypatch,
) -> None:
    codebase = tmp_path / "repo"
    codebase.mkdir()
    (codebase / "train.py").write_text("metric = 0.91\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr("mrm_deepagent.cli.build_agent", lambda *_args, **_kwargs: _FakeRuntime())

    result = runner.invoke(
        app,
        [
            "draft",
            "--codebase",
            str(codebase),
            "--template",
            str(template_path),
            "--auth-mode",
            "h2m",
            "--vertexai",
            "--google-project",
            "proj-123",
        ],
    )
    assert result.exit_code == 0


def test_apply_command_happy_path(tmp_path: Path, template_path: Path, monkeypatch) -> None:
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
    monkeypatch.chdir(tmp_path)
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


def test_apply_command_markdown_template_outputs_md(
    tmp_path: Path,
    markdown_template_path: Path,
    monkeypatch,
) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        """
## [ID:model_overview] Model Overview
```yaml
status: complete
checkboxes: []
attachments: []
evidence: ["README.md:1"]
missing_items: []
```
Overview body.

## [ID:model_purpose] Purpose
```yaml
status: partial
checkboxes:
  - name: intended_use_defined
    checked: true
attachments: []
evidence: ["README.md:2"]
missing_items:
  - id: missing_scope
    question: "Need scope details."
```
Purpose body.
""".strip(),
        encoding="utf-8",
    )
    outputs = tmp_path / "outputs"
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [
            "apply",
            "--draft",
            str(draft),
            "--template",
            str(markdown_template_path),
            "--output-root",
            str(outputs),
        ],
    )
    assert result.exit_code == 0
    run_dirs = [item for item in outputs.iterdir() if item.is_dir()]
    assert run_dirs
    assert (run_dirs[0] / "applied-document.md").exists()


def test_apply_command_invalid_draft_returns_exit_4(
    tmp_path: Path, template_path: Path, monkeypatch
) -> None:
    bad_draft = tmp_path / "bad.md"
    bad_draft.write_text("## [ID:x] Bad\nNo yaml", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["apply", "--draft", str(bad_draft), "--template", str(template_path)],
    )
    assert result.exit_code == 4


def test_apply_command_unsupported_template_extension_returns_exit_5(
    tmp_path: Path,
    monkeypatch,
) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        """
## [ID:x] X
```yaml
status: partial
checkboxes: []
attachments: []
evidence: []
missing_items:
  - id: missing_x
    question: "Need x?"
```
Body
""".strip(),
        encoding="utf-8",
    )
    template = tmp_path / "template.txt"
    template.write_text("not supported", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["apply", "--draft", str(draft), "--template", str(template)],
    )
    assert result.exit_code == 5
