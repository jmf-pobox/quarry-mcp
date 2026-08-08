"""Tests for the .gitignore captures-exclusion ensure step (pkit-kcps)."""

from __future__ import annotations

from pathlib import Path

from quarry.gitignore import CAPTURES_GITIGNORE_ENTRY, CapturesGitignore


def test_ensure_creates_missing_gitignore(tmp_path: Path) -> None:
    gitignore = CapturesGitignore(tmp_path)

    written = gitignore.ensure()

    assert written is True
    assert (tmp_path / ".gitignore").is_file()
    assert (tmp_path / ".gitignore").read_text() == f"{CAPTURES_GITIGNORE_ENTRY}\n"


def test_ensure_appends_to_existing_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*.log\nnode_modules/\n")

    written = CapturesGitignore(tmp_path).ensure()

    assert written is True
    content = (tmp_path / ".gitignore").read_text()
    assert content == f"*.log\nnode_modules/\n{CAPTURES_GITIGNORE_ENTRY}\n"


def test_ensure_appends_newline_before_entry_when_file_lacks_trailing_newline(
    tmp_path: Path,
) -> None:
    (tmp_path / ".gitignore").write_text("*.log")  # no trailing newline

    CapturesGitignore(tmp_path).ensure()

    content = (tmp_path / ".gitignore").read_text()
    assert content == f"*.log\n{CAPTURES_GITIGNORE_ENTRY}\n"


def test_ensure_is_idempotent_when_entry_already_present(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(f"*.log\n{CAPTURES_GITIGNORE_ENTRY}\n")

    written = CapturesGitignore(tmp_path).ensure()

    assert written is False
    assert (
        tmp_path / ".gitignore"
    ).read_text() == f"*.log\n{CAPTURES_GITIGNORE_ENTRY}\n"


def test_ensure_twice_does_not_duplicate_entry(tmp_path: Path) -> None:
    gitignore = CapturesGitignore(tmp_path)

    first = gitignore.ensure()
    second = gitignore.ensure()

    assert first is True
    assert second is False
    content = (tmp_path / ".gitignore").read_text()
    assert content.count(CAPTURES_GITIGNORE_ENTRY) == 1


def test_ensure_preserves_crlf_line_endings(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_bytes(b"*.log\r\nbuild/\r\n")

    CapturesGitignore(tmp_path).ensure()

    raw = (tmp_path / ".gitignore").read_bytes()
    assert raw == f"*.log\r\nbuild/\r\n{CAPTURES_GITIGNORE_ENTRY}\r\n".encode()


def test_path_property_returns_gitignore_path(tmp_path: Path) -> None:
    assert CapturesGitignore(tmp_path).path == tmp_path / ".gitignore"
