"""Tests for the watchdog construction chain (DES-045e).

``PrunedInotifyBuffer``/``PrunedInotifyEmitter``/``PrunedInotifyObserver``
wire :class:`~quarry.daemon.inotify_prune.PrunedInotify` into watchdog's
construction pipeline; the pruning DECISION logic itself is covered in
``tests/test_inotify_prune.py``. Construction tests here use FAKED
``inotify_init``/``inotify_add_watch``/``inotify_rm_watch`` ctypes calls for
the same reason: independence from the host's real inotify headroom. One
slow-tier test drives the real kernel end to end.
"""

from __future__ import annotations

import errno
import itertools
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import watchdog.observers.inotify_c as inotify_c
from watchdog.events import FileSystemEventHandler
from watchdog.observers.api import EventQueue, ObservedWatch

from quarry.daemon.inotify_prune import PrunedInotify
from quarry.daemon.inotify_prune_chain import (
    PrunedInotifyBuffer,
    PrunedInotifyEmitter,
    PrunedInotifyObserver,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="inotify pruning is Linux-only"
)


class _FakeKernel:
    """Fake ``inotify_init``/``inotify_add_watch``/``inotify_rm_watch``.

    See ``tests/test_inotify_prune.py`` for why: independence from the
    host's real, often near-zero, inotify instance headroom.
    """

    def __init__(self) -> None:
        self._fds = itertools.count(2000)
        self._wds = itertools.count(1)

    def init(self) -> int:
        return next(self._fds)

    def add_watch(self, fd: int, path: bytes, mask: int) -> int:
        del fd, path, mask
        return next(self._wds)

    @staticmethod
    def rm_watch(fd: int, wd: int) -> int:
        del fd, wd
        return 0


@pytest.fixture
def fake_kernel() -> Iterator[_FakeKernel]:
    """Patch the module-level ctypes calls ``Inotify`` invokes, for one test."""
    kernel = _FakeKernel()
    with (
        patch.object(inotify_c, "inotify_init", kernel.init),
        patch.object(inotify_c, "inotify_add_watch", kernel.add_watch),
        patch.object(inotify_c, "inotify_rm_watch", kernel.rm_watch),
    ):
        yield kernel


def test_pins_the_watchdog_internals_this_module_subclasses() -> None:
    """A loud, fast check that watchdog's private construction-chain
    internals this module overrides still have the shape it was coded
    against -- fails immediately if a future watchdog release renames or
    removes one, instead of the pruning silently going inert.
    """
    import inspect

    from watchdog.observers.inotify import InotifyEmitter
    from watchdog.observers.inotify_buffer import InotifyBuffer

    assert "__init__" in vars(InotifyBuffer)
    buffer_params = set(inspect.signature(InotifyBuffer.__init__).parameters)
    assert {"self", "path", "recursive", "event_mask"} <= buffer_params

    assert "on_thread_start" in vars(InotifyEmitter)


def test_pruned_inotify_buffer_create_builds_a_pruned_inotify(
    tmp_path: Path, fake_kernel: _FakeKernel
) -> None:
    del fake_kernel
    buf = PrunedInotifyBuffer.create(
        str(tmp_path).encode(), recursive=True, event_mask=None
    )
    try:
        assert isinstance(buf._inotify, PrunedInotify)
    finally:
        buf.close()


def test_pruned_inotify_emitter_builds_a_pruned_inotify_buffer(
    tmp_path: Path, fake_kernel: _FakeKernel
) -> None:
    del fake_kernel
    watch = ObservedWatch(str(tmp_path), recursive=True)
    emitter = PrunedInotifyEmitter(EventQueue(), watch)
    try:
        emitter.on_thread_start()
        assert isinstance(emitter._inotify, PrunedInotifyBuffer)
    finally:
        emitter.on_thread_stop()


def test_pruned_inotify_observer_create_uses_the_pruned_emitter_class() -> None:
    observer = PrunedInotifyObserver.create()
    observer.start()
    try:
        assert observer._emitter_class is PrunedInotifyEmitter
    finally:
        observer.stop()
        observer.join(timeout=5)


@pytest.mark.slow
def test_pruned_observer_end_to_end_prunes_and_handles_deep_create(
    tmp_path: Path,
) -> None:
    """Real kernel, no fakes: prune correctness plus the deep-create crash guard.

    Drives the actual scenario the round-2 review demanded proof of: a
    single ``mkdir -p`` burst that creates a subtree containing BOTH
    watchable and ignored directories, with pre-existing files inside each
    (watchdog's own ``_recursive_simulate`` backfills synthetic create
    events for content that arrived before any watch could see it form).
    Skips gracefully when the host has no free inotify instance headroom
    (a real, common desktop-session condition, not a test bug) rather than
    flaking the suite.
    """
    events: list[tuple[str, str, bool]] = []

    class _Handler(FileSystemEventHandler):
        def on_any_event(self, event: object) -> None:
            events.append(
                (event.event_type, event.src_path, event.is_directory)  # type: ignore[attr-defined]
            )

    (tmp_path / "src").mkdir()
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "existing.js").write_text("x")

    observer = PrunedInotifyObserver.create()
    observer.start()
    try:
        watch = observer.schedule(_Handler(), str(tmp_path), recursive=True)
    except OSError as exc:
        if exc.errno in {errno.ENOSPC, errno.EMFILE}:
            pytest.skip(f"host has no free inotify headroom: {exc}")
        raise

    try:
        # Deep-create burst: one directory-create event for "burst", but it
        # arrives already containing a watchable AND an ignored subtree with
        # pre-existing files -- the crash scenario the sentinel bookkeeping
        # exists for (a KeyError here would kill the observer thread).
        burst = tmp_path / "burst"
        (burst / "a" / "b").mkdir(parents=True)
        (burst / "a" / "b" / "deep.txt").write_text("deep")
        (burst / "node_modules" / "pkg").mkdir(parents=True)
        (burst / "node_modules" / "pkg" / "ignored.txt").write_text("ignored")

        deadline = time.monotonic() + 5.0
        target = burst / "a" / "b" / "deep.txt"
        while time.monotonic() < deadline:
            if any(e[1] == str(target) for e in events):
                break
            time.sleep(0.05)
        assert any(e[1] == str(target) for e in events), (
            "a file inside a deep-created watchable subtree was never reported"
        )
        assert not any("node_modules" in e[1] for e in events), (
            "an event surfaced for content under an ignored directory"
        )
        assert observer.is_alive(), "the observer thread died (a KeyError crash)"
    finally:
        observer.unschedule(watch)
        observer.stop()
        observer.join(timeout=5)
