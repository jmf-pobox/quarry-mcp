"""The :class:`FsEventSource` adapter over the ``watchdog`` library.

Everything else in the watch loop talks to the :class:`FsEventSource` Protocol
(:mod:`~quarry.daemon.fs_events`), so watchdog stays confined to this module
and its Linux collaborator :mod:`~quarry.daemon.inotify_prune_chain`.

One recursive watch per registered root (DES-045e — supersedes DES-045d's
per-directory scheduling, which was structurally wrong on Linux: every
``ObservedWatch`` gets its own emitter, and each Linux emitter's ``Inotify``
wrapper calls the libc ``inotify_init()`` — one kernel INSTANCE plus threads
and fds per directory. ``fs.inotify.max_user_instances`` defaults to 128
(per-user, shared with IDEs/editors), so per-directory scheduling exhausted
it at ~120 directories).

``WatchdogSource`` instead picks the observer by whether the pruned Linux
observer is importable (a module-scope ``try``/``except`` at the top of this
file, not a ``platform.system()`` branch — the import itself is the reliable
signal, since it fails exactly when the host's libc lacks inotify):

* **Linux** — :class:`~quarry.daemon.inotify_prune_chain.PrunedInotifyObserver`:
  one inotify instance per root (comfortably inside
  ``max_user_instances``), whose internal directory walk skips ignored
  directories per the shared :mod:`~quarry.sync_discovery` ignore spec — so
  the much larger ``max_user_watches`` budget (65,536, per-descriptor, no
  per-user cap) is spent only on directories worth watching.
* **macOS and other platforms** — watchdog's standard recursive observer
  (FSEvents on macOS: one stream per root, no per-directory kernel cost at
  all, so nothing to prune at the schedule layer).
* **``use_polling=True``** (either platform) — the stat-walk
  ``PollingObserver``, an operator opt-out for large trees or where the
  native watcher is unavailable.

On the non-Linux and polling paths, ignore filtering happens where it always
has: the post-debounce submitter filter
(:class:`~quarry.daemon.watch_submit.WatchSubmitter`) applies the SAME
ignore spec before any event reaches the ingest queue.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Self, cast, final

from watchdog.events import FileMovedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.utils import UnsupportedLibcError

from quarry.daemon.fs_events import FsEvent
from quarry.ingestion.pipeline import SUPPORTED_EXTENSIONS
from quarry.sync_discovery import FileDiscovery

if TYPE_CHECKING:
    from collections.abc import Callable

    from watchdog.observers.api import BaseObserver, ObservedWatch

    from quarry.daemon.inotify_prune_chain import (
        PrunedInotifyObserver as _PrunedInotifyObserverType,
    )

logger = logging.getLogger(__name__)

# Bound the observer-thread join at shutdown so a wedged native watcher can never
# hang the daemon's teardown.
_JOIN_TIMEOUT_S = 5.0

# The pruned Linux observer, or None off Linux -- imported at module scope
# (not lazily inside a function) so this is a plain conditional import, not a
# PLC0415 violation, and so pyright/mypy narrow the None-check below rather
# than needing a suppression.  Importing unconditionally and catching the
# failure (instead of branching on platform.system()) is also the more
# robust signal: it degrades correctly on any host whose libc lacks inotify,
# not just ones platform.system() happens to report as non-Linux.
_PrunedInotifyObserver: type[_PrunedInotifyObserverType] | None
try:
    from quarry.daemon.inotify_prune_chain import (
        PrunedInotifyObserver as _PrunedInotifyObserver,
    )
except (ImportError, UnsupportedLibcError):
    _PrunedInotifyObserver = None


@final
class _WatchdogHandler(FileSystemEventHandler):
    """Translate watchdog events into :class:`FsEvent` and forward them.

    A rename arrives as a ``FileMovedEvent``; it is delivered as a deletion of
    the source path and a modify of the destination path so the debouncer routes
    each half correctly.  Directory events are ignored — the loop indexes files,
    and directory-level pruning (Linux) or the post-debounce filter (elsewhere)
    already decides what is watched at all.
    """

    __slots__ = ("_on_event",)

    _on_event: Callable[[FsEvent], None]

    def __new__(cls, on_event: Callable[[FsEvent], None]) -> Self:
        self = super().__new__(cls)
        self._on_event = on_event
        return self

    def on_any_event(self, event: FileSystemEvent) -> None:
        """Forward one file event; never propagate into the observer thread."""
        if event.is_directory:
            return
        try:
            if isinstance(event, FileMovedEvent):
                self._emit(event.src_path, deleted=True)
                self._emit(event.dest_path, deleted=False)
            elif event.event_type == "deleted":
                self._emit(event.src_path, deleted=True)
            elif event.event_type in {"created", "modified"}:
                self._emit(event.src_path, deleted=False)
        except Exception:
            logger.exception("watch: event handler failed for %r", event)

    def _emit(self, raw_path: str | bytes, *, deleted: bool) -> None:
        """Forward a supported-suffix path as an :class:`FsEvent` (cheap pre-filter).

        Filtering by suffix here, on the observer thread, keeps unsupported-file
        churn out of the debouncer; the authoritative resolve/ignore filter runs
        post-debounce in the submitter.
        """
        path = Path(raw_path.decode() if isinstance(raw_path, bytes) else raw_path)
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            self._on_event(FsEvent(path, deleted=deleted))


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
        observer = cls._build_observer(
            use_polling=use_polling, poll_interval_s=poll_interval_s
        )
        observer.start()
        self._observer = observer
        return self

    @staticmethod
    def _build_observer(*, use_polling: bool, poll_interval_s: float) -> BaseObserver:
        """Return the platform-appropriate, not-yet-started observer (DES-045e).

        Picks the pruned Linux observer when the module-scope import at the
        top of this file succeeded (see ``_PrunedInotifyObserver``); falls
        back to watchdog's standard recursive observer everywhere else.
        """
        if use_polling:
            return PollingObserver(timeout=poll_interval_s)
        if _PrunedInotifyObserver is not None:
            return _PrunedInotifyObserver.create()
        return Observer()

    def schedule(
        self, root: Path, on_event: Callable[[FsEvent], None]
    ) -> object | None:
        """Begin watching *root* recursively; ``None`` if the tree cannot be watched.

        Refuses up front (before touching the observer) when *root* is
        unresolvable or is a refused temp/scratch tree
        (:attr:`~quarry.sync_discovery.FileDiscovery.root_available`) — the
        same guard the bulk scan applies, so a stale scratch registration is
        never watched by any observer. Otherwise returns the watchdog
        ``ObservedWatch`` handle, or ``None`` when the OS refuses the watch
        (e.g. inotify instance/watch exhaustion) — the caller treats a
        ``None`` handle as "this tree is unwatched, rely on scans".
        """
        if not FileDiscovery(root).root_available:
            logger.info("watch: refusing scratch/unresolvable root %s", root)
            return None
        try:
            return self._observer.schedule(
                _WatchdogHandler(on_event), str(root), recursive=True
            )
        except OSError as exc:
            logger.warning("watch: cannot watch %s (%s); relying on scans", root, exc)
            return None

    def unschedule(self, handle: object | None) -> None:
        """Stop watching the tree associated with *handle* (a no-op if ``None``)."""
        if handle is not None:
            self._observer.unschedule(cast("ObservedWatch", handle))

    def stop(self) -> None:
        """Stop the observer and join its thread under a bounded timeout."""
        self._observer.stop()
        self._observer.join(timeout=_JOIN_TIMEOUT_S)
