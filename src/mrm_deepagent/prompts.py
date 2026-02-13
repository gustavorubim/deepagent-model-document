"""Prompt templates for deep-agent invocations."""

from __future__ import annotations

from mrm_deepagent.models import TemplateSection

SYSTEM_PROMPT = """
You are a governance documentation assistant.
Rules:
- Never invent facts or metrics.
- Use only information in tools/context.
- If information is unavailable, create explicit missing_items.
- Return valid JSON only.
""".strip()


def build_section_prompt(
    section: TemplateSection,
    extra_context: str = "",
    template_format: str = "unknown",
) -> str:
    """Build prompt for a single fillable section."""
    context_block = extra_context.strip() or "None."
    return f"""
Generate content for one governance document section.

Section:
- id: {section.id}
- title: {section.title}
- template_format: {template_format}
- requirement text:
{section.body_text or "(no additional requirement text provided)"}

User-provided supplemental context:
{context_block}

Output format (JSON object only):
{{
  "body": "filled section narrative",
  "checkboxes": [{{"name": "token_name", "checked": true}}],
  "attachments": ["relative/path/to/artifact"],
  "evidence": ["relative/path.py:line"],
  "missing_items": [{{"id": "short_id", "question": "what is missing"}}]
}}

Quality rules:
- Include at least one evidence item or one missing_items entry.
- If any required information is absent, include missing_items.
- Keep writing concise, factual, and audit-friendly.
""".strip()
