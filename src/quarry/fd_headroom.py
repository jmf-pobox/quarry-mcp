"""Open file descriptors measured against the process's ``RLIMIT_NOFILE``.

A long-lived daemon that leaks descriptors fails silently until it hits its soft
limit and every ``open()`` returns ``EMFILE`` — surfacing to users as an HTTP 500
on ``quarry find``. This value object samples the current count so both the doctor
health check and the serve-time telemetry can warn before the wall is hit.

The measurement itself needs a file descriptor (the ``iterdir`` scan opens a
directory handle) — at real exhaustion the sample *is what fails*, so ``sample``
lets that ``OSError`` propagate rather than masking it as healthy. Both callers
absorb it without reading ``errno``: the ``/health`` route (``routes/meta.py``)
reports ``fd: null``; ``fd_telemetry`` logs one line and keeps sampling.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Self, final

# ``resource`` is POSIX-only and absent on platforms without rlimits (e.g.
# Windows). Import it optionally so ``import quarry`` never crashes there; when
# it is missing the sampler degrades exactly like a missing fd directory —
# ``sample`` raises an errno-less ``OSError`` (callers report "unavailable") and
# ``describe`` treats the limit as unbounded — instead of poisoning the import
# chain (fd_headroom is imported by fd_telemetry, doctor_daemon, and meta routes).
resource: ModuleType | None
try:
    resource = importlib.import_module("resource")
except ImportError:
    resource = None

# Warn once the process crosses this fraction of its soft descriptor limit —
# early enough to act before EMFILE, late enough to avoid nuisance warnings.
_FD_WARN_RATIO = 0.8


@final
@dataclass(frozen=True, slots=True)
class FdHeadroom:
    """Open file descriptors measured against the soft ``RLIMIT_NOFILE`` ceiling."""

    open_fds: int
    soft_limit: int

    @classmethod
    def sample(cls) -> Self:
        """Measure the current process's open descriptors and soft fd limit.

        Propagates ``OSError`` when the scan cannot run: descriptor exhaustion
        (the ``EMFILE``/``ENFILE`` case where the scan itself is what fails) or an
        errno-less ``OSError`` for a missing fd directory or an absent POSIX
        ``resource`` module. Neither caller branches on ``errno``: the ``/health``
        route reports ``fd: null``; the telemetry loop logs and keeps sampling.
        """
        rlimits = resource
        if rlimits is None:
            msg = "no resource module on this platform"
            raise OSError(msg)
        soft, _hard = rlimits.getrlimit(rlimits.RLIMIT_NOFILE)
        return cls(open_fds=cls._count_open_fds(), soft_limit=soft)

    @staticmethod
    def _count_open_fds() -> int:
        """Return this process's open-descriptor count via ``/proc`` or ``/dev/fd``.

        Raises a plain ``OSError`` (``errno`` unset) when neither directory
        exists — genuine platform absence. Under real descriptor exhaustion the
        ``iterdir`` scan raises ``OSError(EMFILE)``; that propagates unchanged too,
        and the sole caller collapses both to ``fd: null`` without reading errno.
        """
        for fd_dir in ("/proc/self/fd", "/dev/fd"):
            path = Path(fd_dir)
            if path.is_dir():
                return sum(1 for _ in path.iterdir())
        msg = "no /proc/self/fd or /dev/fd on this platform"
        raise OSError(msg)

    @property
    def _is_bounded(self) -> bool:
        """Whether the soft limit is a real positive ceiling, not ``RLIM_INFINITY``."""
        # RLIM_INFINITY is a large positive int, not 0, yet still means unbounded;
        # an absent ``resource`` module is treated as unbounded too (describe ->
        # "unlimited", utilization -> 0.0).
        rlimits = resource
        if rlimits is None:
            return False
        return self.soft_limit > 0 and self.soft_limit != rlimits.RLIM_INFINITY

    @property
    def utilization(self) -> float:
        """Fraction of the soft limit in use (``0.0`` when the limit is unbounded)."""
        if not self._is_bounded:
            return 0.0
        return self.open_fds / self.soft_limit

    @property
    def is_low(self) -> bool:
        """Whether descriptor usage has crossed the warning threshold."""
        return self.utilization > _FD_WARN_RATIO

    def describe(self) -> str:
        """Return a compact ``used/limit (pct%)`` summary.

        Renders ``used/unlimited fds`` when the soft limit is unbounded, rather
        than printing the giant ``RLIM_INFINITY`` sentinel and a meaningless 0%.
        """
        if not self._is_bounded:
            return f"{self.open_fds}/unlimited fds"
        return (
            f"{self.open_fds}/{self.soft_limit} fds ({round(self.utilization * 100)}%)"
        )
