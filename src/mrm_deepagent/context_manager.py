"""Missing-context markdown parsing and writing."""

from __future__ import annotations

import re
from pathlib import Path

from mrm_deepagent.models import MissingItem

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def load_context(context_path: Path) -> list[MissingItem]:
    """Load missing items from markdown context file."""
    if not context_path.exists():
        return []
    text = context_path.read_text(encoding="utf-8")
    matches = list(_HEADING_RE.finditer(text))
    items: list[MissingItem] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        fields = _parse_block_fields(block)
        section_id = fields.get("section_id", "").strip()
        question = fields.get("question", "").strip()
        if not section_id or not question:
            continue
        items.append(
            MissingItem(
                id=match.group(1).strip(),
                section_id=section_id,
                question=question,
                user_response=fields.get("user_response", "").strip(),
            )
        )
    return items


def merge_missing_items(existing: list[MissingItem], new: list[MissingItem]) -> list[MissingItem]:
    """Merge missing items preserving user-provided responses."""
    merged: dict[tuple[str, str], MissingItem] = {
        (item.id, item.section_id): item for item in existing
    }
    for item in new:
        key = (item.id, item.section_id)
        if key in merged:
            preserved = merged[key]
            if preserved.user_response:
                merged[key] = item.model_copy(update={"user_response": preserved.user_response})
            else:
                merged[key] = item
        else:
            merged[key] = item
    return sorted(merged.values(), key=lambda value: (value.section_id, value.id))


def write_context(items: list[MissingItem], output_path: Path) -> None:
    """Write missing items to markdown file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for item in items:
        lines.extend(
            [
                f"## {item.id}",
                f"section_id: {item.section_id}",
                f"question: {item.question}",
                f"user_response: {item.user_response}",
                "",
            ]
        )
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def context_lookup(items: list[MissingItem]) -> dict[str, str]:
    """Build lookup map of section_id -> concatenated user responses."""
    by_section: dict[str, list[str]] = {}
    for item in items:
        if not item.user_response.strip():
            continue
        by_section.setdefault(item.section_id, []).append(
            f"- {item.id}: {item.user_response.strip()}"
        )
    return {key: "\n".join(values) for key, values in by_section.items()}


def _parse_block_fields(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields
