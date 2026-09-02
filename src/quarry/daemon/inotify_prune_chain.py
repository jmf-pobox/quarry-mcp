"""The watchdog construction chain that wires :class:`PrunedInotify` in.

Split out of :mod:`~quarry.daemon.inotify_prune` (which owns the pruning
ALGORITHM) because watchdog's ``InotifyBuffer`` → ``InotifyEmitter`` →
``BaseObserver`` chain each hardcode the next class down inline, with no
factory hook to override — reaching :class:`~quarry.daemon.inotify_prune.
PrunedInotify` from :class:`PrunedInotifyObserver` therefore requires
overriding one method or constructor at each of the three levels. Every
override here is a verbatim, low-drift copy of its vanilla counterpart's
3-4 line body with one class name substituted;
``tests/test_inotify_prune.py``'s
``test_pins_the_watchdog_internals_this_module_subclasses`` fails loudly if a
future watchdog release renames or removes any of the methods this module
depends on.

None of these three classes define ``__init__`` (PY-CC-1): each vanilla
parent's ``__init__`` does something this class must NOT run unmodified
(construct a vanilla ``Inotify``, or omit the injected ``emitter_class``), so
each uses a ``create`` classmethod factory (PY-CC-5) that performs
construction directly via ``object.__new__`` rather than relying on
``type.__call__``'s automatic post-``__new__`` invocation of the (harmful,
unoverridable-by-signature) inherited ``__init__``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Self, final

from watchdog.observers.api import DEFAULT_OBSERVER_TIMEOUT, BaseObserver
from watchdog.observers.inotify import InotifyEmitter
from watchdog.observers.inotify_buffer import InotifyBuffer
from watchdog.utils import BaseThread
from watchdog.utils.delayed_queue import DelayedQueue

from quarry.daemon.inotify_prune import PrunedInotify

if TYPE_CHECKING:
    from watchdog.observers.inotify_c import InotifyEvent


@final
class PrunedInotifyBuffer(InotifyBuffer):
    """An ``InotifyBuffer`` that builds a :class:`PrunedInotify`."""

    _queue: DelayedQueue[InotifyEvent | tuple[InotifyEvent, InotifyEvent]]

    @classmethod
    def create(
        cls, path: bytes, *, recursive: bool = False, event_mask: int | None = None
    ) -> Self:
        """Build one, running ``InotifyBuffer``'s own thread-start side effect.

        ``InotifyBuffer.__init__`` constructs the vanilla ``Inotify`` inline
        and this needs :class:`PrunedInotify` there instead, so this
        replicates its four-line body directly rather than calling
        ``super().__init__()`` (which would reintroduce the vanilla
        ``Inotify``) or defining an ``__init__`` override at all -- the
        class-level ``__init__`` this factory bypasses is never invoked
        because nothing ever calls ``PrunedInotifyBuffer(...)`` directly.
        """
        self = object.__new__(cls)
        BaseThread.__init__(self)
        self._queue = DelayedQueue(self.delay)
        self._inotify = PrunedInotify(path, recursive=recursive, event_mask=event_mask)
        self.start()
        return self


@final
class PrunedInotifyEmitter(InotifyEmitter):
    """An ``InotifyEmitter`` whose thread builds a :class:`PrunedInotifyBuffer`."""

    def on_thread_start(self) -> None:
        path = os.fsencode(self.watch.path)
        event_mask = self.get_event_mask_from_filter()
        self._inotify = PrunedInotifyBuffer.create(
            path, recursive=self.watch.is_recursive, event_mask=event_mask
        )


@final
class PrunedInotifyObserver(BaseObserver):
    """A Linux inotify observer whose recursive watches are pruned per DES-045e.

    Constructs :class:`PrunedInotifyEmitter` directly rather than subclassing
    ``InotifyObserver`` (whose entire body is picking between ``InotifyEmitter``
    and ``InotifyFullEmitter`` -- full move events are never used here, so
    there is nothing else in it worth inheriting).
    """

    @classmethod
    def create(cls, *, timeout: float = DEFAULT_OBSERVER_TIMEOUT) -> Self:
        """Build one, injecting :class:`PrunedInotifyEmitter` as the emitter class.

        ``BaseObserver.__init__`` requires ``emitter_class`` positionally
        with no default, so a plain ``PrunedInotifyObserver(timeout=...)``
        call cannot supply it -- this factory calls ``BaseObserver.__init__``
        directly with the class injected, and (like the sibling factories in
        this module) never lets ``type.__call__`` invoke any inherited
        ``__init__`` automatically.
        """
        self = object.__new__(cls)
        BaseObserver.__init__(self, PrunedInotifyEmitter, timeout=timeout)
        return self
