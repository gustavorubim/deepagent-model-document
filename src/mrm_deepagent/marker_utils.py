"""Section marker parsing utilities for tolerant template handling."""

from __future__ import annotations

import re

from mrm_deepagent.models import SectionType

_SECTION_TYPE_RE = re.compile(r"\[(FILL|SKIP|VALIDATOR)\]", re.IGNORECASE)
_SECTION_ID_RE = re.compile(r"\[ID:([A-Za-z0-9_-]+)\]", re.IGNORECASE)
_BRACKET_TOKEN_RE = re.compile(r"\[[^\]]+\]")
_SPACE_RE = re.compile(r"\s+")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def parse_heading_marker(
    heading_text: str,
    *,
    fallback_fill: bool,
    used_ids: set[str],
) -> tuple[SectionType, str, str] | None:
    """Parse marker-like metadata from heading text.

    Returns tuple: (section_type, section_id, cleaned_title)
    """
    raw = heading_text.strip()
    if not raw:
        return None

    section_type = _extract_section_type(raw, fallback_fill=fallback_fill)
    if section_type is None:
        return None

    clean_title = _clean_title(raw)
    explicit_id = _extract_id(raw)
    if explicit_id:
        section_id = explicit_id
    else:
        section_id = _dedupe_id(_slugify(clean_title), used_ids)
    used_ids.add(section_id)

    return (section_type, section_id, clean_title)


def _extract_section_type(text: str, *, fallback_fill: bool) -> SectionType | None:
    match = _SECTION_TYPE_RE.search(text)
    if match:
        return SectionType(match.group(1).lower())
    if fallback_fill:
        return SectionType.FILL
    return None


def _extract_id(text: str) -> str | None:
    match = _SECTION_ID_RE.search(text)
    if not match:
        return None
    return match.group(1).strip().lower()


def _clean_title(text: str) -> str:
    cleaned = _BRACKET_TOKEN_RE.sub("", text)
    cleaned = _SPACE_RE.sub(" ", cleaned).strip(" -:\t")
    return cleaned or "Untitled Section"


def _slugify(text: str) -> str:
    normalized = text.lower().strip()
    slug = _SLUG_RE.sub("_", normalized).strip("_")
    slug = slug.lstrip("0123456789_")
    return slug or "section"


def _dedupe_id(section_id: str, used_ids: set[str]) -> str:
    if section_id not in used_ids:
        return section_id
    suffix = 2
    while f"{section_id}_{suffix}" in used_ids:
        suffix += 1
    return f"{section_id}_{suffix}"
