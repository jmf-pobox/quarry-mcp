"""Hermetic tests for FinalizeThrottle — per-database finalize rate-limiting.

Driven on a real event loop with a tiny interval and a counting thunk, so the
run-now / coalesce-into-trailing / per-database-independence / disabled-passthrough
behaviours are asserted without the queue, watchdog, or the filesystem.
"""

from __future__ import annotations

import asyncio

from quarry.daemon.watch_submit import FinalizeThrottle

_INTERVAL = 0.05


def test_first_request_runs_immediately() -> None:
    async def _run() -> None:
        calls = 0

        def submit() -> None:
            nonlocal calls
            calls += 1

        throttle = FinalizeThrottle(asyncio.get_running_loop(), _INTERVAL)
        throttle.request("db", submit)
        assert calls == 1

    asyncio.run(_run())


def test_burst_within_interval_coalesces_to_one_trailing() -> None:
    """First fires now; the rest inside the window collapse to one trailing run."""

    async def _run() -> None:
        calls = 0

        def submit() -> None:
            nonlocal calls
            calls += 1

        throttle = FinalizeThrottle(asyncio.get_running_loop(), _INTERVAL)
        for _ in range(10):
            throttle.request("db", submit)
        assert calls == 1  # only the first ran inline
        await asyncio.sleep(_INTERVAL * 2)
        assert calls == 2  # exactly one trailing finalize, not ten

    asyncio.run(_run())


def test_request_after_interval_runs_immediately_again() -> None:
    async def _run() -> None:
        calls = 0

        def submit() -> None:
            nonlocal calls
            calls += 1

        throttle = FinalizeThrottle(asyncio.get_running_loop(), _INTERVAL)
        throttle.request("db", submit)
        await asyncio.sleep(_INTERVAL * 2)
        throttle.request("db", submit)
        assert calls == 2  # interval elapsed, so the second ran inline

    asyncio.run(_run())


def test_databases_are_independent() -> None:
    async def _run() -> None:
        calls: dict[str, int] = {"a": 0, "b": 0}
        throttle = FinalizeThrottle(asyncio.get_running_loop(), _INTERVAL)
        throttle.request("a", lambda: calls.__setitem__("a", calls["a"] + 1))
        throttle.request("b", lambda: calls.__setitem__("b", calls["b"] + 1))
        # Each database's first request runs immediately, independent of the other.
        assert calls == {"a": 1, "b": 1}

    asyncio.run(_run())


def test_disabled_interval_runs_every_request() -> None:
    async def _run() -> None:
        calls = 0

        def submit() -> None:
            nonlocal calls
            calls += 1

        throttle = FinalizeThrottle(asyncio.get_running_loop(), 0.0)
        for _ in range(5):
            throttle.request("db", submit)
        assert calls == 5  # rate-limit off: no coalescing

    asyncio.run(_run())


def test_cancel_all_drops_pending_trailing() -> None:
    async def _run() -> None:
        calls = 0

        def submit() -> None:
            nonlocal calls
            calls += 1

        throttle = FinalizeThrottle(asyncio.get_running_loop(), _INTERVAL)
        throttle.request("db", submit)  # runs now
        throttle.request("db", submit)  # arms a trailing timer
        throttle.cancel_all()
        await asyncio.sleep(_INTERVAL * 2)
        assert calls == 1  # the trailing finalize was cancelled

    asyncio.run(_run())


def test_immediate_path_cancels_pending_timer_no_double_fire() -> None:
    """The immediate path must CANCEL a pending trailing timer, not just drop it.

    Otherwise a debounce flush landing in the tick the timer is due runs the
    immediate finalize AND leaves the overdue timer queued → two finalizes.
    """

    async def _run() -> None:
        calls = 0

        def submit() -> None:
            nonlocal calls
            calls += 1

        loop = asyncio.get_running_loop()
        # Long interval so the trailing timer stays pending under our control.
        throttle = FinalizeThrottle(loop, 100.0)
        throttle.request("db", submit)  # fires now (calls=1), stamps _last
        throttle.request("db", submit)  # within interval → arms a trailing timer
        # White-box: reach into the throttle's event-loop state to force the exact
        # race deterministically (real timing would be flaky).
        pending = throttle._timers["db"]
        assert not pending.cancelled()
        # Force the immediate branch while the timer is still pending, exactly as a
        # debounce flush arriving at/after the due time would: backdate _last.
        throttle._last["db"] = loop.time() - 200.0
        throttle.request("db", submit)  # immediate _fire → must cancel `pending`
        assert calls == 2  # the immediate finalize ran once more
        assert pending.cancelled()  # THE FIX: no overdue timer left to double-fire
        await asyncio.sleep(0)  # let any (wrongly) surviving callback run
        assert calls == 2

    asyncio.run(_run())
