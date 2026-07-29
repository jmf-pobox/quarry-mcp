"""The resident daemon's file-descriptor envelope: raise RLIMIT_NOFILE once.

The daemon inherits launchd/systemd's soft ``RLIMIT_NOFILE`` (256 on macOS) and,
post-DES-045, holds one persistent LanceDB connection per roster database. Each
connection's reader-recycler bounds its own descriptors, but the aggregate across
a ~21-collection roster sits above a 256 limit sized for two connections, so the
daemon walks into ``EMFILE`` over long uptime. :class:`FdEnvelope` raises the soft
limit toward a configured target at daemon start — the sibling of
``ThreadConfig``'s CPU/thread envelope (DES-032), applied at the same seam before
the first ``lancedb.connect``. See DES-046.

The raise is fail-safe: a missing ``resource`` module, a raising ``getrlimit``,
or a raising ``setrlimit`` each degrade to a single logged line and the inherited
limit — the whole point is to survive, so a platform quirk must never crash the
daemon at start. A target above the hard limit is not a degrade: ``apply`` clamps
to the hard limit and successfully raises the soft limit to it. It never lowers
an already higher inherited soft limit, so an operator's ``LimitNOFILE=65536`` is
honored.
"""

from __future__ import annotations

import importlib
import logging
from types import ModuleType
from typing import Self, final

logger = logging.getLogger(__name__)

# ``resource`` is POSIX-only and absent on platforms without rlimits (e.g.
# Windows). Import it optionally, mirroring fd_headroom.py, so importing this
# module never crashes there; a missing module degrades ``apply`` to a no-op.
resource: ModuleType | None
try:
    resource = importlib.import_module("resource")
except ImportError:  # pragma: no cover - POSIX-only; non-POSIX import must not fail
    resource = None


@final
class FdEnvelope:
    """The daemon's file-descriptor budget: raise the soft ``RLIMIT_NOFILE`` once.

    Built with the target soft limit resolved from configuration
    (``Settings.fd_limit``), not a module constant, so the budget is
    env-overridable via ``QUARRY_FD_LIMIT`` at the one place it is applied.
    """

    __slots__ = ("_target",)

    _target: int

    def __new__(cls, *, target: int) -> Self:
        self = super().__new__(cls)
        self._target = target
        return self

    def apply(self) -> str:
        """Raise the soft fd limit toward the target; return the effective state.

        Fail-safe at every boundary (Bug-class-2): a missing ``resource`` module,
        a ``getrlimit`` that raises, or a ``setrlimit`` that raises degrades to a
        single logged line and the inherited limit — never a crash. A target above
        the hard limit is clamped to the hard limit and the soft limit is raised to
        it (a success, not a degrade). Never LOWERS an already-higher inherited soft
        limit (the floor is the inherited soft), so a higher operator/systemd
        ``LimitNOFILE`` is honored.
        """
        rlimits = resource
        if rlimits is None:
            state = "unavailable (no resource module on this platform)"
            logger.info("fd envelope: %s", state)
            return state
        try:
            soft, hard = rlimits.getrlimit(rlimits.RLIMIT_NOFILE)
        except OSError as exc:
            state = f"unchanged (getrlimit failed: {exc})"
            logger.warning("fd envelope: %s", state)
            return state
        unbounded = hard == rlimits.RLIM_INFINITY
        effective = self._target if unbounded else min(self._target, hard)
        if soft >= effective:
            state = f"unchanged (inherited soft {soft} already >= target {effective})"
            logger.info("fd envelope: %s", state)
            return state
        try:
            rlimits.setrlimit(rlimits.RLIMIT_NOFILE, (effective, hard))
        except (OSError, ValueError) as exc:
            state = f"unchanged (setrlimit to {effective} failed: {exc})"
            logger.warning("fd envelope: %s", state)
            return state
        state = f"raised soft {soft} -> {effective} (hard {hard})"
        logger.info("fd envelope: %s", state)
        return state
