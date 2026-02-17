from __future__ import annotations

import pytest

from mrm_deepagent import simple


def test_list_fill_sections_returns_only_fill_ids(tmp_path) -> None:
    template = tmp_path / "template.md"
    template.write_text(
        (
            "# [FILL][ID:document_control] Document Control\n\n"
            "Response:\n[[SECTION_CONTENT]]\n\n"
            "# [SKIP][ID:notes] Notes\n\n"
            "Response:\n[[SECTION_CONTENT]]\n\n"
            "# [FILL][ID:model_overview] Model Overview\n\n"
            "Response:\n[[SECTION_CONTENT]]\n"
        ),
        encoding="utf-8",
    )

    assert simple.list_fill_sections(str(template)) == ["document_control", "model_overview"]


def test_fill_markdown_template_replaces_only_requested_sections(tmp_path) -> None:
    template = tmp_path / "template.md"
    template.write_text(
        (
            "# [FILL][ID:document_control] Document Control\n\n"
            "Response:\n[[SECTION_CONTENT]]\n\n"
            "# [FILL][ID:model_overview] Model Overview\n\n"
            "Response:\n[[SECTION_CONTENT]]\n"
        ),
        encoding="utf-8",
    )
    output = tmp_path / "rendered.md"

    message = simple.fill_markdown_template(
        template_path=str(template),
        section_content={"document_control": "Owner: MRM Team"},
        output_path=str(output),
    )
    rendered = output.read_text(encoding="utf-8")

    assert "Owner: MRM Team" in rendered
    assert rendered.count("[[SECTION_CONTENT]]") == 1
    assert "Filled sections: document_control" in message


def test_fill_markdown_template_raises_when_token_is_missing(tmp_path) -> None:
    template = tmp_path / "template.md"
    template.write_text(
        (
            "# [FILL][ID:document_control] Document Control\n\n"
            "Response:\nMissing token here.\n"
        ),
        encoding="utf-8",
    )
    output = tmp_path / "rendered.md"

    with pytest.raises(ValueError, match="missing required token"):
        simple.fill_markdown_template(
            template_path=str(template),
            section_content={"document_control": "Owner: MRM Team"},
            output_path=str(output),
        )


def test_create_doc_gen_agent_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GOOGLE_API_KEY is required"):
        simple.create_doc_gen_agent(["examples/simple_agent_template.md"], api_key=None)


def test_create_doc_gen_agent_rejects_non_markdown_templates(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    with pytest.raises(ValueError, match="Only markdown templates"):
        simple.create_doc_gen_agent(["examples/fictitious_mrm_template.docx"])


def test_create_doc_gen_agent_wires_dependencies(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    captured: dict[str, object] = {}

    def fake_model(**kwargs):
        captured["model_kwargs"] = kwargs
        return "MODEL"

    def fake_backend(*, root_dir: str, virtual_mode: bool):
        captured["backend_kwargs"] = {"root_dir": root_dir, "virtual_mode": virtual_mode}
        return "BACKEND"

    def fake_create_deep_agent(**kwargs):
        captured["agent_kwargs"] = kwargs
        return "AGENT"

    monkeypatch.setattr(simple, "ChatGoogleGenerativeAI", fake_model)
    monkeypatch.setattr(simple, "FilesystemBackend", fake_backend)
    monkeypatch.setattr(simple, "create_deep_agent", fake_create_deep_agent)

    agent = simple.create_doc_gen_agent(
        ["examples/simple_agent_template.md"],
        root_dir="examples",
    )

    assert agent == "AGENT"
    assert captured["model_kwargs"] == {
        "model": "gemini-3-flash-preview",
        "google_api_key": "test-key",
        "temperature": 0.1,
    }
    assert captured["backend_kwargs"] == {"root_dir": "examples", "virtual_mode": False}
    assert captured["agent_kwargs"]["tools"] == [
        simple.execute_tests,
        simple.list_fill_sections,
        simple.fill_markdown_template,
    ]
