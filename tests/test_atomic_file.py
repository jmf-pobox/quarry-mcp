"""Tests for the byte-preserving, atomic, symlink-safe file writer."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from quarry.atomic_file import AtomicFile


def test_read_missing_returns_empty(tmp_path: Path) -> None:
    assert AtomicFile(tmp_path / "nope.md").read() == ""


@pytest.mark.parametrize(
    "raw",
    [
        "line one\nline two\n",
        "line one\r\nline two\r\n",
        "line one\rline two\r",
        "no trailing newline",
        "",
    ],
)
def test_round_trip_is_byte_identical(tmp_path: Path, raw: str) -> None:
    """A read-then-write round-trip preserves LF, CRLF, and lone-CR verbatim."""
    path = tmp_path / "CLAUDE.md"
    path.write_bytes(raw.encode())
    file = AtomicFile(path)
    file.replace(file.read())
    assert path.read_bytes() == raw.encode()


def test_replace_is_atomic_leaves_no_temp(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    AtomicFile(path).replace("content\n")
    assert path.read_text() == "content\n"
    # No orphaned temp siblings.
    assert [p.name for p in tmp_path.iterdir()] == ["CLAUDE.md"]


def test_fdopen_raises_closes_fd_and_removes_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``os.fdopen`` raising before ownership closes the fd and orphans no temp."""
    path = tmp_path / "CLAUDE.md"
    path.write_text("original\n")

    closed: list[int] = []
    real_close = os.close

    def record_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    def boom(fd: int, *_args: object, **_kwargs: object) -> object:
        # Raise BEFORE taking ownership; AtomicFile must os.close(fd) itself.
        msg = "fdopen failed"
        raise OSError(msg)

    monkeypatch.setattr(os, "fdopen", boom)
    monkeypatch.setattr(os, "close", record_close)
    with pytest.raises(OSError, match="fdopen failed"):
        AtomicFile(path).replace("new content\n")

    assert closed, "the raw mkstemp fd was never closed"
    assert path.read_text() == "original\n"
    assert [p.name for p in tmp_path.iterdir()] == ["CLAUDE.md"]


def test_write_failure_removes_temp_and_keeps_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after ``fdopen`` (here ``fsync``) never truncates the original."""
    path = tmp_path / "CLAUDE.md"
    path.write_text("original\n")

    def boom(_fd: int) -> None:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError, match="disk full"):
        AtomicFile(path).replace("new content\n")

    assert path.read_text() == "original\n"
    assert [p.name for p in tmp_path.iterdir()] == ["CLAUDE.md"]


def test_new_file_gets_0644(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    AtomicFile(path).replace("x\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_existing_mode_preserved(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_text("x\n")
    path.chmod(0o600)
    AtomicFile(path).replace("y\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_forced_mode_wins(tmp_path: Path) -> None:
    path = tmp_path / "secret"
    AtomicFile(path).replace("token\n", mode=0o600)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_symlink_target_is_rewritten_link_preserved(tmp_path: Path) -> None:
    """Writing through a symlink updates the real file and keeps the link."""
    real = tmp_path / "real.md"
    real.write_text("old\n")
    link = tmp_path / "CLAUDE.md"
    link.symlink_to(real)

    AtomicFile(link).replace("new\n")

    assert link.is_symlink()
    assert real.read_text() == "new\n"


def test_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deep" / "CLAUDE.md"
    AtomicFile(path).replace("x\n")
    assert path.read_text() == "x\n"
