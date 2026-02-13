from __future__ import annotations

from mrm_deepagent.models import SectionType, TemplateSection
from mrm_deepagent.prompts import SYSTEM_PROMPT, build_section_prompt


def test_build_section_prompt_contains_contract() -> None:
    section = TemplateSection(
        id="exec_summary",
        title="Executive Summary",
        section_type=SectionType.FILL,
        marker_text="[FILL][ID:exec_summary] Executive Summary",
        heading_index=1,
        body_text="Summarize objective and metrics.",
    )
    prompt = build_section_prompt(section, extra_context="Known owner: ML Team")
    assert '"missing_items"' in prompt
    assert "Known owner: ML Team" in prompt
    assert section.id in prompt
    assert "Never invent facts" in SYSTEM_PROMPT
