"""The :class:`FsEventSource` adapter over the ``watchdog`` library.

Everything else in the watch loop talks to the :class:`FsEventSource` Protocol
(:mod:`~quarry.daemon.fs_events`), so watchdog stays confined to this module
and its collaborator :mod:`~quarry.daemon.watch_tree`.  ``WatchdogSource`` owns
one observer thread for the whole process; :class:`~quarry.daemon.watch_tree.
WatchedTree` owns the per-directory watches and event routing for one
registered root.

Scheduling is PRUNED, not raw-recursive (DES-045d).  inotify allocates one
native watch per directory, so ``observer.schedule(root, recursive=True)``
allocates a watch for every ignored subtree too (``.git``, ``node_modules``,
build output…) — a real workspace has far more ignored directories than
watchable ones, and the raw-recursive form blows the fixed inotify watch
budget the operator will not raise.  ``WatchedTree`` instead schedules one
non-recursive watch per directory :meth:`~quarry.sync_discovery.FileDiscovery.
iter_watchable_dirs` yields — the SAME ignore/pruning seam
:mod:`~quarry.sync_discovery` uses for a bulk scan, so a live watch and a scan
never disagree about what is ignored.  A directory that appears later under a
watched tree (``WatchedTree.watch_new_subtree``) is walked and scheduled
through the identical seam, so it is watched iff a bulk scan would have found
it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, cast, final

from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from quarry.daemon.watch_tree import WatchedTree
from quarry.sync_discovery import FileDiscovery

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from watchdog.observers.api import BaseObserver

    from quarry.daemon.fs_events import FsEvent

logger = logging.getLogger(__name__)

# Bound the observer-thread join at shutdown so a wedged native watcher can never
# hang the daemon's teardown.
_JOIN_TIMEOUT_S = 5.0


@final
class WatchdogSource:
    """One watchdog observer thread behind the :class:`FsEventSource` Protocol.

    ``use_polling`` selects the stat-walk ``PollingObserver`` — the zero-inotify,
    zero-FSEvents fallback an operator sets for large trees (or where the native
    watcher is unavailable).
    """

    __slots__ = ("_observer",)

    _observer: BaseObserver

    def __new__(
        cls, *, use_polling: bool = False, poll_interval_s: float = 2.0
    ) -> Self:
        self = super().__new__(cls)
        observer: BaseObserver = (
            PollingObserver(timeout=poll_interval_s) if use_polling else Observer()
        )
        observer.start()
        self._observer = observer
        return self

    def schedule(
        self, root: Path, on_event: Callable[[FsEvent], None]
    ) -> object | None:
        """Begin watching *root*, pruned per the shared ignore spec, or refuse.

        Returns an opaque :class:`~quarry.daemon.watch_tree.WatchedTree`
        handle, or ``None`` when *root* itself is unwatchable (unresolvable,
        or an excluded temp/scratch root — :meth:`~quarry.sync_discovery.
        FileDiscovery.root_available`) or the OS refuses a watch partway
        through the tree (e.g. ``ENOSPC`` on inotify exhaustion).  A
        partial-tree failure releases every watch already acquired for
        *root* before returning ``None`` — the caller treats a ``None``
        handle as "this tree is unwatched, rely on scans" and must never be
        left holding leaked watches for a tree it believes is unwatched.
        """
        discovery = FileDiscovery(root)
        if not discovery.root_available:
            return None
        tree = WatchedTree(self._observer, discovery, on_event)
        try:
            tree.schedule_tree()
        except OSError as exc:
            logger.warning(
                "watch: cannot watch %s (%s); releasing %d partial watch(es); "
                "relying on scans",
                root,
                exc,
                len(tree),
            )
            tree.release()
            return None
        return tree

    def unschedule(self, handle: object | None) -> None:
        """Stop watching the tree associated with *handle* (a no-op if ``None``)."""
        if handle is not None:
            cast("WatchedTree", handle).release()

    def stop(self) -> None:
        """Stop the observer and join its thread under a bounded timeout."""
        self._observer.stop()
        self._observer.join(timeout=_JOIN_TIMEOUT_S)
