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


def test_symlinked_lock_path_is_refused_and_creates_nothing_outside(
    tmp_path: Path,
) -> None:
    """A planted symlink at the lock path must not let the acquire escape the repo.

    O_NOFOLLOW refuses the symlinked ``.CLAUDE.md.lock``; without it the acquire
    would O_CREAT-create (dangling target) or flock (existing target) a file
    outside the repo.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "external_lock_target"  # does not exist yet
    (repo / ".CLAUDE.md.lock").symlink_to(external)

    # O_NOFOLLOW on a symlink raises ELOOP ("... symbolic links") on Linux/macOS.
    with pytest.raises(OSError, match="symbolic"):
        FileLock(repo / "CLAUDE.md").__enter__()

    assert not external.exists()


def test_symlinked_lock_to_existing_file_is_not_opened(tmp_path: Path) -> None:
    """A symlink to an existing external file is refused, leaving it untouched."""
    repo = tmp_path / "repo"
    repo.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("keep\n")
    (repo / ".CLAUDE.md.lock").symlink_to(victim)

    with pytest.raises(OSError, match="symbolic"):
        FileLock(repo / "CLAUDE.md").__enter__()

    assert victim.read_text() == "keep\n"


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


def test_reentrant_nested_acquire_same_process(tmp_path: Path) -> None:
    """A nested acquire of the same lock in one process shares the flock, not deadlocks.

    Enablement holds the lock while ClaudeMdImport.register re-acquires it; two
    independent fds on one file would deadlock (flock treats them as separate
    holders even in one process), so the lock counts the depth and locks once.
    """
    target = tmp_path / "CLAUDE.md"
    with FileLock(target), FileLock(target):
        assert (tmp_path / ".CLAUDE.md.lock").is_file()
    # Fully released: the path can be acquired cleanly again.
    with FileLock(target):
        pass


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
