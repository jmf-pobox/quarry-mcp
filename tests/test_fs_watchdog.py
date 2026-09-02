"""Adapter test: the real watchdog observer emits FsEvents against tmp_path.

Everything else drives a synthetic source; this proves the one module that
imports watchdog actually delivers create/modify/delete as :class:`FsEvent`s.
The stat-walk ``PollingObserver`` is used deterministically (a short poll
interval) so the test is not subject to native-watcher timing flakiness.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Self, final

from quarry.daemon.fs_watchdog import WatchdogSource

if TYPE_CHECKING:
    import pytest
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers.api import ObservedWatch

    from quarry.daemon.fs_events import FsEvent

_DEADLINE_S = 5.0
_POLL_S = 0.05
_QUIET_WINDOW_S = 0.5


@final
class _Recorder:
    """Collect events the observer thread delivers (thread-safe list append)."""

    __slots__ = ("events",)

    events: list[FsEvent]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.events = []
        return self

    def __call__(self, event: FsEvent) -> None:
        self.events.append(event)

    def wait_for(self, predicate: object, deadline: float = _DEADLINE_S) -> bool:
        """Poll until *predicate* matches a recorded event, or the deadline."""
        assert callable(predicate)
        end = time.monotonic() + deadline
        while time.monotonic() < end:
            if any(predicate(event) for event in self.events):
                return True
            time.sleep(_POLL_S)
        return False


def test_watchdog_source_reports_create_modify_and_delete(tmp_path: Path) -> None:
    """A created-then-modified-then-deleted file surfaces as FsEvents."""
    recorder = _Recorder()
    source = WatchdogSource(use_polling=True, poll_interval_s=0.1)
    handle = source.schedule(tmp_path, recorder)
    try:
        target = tmp_path / "note.md"
        target.write_text("first")
        assert recorder.wait_for(lambda e: e.path == target and not e.deleted), (
            "create/modify event never arrived"
        )

        target.unlink()
        assert recorder.wait_for(lambda e: e.path == target and e.deleted), (
            "delete event never arrived"
        )
    finally:
        source.unschedule(handle)
        source.stop()


def test_watchdog_source_stop_is_idempotent_after_unschedule(tmp_path: Path) -> None:
    """Unscheduling then stopping tears the observer down without error."""
    source = WatchdogSource(use_polling=True, poll_interval_s=0.1)
    handle = source.schedule(tmp_path, _Recorder())
    source.unschedule(handle)
    source.stop()


def test_schedule_prunes_ignored_directories(tmp_path: Path) -> None:
    """A live edit inside a scratch/VCS directory never reaches the recorder.

    Pruned scheduling means ``node_modules`` was never watched at all -- not
    filtered post-hoc -- so an edit inside it produces no event, matching
    what a bulk scan would find.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    recorder = _Recorder()
    source = WatchdogSource(use_polling=True, poll_interval_s=0.1)
    handle = source.schedule(tmp_path, recorder)
    try:
        kept = tmp_path / "src" / "keep.md"
        kept.write_text("watched")
        assert recorder.wait_for(lambda e: e.path == kept and not e.deleted), (
            "an edit in a non-ignored directory never arrived"
        )
        ignored = tmp_path / "node_modules" / "pkg" / "skip.md"
        ignored.write_text("never watched")
        assert not recorder.wait_for(
            lambda e: e.path == ignored, deadline=_QUIET_WINDOW_S
        ), "an edit inside node_modules/ reached the recorder — it was watched"
    finally:
        source.unschedule(handle)
        source.stop()


def test_schedule_watches_a_newly_created_subdirectory(tmp_path: Path) -> None:
    """A directory created after scheduling is watched for its own new files."""
    recorder = _Recorder()
    source = WatchdogSource(use_polling=True, poll_interval_s=0.1)
    handle = source.schedule(tmp_path, recorder)
    try:
        sub = tmp_path / "newdir"
        sub.mkdir()
        target = sub / "arrived.md"
        # A short settle window lets the polling emitter notice the new
        # directory before the file write races it.
        time.sleep(0.2)
        target.write_text("hello")
        assert recorder.wait_for(lambda e: e.path == target and not e.deleted), (
            "a file inside a newly created subdirectory was never watched"
        )
    finally:
        source.unschedule(handle)
        source.stop()


def test_schedule_never_watches_a_newly_created_ignored_subdirectory(
    tmp_path: Path,
) -> None:
    """A directory created after scheduling that is ignored stays unwatched."""
    recorder = _Recorder()
    source = WatchdogSource(use_polling=True, poll_interval_s=0.1)
    handle = source.schedule(tmp_path, recorder)
    try:
        sub = tmp_path / "node_modules"
        sub.mkdir()
        time.sleep(0.2)
        target = sub / "never.md"
        target.write_text("never watched")
        assert not recorder.wait_for(
            lambda e: e.path == target, deadline=_QUIET_WINDOW_S
        ), "a file inside a newly created node_modules/ reached the recorder"
    finally:
        source.unschedule(handle)
        source.stop()


def test_schedule_failure_releases_partial_watches_and_spares_other_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mid-tree ENOSPC releases every watch already acquired for THAT tree only.

    Covers the ratchet's required boundary: the partial-failure release must
    not leak the acquired watches, and a wholly separate registration must
    keep working -- a failure on one tree is not permitted to starve another
    (the quarry-ndrj leak this fix retires).
    """
    good = tmp_path / "good"
    good.mkdir()
    bad = tmp_path / "bad"
    (bad / "a").mkdir(parents=True)
    (bad / "b").mkdir()
    (bad / "c").mkdir()

    source = WatchdogSource(use_polling=True, poll_interval_s=0.1)
    real_schedule = source._observer.schedule
    real_unschedule = source._observer.unschedule
    released: list[object] = []

    def flaky_schedule(
        handler: FileSystemEventHandler, path: str, *, recursive: bool = False
    ) -> ObservedWatch:
        if Path(path) == bad / "b":
            msg = "No space left on device"
            raise OSError(28, msg)
        return real_schedule(handler, path, recursive=recursive)

    def spy_unschedule(watch: ObservedWatch) -> None:
        released.append(watch)
        real_unschedule(watch)

    monkeypatch.setattr(source._observer, "schedule", flaky_schedule)
    monkeypatch.setattr(source._observer, "unschedule", spy_unschedule)

    good_recorder = _Recorder()
    good_handle = source.schedule(good, good_recorder)
    assert good_handle is not None

    bad_recorder = _Recorder()
    bad_handle = source.schedule(bad, bad_recorder)
    assert bad_handle is None  # the partial tree is refused, not leaked

    # Only the bad tree's two directories acquired before "b" failed (its own
    # root and "a", visited before "b" in topdown/sorted walk order) were
    # released; the good tree was never touched.
    assert len(released) == 2

    try:
        target = good / "note.md"
        target.write_text("still watched")
        assert good_recorder.wait_for(lambda e: e.path == target and not e.deleted), (
            "the unrelated good tree stopped receiving events after the bad "
            "tree's schedule failure"
        )
    finally:
        source.unschedule(good_handle)
        source.stop()


def test_schedule_refuses_an_excluded_scratch_root(tmp_path: Path) -> None:
    """A root that is itself a repo's own .tmp scratch is refused, not scheduled."""
    (tmp_path / ".git").mkdir()
    root = tmp_path / ".tmp" / "pytest-of-me" / "docs"
    root.mkdir(parents=True)
    source = WatchdogSource(use_polling=True, poll_interval_s=0.1)
    try:
        assert source.schedule(root, _Recorder()) is None
    finally:
        source.stop()


def test_schedule_returns_none_for_an_unresolvable_root(tmp_path: Path) -> None:
    """A registered root that does not exist is refused, never raises."""
    missing = tmp_path / "does-not-exist"
    source = WatchdogSource(use_polling=True, poll_interval_s=0.1)
    try:
        assert source.schedule(missing, _Recorder()) is None
    finally:
        source.stop()  # joins the observer thread under the bounded timeout
