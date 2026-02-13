from __future__ import annotations

from pathlib import Path

from mrm_deepagent.cli import _configured_context_override, _resolve_context_path


def test_context_resolution_uses_explicit_override() -> None:
    resolved, legacy = _resolve_context_path(
        template_stem="fictitious_governance_template",
        explicit_context_path="C:/tmp/custom-context.md",
    )
    assert resolved == Path("C:/tmp/custom-context.md")
    assert legacy is None


def test_context_resolution_defaults_per_template_path() -> None:
    resolved, legacy = _resolve_context_path(
        template_stem="Fictitious Governance Template",
        explicit_context_path=None,
    )
    assert resolved == Path("contexts/fictitious-governance-template-additional-context.md")
    assert legacy is None


def test_configured_context_override_treats_default_as_not_explicit() -> None:
    assert _configured_context_override("additional-context.md") is None
    assert _configured_context_override("contexts/abc.md") == "contexts/abc.md"
