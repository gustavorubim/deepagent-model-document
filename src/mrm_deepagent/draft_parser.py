"""Draft markdown parsing and serialization."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from mrm_deepagent.exceptions import DraftParseError
from mrm_deepagent.models import (
    CheckboxToken,
    DraftDocument,
    DraftSection,
    DraftStatus,
    MissingItem,
)

_SECTION_HEADER_RE = re.compile(r"^##\s+\[ID:([A-Za-z0-9_-]+)\]\s+(.+?)\s*$", re.MULTILINE)
_YAML_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)


def parse_draft_markdown(path: Path) -> DraftDocument:
    """Parse draft markdown file into typed document."""
    if not path.exists():
        raise DraftParseError(f"Draft file does not exist: {path}")
    return parse_draft_text(path.read_text(encoding="utf-8"))


def parse_draft_text(text: str) -> DraftDocument:
    """Parse draft markdown content."""
    headers = list(_SECTION_HEADER_RE.finditer(text))
    if not headers:
        raise DraftParseError("No section headings found. Expected '## [ID:<section_id>] <title>'.")

    sections: list[DraftSection] = []
    for idx, header in enumerate(headers):
        start = header.start()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(text)
        chunk = text[start:end]
        section_id = header.group(1)
        title = header.group(2).strip()
        yaml_match = _YAML_RE.search(chunk)
        if not yaml_match:
            raise DraftParseError(f"Section '{section_id}' is missing required YAML code block.")

        metadata = _parse_metadata(yaml_match.group(1), section_id=section_id)
        body_start = yaml_match.end()
        body = chunk[body_start:].strip()

        sections.append(
            DraftSection(
                id=section_id,
                title=title,
                status=DraftStatus(metadata["status"]),
                checkboxes=metadata["checkboxes"],
                attachments=metadata["attachments"],
                evidence=metadata["evidence"],
                missing_items=metadata["missing_items"],
                body=body,
            )
        )

    return DraftDocument(sections=sections)


def serialize_draft_markdown(draft: DraftDocument) -> str:
    """Serialize draft document to markdown contract."""
    blocks: list[str] = []
    for section in draft.sections:
        metadata = {
            "status": section.status.value,
            "checkboxes": [
                {"name": checkbox.name, "checked": checkbox.checked}
                for checkbox in section.checkboxes
            ],
            "attachments": section.attachments,
            "evidence": section.evidence,
            "missing_items": [
                {
                    "id": item.id,
                    "question": item.question,
                    "section_id": item.section_id,
                }
                for item in section.missing_items
            ],
        }
        yaml_block = yaml.safe_dump(metadata, sort_keys=False).rstrip()
        blocks.extend(
            [
                f"## [ID:{section.id}] {section.title}",
                "```yaml",
                yaml_block,
                "```",
                "",
                section.body.strip(),
                "",
            ]
        )
    return "\n".join(blocks).rstrip() + "\n"


def _parse_metadata(yaml_text: str, section_id: str) -> dict[str, Any]:
    raw = yaml.safe_load(yaml_text)
    if not isinstance(raw, dict):
        raise DraftParseError(f"Section '{section_id}' metadata must be a YAML mapping.")

    required = ["status", "checkboxes", "attachments", "evidence", "missing_items"]
    missing = [key for key in required if key not in raw]
    if missing:
        raise DraftParseError(
            f"Section '{section_id}' missing metadata keys: {', '.join(missing)}."
        )

    if raw["status"] not in {DraftStatus.COMPLETE.value, DraftStatus.PARTIAL.value}:
        raise DraftParseError(
            f"Section '{section_id}' has invalid status '{raw['status']}'. "
            "Expected 'complete' or 'partial'."
        )

    checkboxes = _parse_checkboxes(raw["checkboxes"], section_id=section_id)
    attachments = _parse_str_list(raw["attachments"], section_id=section_id, field="attachments")
    evidence = _parse_str_list(raw["evidence"], section_id=section_id, field="evidence")
    missing_items = _parse_missing_items(raw["missing_items"], section_id=section_id)

    return {
        "status": raw["status"],
        "checkboxes": checkboxes,
        "attachments": attachments,
        "evidence": evidence,
        "missing_items": missing_items,
    }


def _parse_checkboxes(raw: Any, section_id: str) -> list[CheckboxToken]:
    if not isinstance(raw, list):
        raise DraftParseError(f"Section '{section_id}' field 'checkboxes' must be a list.")
    parsed: list[CheckboxToken] = []
    for entry in raw:
        if not isinstance(entry, dict) or "name" not in entry:
            raise DraftParseError(
                f"Section '{section_id}' checkbox entries must be mappings with key 'name'."
            )
        parsed.append(
            CheckboxToken(name=str(entry["name"]), checked=bool(entry.get("checked", False)))
        )
    return parsed


def _parse_str_list(raw: Any, section_id: str, field: str) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise DraftParseError(f"Section '{section_id}' field '{field}' must be a list of strings.")
    return list(raw)


def _parse_missing_items(raw: Any, section_id: str) -> list[MissingItem]:
    if not isinstance(raw, list):
        raise DraftParseError(f"Section '{section_id}' field 'missing_items' must be a list.")
    parsed: list[MissingItem] = []
    for entry in raw:
        if not isinstance(entry, dict) or "id" not in entry or "question" not in entry:
            raise DraftParseError(
                f"Section '{section_id}' missing_item entries must contain 'id' and 'question'."
            )
        parsed.append(
            MissingItem(
                id=str(entry["id"]),
                section_id=str(entry.get("section_id") or section_id),
                question=str(entry["question"]),
                user_response=str(entry.get("user_response", "")),
            )
        )
    return parsed
