"""Tests for the exclusive sibling-file lock."""

from __future__ import annotations

import fcntl
import multiprocessing
import os
import time
from pathlib import Path

import pytest

from quarry.file_lock import FileLock


def test_lock_file_created_beside_target(tmp_path: Path) -> None:
    target = tmp_path / "CLAUDE.md"
    with FileLock(target):
        assert (tmp_path / ".CLAUDE.md.lock").is_file()


def test_reentrant_sequential_acquire(tmp_path: Path) -> None:
    """The same lock can be acquired again once released (fd reset)."""
    target = tmp_path / "CLAUDE.md"
    with FileLock(target):
        pass
    with FileLock(target):
        pass


def test_enter_closes_fd_when_flock_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raising flock closes the fd __enter__ opened, so it does not leak."""
    opened: list[int] = []
    closed: list[int] = []
    real_open = os.open
    real_close = os.close

    def spy_open(path: str, flags: int, mode: int = 0o777) -> int:
        fd = real_open(path, flags, mode)
        opened.append(fd)
        return fd

    def spy_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    def boom(fd: int, operation: int) -> None:
        raise OSError("flock interrupted")

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "close", spy_close)
    monkeypatch.setattr(fcntl, "flock", boom)

    lock = FileLock(tmp_path / "CLAUDE.md")
    with pytest.raises(OSError, match="flock interrupted"):
        lock.__enter__()

    assert opened, "expected __enter__ to open the lock fd"
    assert closed == opened, "the opened fd must be closed, not leaked"


def _increment_under_lock(target_str: str, counter_str: str) -> None:
    target = Path(target_str)
    counter = Path(counter_str)
    for _ in range(50):
        with FileLock(target):
            n = int(counter.read_text())
            time.sleep(0.0005)  # widen the read-modify-write window
            counter.write_text(str(n + 1))


def test_lock_prevents_lost_updates(tmp_path: Path) -> None:
    """N processes each do 50 locked increments; none is lost."""
    target = tmp_path / "CLAUDE.md"
    counter = tmp_path / "counter"
    counter.write_text("0")
    ctx = multiprocessing.get_context("spawn")
    procs = [
        ctx.Process(target=_increment_under_lock, args=(str(target), str(counter)))
        for _ in range(4)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
    for p in procs:
        if p.is_alive():
            p.terminate()
        assert p.exitcode == 0, "a child did not finish cleanly"
    assert counter.read_text() == "200"
