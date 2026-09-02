"""Tests for :class:`~quarry.daemon.inotify_prune.PrunedInotify` (DES-045e).

Drives ``PrunedInotify`` directly against FAKED ``inotify_init``/
``inotify_add_watch``/``inotify_rm_watch`` ctypes calls (module-level
functions in ``watchdog.observers.inotify_c``) so the pruning DECISION
logic — which directories get a real (fake) watch, which get silently
skipped, and how a per-directory failure is handled — is covered
deterministically, independent of the host's actual inotify instance/watch
headroom (a real desktop session routinely has near-zero
``fs.inotify.max_user_instances`` headroom shared with IDEs and other
processes, which is the exact scarcity this fix exists for). The watchdog
construction-chain wiring (``PrunedInotifyBuffer``/``PrunedInotifyEmitter``/
``PrunedInotifyObserver``, including the real-kernel end-to-end slow test)
lives in ``tests/test_inotify_prune_chain.py``.
"""

from __future__ import annotations

import ctypes
import errno
import itertools
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import watchdog.observers.inotify_c as inotify_c

from quarry.daemon.inotify_prune import PrunedDirectoryError, PrunedInotify

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="inotify pruning is Linux-only"
)

_PRUNED_WD = -2


class _FakeKernel:
    """Fake ``inotify_init``/``inotify_add_watch``/``inotify_rm_watch``.

    Returns monotonically increasing fake fds/watch descriptors instead of
    making a real ``inotify_init()`` syscall, so a test never depends on (or
    consumes) the host's real, often near-zero, inotify instance headroom.
    ``fail_paths`` maps one encoded path to the errno ``inotify_add_watch``
    should fail with for that path only.
    """

    def __init__(self, *, fail_paths: dict[bytes, int] | None = None) -> None:
        self._fds = itertools.count(1000)
        self._wds = itertools.count(1)
        self._fail_paths = fail_paths or {}

    def init(self) -> int:
        return next(self._fds)

    def add_watch(self, fd: int, path: bytes, mask: int) -> int:
        del fd, mask
        if path in self._fail_paths:
            ctypes.set_errno(self._fail_paths[path])
            return -1
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


def _watched_paths(inst: PrunedInotify) -> set[str]:
    return {p.decode() for p, wd in inst._wd_for_path.items() if wd != _PRUNED_WD}


def _pruned_sentinel_paths(inst: PrunedInotify) -> set[str]:
    return {p.decode() for p, wd in inst._wd_for_path.items() if wd == _PRUNED_WD}


def test_pins_the_watchdog_internals_this_module_subclasses() -> None:
    """A loud, fast check that watchdog's private inotify internals this
    module overrides still have the shape it was coded against.

    If a future watchdog release renames or removes one of these, this
    fails immediately and explicitly instead of the pruning silently going
    inert (the whole point of "pin the assumption with a test").
    """
    import inspect

    from watchdog.observers.inotify_c import Inotify

    assert "_add_dir_watch" in vars(Inotify)
    add_dir_params = set(inspect.signature(Inotify._add_dir_watch).parameters)
    assert {"self", "path", "mask", "recursive"} <= add_dir_params

    assert "_add_watch" in vars(Inotify)
    add_watch_params = set(inspect.signature(Inotify._add_watch).parameters)
    assert {"self", "path", "mask"} <= add_watch_params


def test_add_dir_watch_prunes_ignored_directories(
    tmp_path: Path, fake_kernel: _FakeKernel
) -> None:
    """The initial recursive walk never adds (or even attempts) a watch for
    an ignored directory -- confirmed by BOTH the watched set and the
    absence of even a pruned-sentinel entry, since the pre-filtered walk
    never calls ``_add_watch`` for it at all.
    """
    del fake_kernel
    (tmp_path / "src").mkdir()
    (tmp_path / "node_modules" / "pkg" / "deep").mkdir(parents=True)
    (tmp_path / ".git").mkdir()

    inst = PrunedInotify(str(tmp_path).encode(), recursive=True, event_mask=None)
    try:
        assert _watched_paths(inst) == {str(tmp_path), str(tmp_path / "src")}
        assert _pruned_sentinel_paths(inst) == set()
    finally:
        inst.close()


def test_add_dir_watch_empty_directory_watches_only_the_root(
    tmp_path: Path, fake_kernel: _FakeKernel
) -> None:
    """Boundary: a root with no subdirectories yields exactly one watch."""
    del fake_kernel
    inst = PrunedInotify(str(tmp_path).encode(), recursive=True, event_mask=None)
    try:
        assert _watched_paths(inst) == {str(tmp_path)}
    finally:
        inst.close()


def test_add_dir_watch_bounded_regardless_of_ignored_subtree_size(
    tmp_path: Path, fake_kernel: _FakeKernel
) -> None:
    """A large ignored subtree contributes zero watches -- the actual bug."""
    del fake_kernel
    for i in range(150):
        (tmp_path / "node_modules" / f"pkg{i}").mkdir(parents=True)
    (tmp_path / "src").mkdir()

    inst = PrunedInotify(str(tmp_path).encode(), recursive=True, event_mask=None)
    try:
        assert _watched_paths(inst) == {str(tmp_path), str(tmp_path / "src")}
    finally:
        inst.close()


def test_add_dir_watch_skips_ordinary_oserror_and_continues(tmp_path: Path) -> None:
    """A single directory's ordinary add-watch failure (raced ENOENT) is
    skipped -- siblings still get watched, the tree is not aborted.
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "c").mkdir()
    fail_b = {str(tmp_path / "b").encode(): errno.ENOENT}
    kernel = _FakeKernel(fail_paths=fail_b)
    with (
        patch.object(inotify_c, "inotify_init", kernel.init),
        patch.object(inotify_c, "inotify_add_watch", kernel.add_watch),
        patch.object(inotify_c, "inotify_rm_watch", kernel.rm_watch),
    ):
        inst = PrunedInotify(str(tmp_path).encode(), recursive=True, event_mask=None)
        try:
            watched = _watched_paths(inst)
            assert str(tmp_path / "a") in watched
            assert str(tmp_path / "c") in watched
            assert str(tmp_path / "b") not in watched
        finally:
            inst.close()


@pytest.mark.parametrize("bad_errno", [errno.ENOSPC, errno.EMFILE])
def test_add_dir_watch_aborts_on_budget_exhaustion(
    tmp_path: Path, bad_errno: int
) -> None:
    """ENOSPC/EMFILE abort the whole initial walk -- these mean the budget
    is genuinely exhausted, not a transient per-directory race.
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    fail_b = {str(tmp_path / "b").encode(): bad_errno}
    kernel = _FakeKernel(fail_paths=fail_b)
    with (
        patch.object(inotify_c, "inotify_init", kernel.init),
        patch.object(inotify_c, "inotify_add_watch", kernel.add_watch),
        patch.object(inotify_c, "inotify_rm_watch", kernel.rm_watch),
        pytest.raises(OSError, match=r"limit reached"),
    ):
        PrunedInotify(str(tmp_path).encode(), recursive=True, event_mask=None)


def test_add_watch_rejects_an_ignored_path_and_registers_the_sentinel(
    tmp_path: Path, fake_kernel: _FakeKernel
) -> None:
    """A direct ``_add_watch`` call for an ignored path raises
    ``PrunedDirectoryError`` (a plain ``OSError`` subclass every existing
    watchdog call site already tolerates) and leaves a sentinel entry so a
    later parent-wd lookup (``_recursive_simulate``'s file loop) resolves
    instead of raising ``KeyError``.
    """
    del fake_kernel
    (tmp_path / "node_modules").mkdir()
    inst = PrunedInotify(str(tmp_path).encode(), recursive=False, event_mask=None)
    try:
        ignored = str(tmp_path / "node_modules").encode()
        with pytest.raises(PrunedDirectoryError):
            inst._add_watch(ignored, 0)
        assert inst._wd_for_path[ignored] == _PRUNED_WD
    finally:
        inst.close()


def test_add_watch_never_prunes_the_root_itself(
    tmp_path: Path, fake_kernel: _FakeKernel
) -> None:
    """The registered root is always watched, even though ``is_watchable_dir``
    would reject it if it were (incorrectly) checked against itself.
    """
    del fake_kernel
    inst = PrunedInotify(str(tmp_path).encode(), recursive=False, event_mask=None)
    try:
        assert str(tmp_path) in _watched_paths(inst)
    finally:
        inst.close()
