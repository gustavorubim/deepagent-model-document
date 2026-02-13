"""Apply dispatcher for supported template formats."""

from __future__ import annotations

from pathlib import Path

from mrm_deepagent.docx_applier import apply_draft_to_template as apply_draft_to_docx_template
from mrm_deepagent.exceptions import UnsupportedTemplateError
from mrm_deepagent.markdown_applier import apply_draft_to_markdown_template
from mrm_deepagent.models import ApplyReport, DraftDocument


def apply_draft_to_template(
    template_path: Path,
    draft: DraftDocument,
    out_path: Path,
    *,
    force: bool = False,
    context_reference: str = "additional-context.md",
) -> ApplyReport:
    """Apply draft content using the applier that matches template extension."""
    suffix = template_path.suffix.lower()
    if suffix == ".docx":
        return apply_draft_to_docx_template(template_path, draft, out_path, force=force)
    if suffix in {".md", ".markdown"}:
        return apply_draft_to_markdown_template(
            template_path,
            draft,
            out_path,
            force=force,
            context_reference=context_reference,
        )
    raise UnsupportedTemplateError(
        f"Unsupported template extension '{template_path.suffix}'. "
        "Supported extensions are .docx and .md."
    )
