from __future__ import annotations

from pathlib import Path

from mrm_deepagent.repo_indexer import index_repo, list_repo_files, read_file_safe, search_repo


def test_index_repo_applies_allow_and_deny_patterns(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("print('alpha')\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("beta metrics\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("ignored\n", encoding="utf-8")
    (tmp_path / "artifact.bin").write_bytes(b"\x00\x01\x02")

    repo = index_repo(
        codebase_path=tmp_path,
        allowlist=["*.py", "*.md", "*.bin"],
        denylist=[".git/**", "*.bin"],
    )

    assert sorted(repo.files.keys()) == ["keep.py", "notes.md"]
    assert list_repo_files(repo) == ["keep.py", "notes.md"]
    assert search_repo(repo, "metrics") == ["notes.md"]


def test_read_file_safe_rejects_oversized_and_binary(tmp_path: Path) -> None:
    text_path = tmp_path / "small.txt"
    text_path.write_text("hello", encoding="utf-8")
    assert read_file_safe(text_path, max_size_bytes=10) == "hello"

    large_path = tmp_path / "large.txt"
    large_path.write_text("x" * 100, encoding="utf-8")
    assert read_file_safe(large_path, max_size_bytes=10) is None

    binary_path = tmp_path / "binary.txt"
    binary_path.write_bytes(b"\x00\x10\x11")
    assert read_file_safe(binary_path) is None
