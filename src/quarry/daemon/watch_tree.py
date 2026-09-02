"""One watched directory tree: its per-directory watches and event routing.

Extracted from :mod:`~quarry.daemon.fs_watchdog` (which keeps the thin
:class:`~quarry.daemon.fs_watchdog.WatchdogSource` Protocol adapter) so the
tree-scoped bookkeeping — acquiring/releasing per-directory watches, and
routing a directory event into "watch a new subtree" or "forget a departed
one" — lives in its own module.  :class:`WatchedTree` and
:class:`WatchdogHandler` are still watchdog types (the split is about
responsibility, not about isolating the ``watchdog`` import to one module);
:mod:`~quarry.daemon.fs_watchdog` remains the only module a caller outside the
daemon's watch subsystem needs to import.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Self, final

from watchdog.events import FileMovedEvent, FileSystemEvent, FileSystemEventHandler

from quarry.daemon.fs_events import FsEvent
from quarry.ingestion.pipeline import SUPPORTED_EXTENSIONS

if TYPE_CHECKING:
    from collections.abc import Callable

    from watchdog.observers.api import BaseObserver, ObservedWatch

    from quarry.sync_discovery import FileDiscovery

logger = logging.getLogger(__name__)


@final
class WatchedTree:
    """One registered root's per-directory watches, pruned per the shared ignore spec.

    Owns enough state — the :class:`~quarry.sync_discovery.FileDiscovery`
    built for the root, and the ``{directory: ObservedWatch}`` map — to add a
    watch for a directory that appears later under the tree using the SAME
    loaded ignore spec the initial walk used, so a live create event and the
    initial scan agree on what is ignored.
    """

    __slots__ = ("_discovery", "_handler", "_observer", "_watches")

    _observer: BaseObserver
    _discovery: FileDiscovery
    _handler: FileSystemEventHandler
    _watches: dict[Path, ObservedWatch]

    def __new__(
        cls,
        observer: BaseObserver,
        discovery: FileDiscovery,
        on_event: Callable[[FsEvent], None],
    ) -> Self:
        self = super().__new__(cls)
        self._observer = observer
        self._discovery = discovery
        self._handler = WatchdogHandler(on_event, self)
        self._watches = {}
        return self

    def __len__(self) -> int:
        return len(self._watches)

    def schedule_tree(self) -> None:
        """Schedule every directory the pruned walk yields; raise on the first failure.

        Raises whatever the underlying ``observer.schedule`` raises (``OSError``
        on inotify ``ENOSPC``) with whatever watches were already acquired left
        in :attr:`_watches` — the caller releases them via :meth:`release`,
        keeping "acquire" and "release-on-failure" as two separately callable
        steps rather than folding cleanup into this method's own exception path.
        """
        for directory in self._discovery.iter_watchable_dirs():
            self._watches[directory] = self._schedule_one(directory)

    def watch_new_subtree(self, path: Path) -> None:
        """Watch *path* and any non-ignored descendants (a live directory create).

        Best-effort per directory: unlike :meth:`schedule_tree`, this runs on
        the observer thread mid-stream, with the rest of the tree already
        live, so a schedule failure for one new directory logs and skips only
        that directory (bug-class 2) rather than tearing the whole tree down.
        A directory that is itself ignored (or already tracked) is skipped
        without touching the observer at all.
        """
        if path in self._watches or not self._discovery.is_watchable_dir(path):
            return
        for directory in self._discovery.iter_watchable_dirs(start=path):
            if directory in self._watches:
                continue
            try:
                self._watches[directory] = self._schedule_one(directory)
            except OSError as exc:
                logger.warning(
                    "watch: cannot watch new directory %s (%s); skipping",
                    directory,
                    exc,
                )

    def forget_subtree(self, path: Path) -> None:
        """Drop bookkeeping for *path* and any watch nested under it (best effort).

        The kernel already invalidates an inotify watch for a directory that
        no longer exists; this only prevents :attr:`_watches` from
        accumulating stale entries (and their ``ObservedWatch`` objects) over
        a long daemon uptime as directories are created and removed.
        ``unschedule`` racing an already-invalidated watch is a normal
        outcome here (the OS beat us to it), not a bug — narrowly suppressed
        at this one external-boundary call, not swallowed elsewhere.
        """
        stale = [d for d in self._watches if d == path or path in d.parents]
        for directory in stale:
            watch = self._watches.pop(directory)
            with contextlib.suppress(OSError, KeyError):
                self._observer.unschedule(watch)

    def release(self) -> None:
        """Unschedule every directory watch acquired for this tree."""
        for watch in self._watches.values():
            self._observer.unschedule(watch)
        self._watches.clear()

    def _schedule_one(self, directory: Path) -> ObservedWatch:
        return self._observer.schedule(self._handler, str(directory), recursive=False)


@final
class WatchdogHandler(FileSystemEventHandler):
    """Translate watchdog events into :class:`FsEvent` and forward them.

    A rename arrives as a ``FileMovedEvent``; a file half is delivered as a
    deletion of the source path and a modify of the destination path so the
    debouncer routes each half correctly.  A directory half instead updates
    the tree's own watch bookkeeping (:class:`WatchedTree`) — directory
    events never reach the caller's ``on_event``, which indexes files.
    """

    __slots__ = ("_on_event", "_tree")

    _on_event: Callable[[FsEvent], None]
    _tree: WatchedTree

    def __new__(cls, on_event: Callable[[FsEvent], None], tree: WatchedTree) -> Self:
        self = super().__new__(cls)
        self._on_event = on_event
        self._tree = tree
        return self

    def on_any_event(self, event: FileSystemEvent) -> None:
        """Forward one file event, or watch/unwatch a directory; never propagate."""
        try:
            if event.is_directory:
                self._handle_directory_event(event)
                return
            if isinstance(event, FileMovedEvent):
                self._emit(event.src_path, deleted=True)
                self._emit(event.dest_path, deleted=False)
            elif event.event_type == "deleted":
                self._emit(event.src_path, deleted=True)
            elif event.event_type in {"created", "modified"}:
                self._emit(event.src_path, deleted=False)
        except Exception:
            logger.exception("watch: event handler failed for %r", event)

    def _handle_directory_event(self, event: FileSystemEvent) -> None:
        """Add a watch for a directory that appeared; drop one that left."""
        if isinstance(event, FileMovedEvent):
            self._tree.forget_subtree(self._as_path(event.src_path))
            self._tree.watch_new_subtree(self._as_path(event.dest_path))
        elif event.event_type == "created":
            self._tree.watch_new_subtree(self._as_path(event.src_path))
        elif event.event_type == "deleted":
            self._tree.forget_subtree(self._as_path(event.src_path))

    def _emit(self, raw_path: str | bytes, *, deleted: bool) -> None:
        """Forward a supported-suffix path as an :class:`FsEvent` (cheap pre-filter).

        Filtering by suffix here, on the observer thread, keeps unsupported-file
        churn out of the debouncer; the authoritative resolve/ignore filter runs
        post-debounce in the submitter.
        """
        path = self._as_path(raw_path)
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            self._on_event(FsEvent(path, deleted=deleted))

    @staticmethod
    def _as_path(raw_path: str | bytes) -> Path:
        """Decode watchdog's ``str | bytes`` event path into a :class:`Path`."""
        return Path(raw_path.decode() if isinstance(raw_path, bytes) else raw_path)
