"""Tests for the .gitignore ensure step (pkit-kcps)."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from quarry.file_lock import FILE_LOCK_GITIGNORE_GLOB
from quarry.gitignore import CAPTURES_GITIGNORE_ENTRY, QuarryGitignore


def test_ensure_creates_missing_gitignore(tmp_path: Path) -> None:
    gitignore = QuarryGitignore(tmp_path)

    written = gitignore.ensure()

    assert written is True
    assert (tmp_path / ".gitignore").is_file()
    content = (tmp_path / ".gitignore").read_text()
    assert content == f"{CAPTURES_GITIGNORE_ENTRY}\n{FILE_LOCK_GITIGNORE_GLOB}\n"


def test_ensure_appends_to_existing_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*.log\nnode_modules/\n")

    written = QuarryGitignore(tmp_path).ensure()

    assert written is True
    content = (tmp_path / ".gitignore").read_text()
    assert content == (
        f"*.log\nnode_modules/\n{CAPTURES_GITIGNORE_ENTRY}\n{FILE_LOCK_GITIGNORE_GLOB}\n"
    )


def test_ensure_appends_newline_before_entries_when_file_lacks_trailing_newline(
    tmp_path: Path,
) -> None:
    (tmp_path / ".gitignore").write_text("*.log")  # no trailing newline

    QuarryGitignore(tmp_path).ensure()

    content = (tmp_path / ".gitignore").read_text()
    assert content == f"*.log\n{CAPTURES_GITIGNORE_ENTRY}\n{FILE_LOCK_GITIGNORE_GLOB}\n"


def test_ensure_is_idempotent_when_every_entry_already_present(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(
        f"*.log\n{CAPTURES_GITIGNORE_ENTRY}\n{FILE_LOCK_GITIGNORE_GLOB}\n"
    )

    written = QuarryGitignore(tmp_path).ensure()

    assert written is False
    assert (tmp_path / ".gitignore").read_text() == (
        f"*.log\n{CAPTURES_GITIGNORE_ENTRY}\n{FILE_LOCK_GITIGNORE_GLOB}\n"
    )


def test_ensure_backfills_only_the_missing_entry(tmp_path: Path) -> None:
    """A repo excluding captures but not the lock glob gets just the glob added."""
    (tmp_path / ".gitignore").write_text(f"{CAPTURES_GITIGNORE_ENTRY}\n")

    written = QuarryGitignore(tmp_path).ensure()

    assert written is True
    content = (tmp_path / ".gitignore").read_text()
    assert content == f"{CAPTURES_GITIGNORE_ENTRY}\n{FILE_LOCK_GITIGNORE_GLOB}\n"
    assert content.count(CAPTURES_GITIGNORE_ENTRY) == 1


def test_ensure_twice_does_not_duplicate_any_entry(tmp_path: Path) -> None:
    gitignore = QuarryGitignore(tmp_path)

    first = gitignore.ensure()
    second = gitignore.ensure()

    assert first is True
    assert second is False
    content = (tmp_path / ".gitignore").read_text()
    assert content.count(CAPTURES_GITIGNORE_ENTRY) == 1
    assert content.count(FILE_LOCK_GITIGNORE_GLOB) == 1


def test_ensure_preserves_crlf_line_endings(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_bytes(b"*.log\r\nbuild/\r\n")

    QuarryGitignore(tmp_path).ensure()

    raw = (tmp_path / ".gitignore").read_bytes()
    assert (
        raw
        == (
            f"*.log\r\nbuild/\r\n{CAPTURES_GITIGNORE_ENTRY}\r\n"
            f"{FILE_LOCK_GITIGNORE_GLOB}\r\n"
        ).encode()
    )


def test_ensure_excludes_file_lock_artifacts(tmp_path: Path) -> None:
    """The FileLock lock-file glob is ensured -- the Bugbot-flagged bug.

    ``QuarryGitignore.ensure()`` itself takes a ``FileLock`` on ``.gitignore``,
    creating ``..gitignore.lock`` beside it; that artifact is created and
    never removed (see ``FileLock``'s docstring), so without this entry every
    ``quarry enable`` leaves a machine-local file a bare ``git add -A`` could
    commit -- the same failure mode as ``.CLAUDE.md.lock``.
    """
    QuarryGitignore(tmp_path).ensure()

    content = (tmp_path / ".gitignore").read_text()
    assert FILE_LOCK_GITIGNORE_GLOB in content.splitlines()
    assert fnmatch.fnmatch(".CLAUDE.md.lock", FILE_LOCK_GITIGNORE_GLOB)
    assert fnmatch.fnmatch("..gitignore.lock", FILE_LOCK_GITIGNORE_GLOB)


def test_path_property_returns_gitignore_path(tmp_path: Path) -> None:
    assert QuarryGitignore(tmp_path).path == tmp_path / ".gitignore"
