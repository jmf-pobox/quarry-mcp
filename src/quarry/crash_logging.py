"""Route uncaught exceptions into the log file instead of only to stderr.

A daemon's stderr goes wherever its supervisor points it — for launchd, a file
with no timestamps, which is how a traceback from one morning can be mistaken
for a live outage that afternoon.  Logging the exception instead puts it in the
same timestamped, rotating file as the operations that led to it, so the
sequence reads in one place.

Three hooks, because an uncaught exception has three ways out of a daemon and
each is a separate interpreter mechanism: the main thread's ``sys.excepthook``,
a worker thread's ``threading.excepthook``, and the event loop's exception
handler for a task nobody awaited.  Missing any one of them leaves a class of
failure invisible in the file.

Every hook delegates to the previously installed one afterwards, so stderr
keeps its copy: the supervisor's file stays a backstop for a crash that happens
before logging is configured, or that breaks logging itself.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    import asyncio
    from types import TracebackType

logger = logging.getLogger(__name__)


@final
class UncaughtExceptionLog:
    """Install hooks that log uncaught exceptions before the default handling."""

    __slots__ = ("_prior_system", "_prior_thread")

    _prior_system: object
    _prior_thread: object

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._prior_system = sys.excepthook
        self._prior_thread = threading.excepthook
        return self

    @classmethod
    def install(cls) -> Self:
        """Install the main-thread and worker-thread hooks; return the installer.

        The event loop's handler is installed separately by :meth:`bind_loop`,
        because the loop does not exist yet when the process configures logging.
        """
        self = cls()
        sys.excepthook = self._on_system_exception
        threading.excepthook = self._on_thread_exception
        return self

    @staticmethod
    def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
        """Route the loop's unhandled-exception reports into the log.

        The default handler writes to stderr through the ``asyncio`` logger only
        when a handler exists for it; binding explicitly makes the message ours
        and keeps the context dict, which names the task that failed.
        """

        def handler(
            _loop: asyncio.AbstractEventLoop, context: dict[str, object]
        ) -> None:
            message = context.get("message", "unhandled exception in event loop")
            exception = context.get("exception")
            if isinstance(exception, BaseException):
                logger.error("%s", message, exc_info=exception)
            else:
                logger.error("%s (context: %r)", message, context)

        loop.set_exception_handler(handler)

    def _on_system_exception(
        self,
        exc_type: type[BaseException],
        exc: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        """Log a main-thread exception, then let the prior hook run."""
        # A Ctrl-C is a shutdown, not a fault: log it as such and do not dress
        # it up with an ERROR and a traceback.
        if issubclass(exc_type, KeyboardInterrupt):
            logger.info("interrupted")
        else:
            logger.critical("uncaught exception", exc_info=(exc_type, exc, traceback))
        prior = self._prior_system
        if callable(prior):
            prior(exc_type, exc, traceback)

    def _on_thread_exception(self, args: threading.ExceptHookArgs) -> None:
        """Log a worker-thread exception, then let the prior hook run."""
        exc = args.exc_value
        name = args.thread.name if args.thread is not None else "unknown"
        if exc is not None:
            logger.critical("uncaught exception in thread %s", name, exc_info=exc)
        prior = self._prior_thread
        if callable(prior):
            prior(args)
