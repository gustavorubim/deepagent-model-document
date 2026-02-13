"""Codebase indexing and search utilities."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path


@dataclass(slots=True)
class RepoIndex:
    """In-memory index of repository files."""

    root: Path
    files: dict[str, str]


def read_file_safe(path: Path, max_size_bytes: int = 1_000_000) -> str | None:
    """Read text file content safely, skip binary and oversized files."""
    if not path.is_file():
        return None
    if path.stat().st_size > max_size_bytes:
        return None
    with path.open("rb") as file_obj:
        chunk = file_obj.read(2048)
        if b"\x00" in chunk:
            return None
    return path.read_text(encoding="utf-8", errors="ignore")


def _matches_any(rel_path: str, patterns: list[str]) -> bool:
    return any(fnmatch(rel_path, pattern) for pattern in patterns)


def _include_path(rel_path: str, allowlist: list[str], denylist: list[str]) -> bool:
    if _matches_any(rel_path, denylist):
        return False
    return _matches_any(rel_path, allowlist)


def index_repo(
    codebase_path: Path,
    allowlist: list[str],
    denylist: list[str],
    max_size_bytes: int = 1_000_000,
) -> RepoIndex:
    """Index allowed text files from repository."""
    files: dict[str, str] = {}
    root = codebase_path.resolve()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if not _include_path(rel, allowlist, denylist):
            continue
        content = read_file_safe(path, max_size_bytes=max_size_bytes)
        if content is None:
            continue
        files[rel] = content
    return RepoIndex(root=root, files=files)


def search_repo(index: RepoIndex, query: str, limit: int = 10) -> list[str]:
    """Return file references containing query."""
    lowered = query.lower()
    matches: list[str] = []
    for rel_path, content in index.files.items():
        if lowered in content.lower():
            matches.append(rel_path)
        if len(matches) >= limit:
            break
    return matches


def read_index_file(index: RepoIndex, rel_path: str) -> str:
    """Read indexed file content by repository-relative path."""
    return index.files.get(rel_path, "")


def list_repo_files(index: RepoIndex, limit: int = 300) -> list[str]:
    """List indexed repository files in sorted order."""
    return sorted(index.files.keys())[:limit]
