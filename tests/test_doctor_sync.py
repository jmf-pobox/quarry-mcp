"""Unit tests for SyncRecency: the newest-sync pipeline-liveness value object."""

from __future__ import annotations

from quarry.doctor_sync import SyncRecency

_DAY = 24 * 3600


class TestSyncRecencyResult:
    """SyncRecency.result maps a recency snapshot to a doctor CheckResult."""

    def test_no_registrations_passes(self) -> None:
        result = SyncRecency(0, None).result()
        assert result.passed is True
        assert result.message == "no registrations"

    def test_fresh_newest_reports_newest_not_oldest(self) -> None:
        result = SyncRecency(2, 90 * 60).result()
        assert result.passed is True
        assert result.message == "2 collections, newest sync 1h ago"

    def test_minutes_phrase_when_under_an_hour(self) -> None:
        result = SyncRecency(1, 120).result()
        assert "newest sync 2m ago" in result.message

    def test_stale_newest_fails(self) -> None:
        """The freshest collection being > 24h old means the pipeline is dead."""
        result = SyncRecency(1, 683 * 3600).result()
        assert result.passed is False
        assert ">24h stale" in result.message

    def test_boundary_exactly_a_day_is_not_stale(self) -> None:
        result = SyncRecency(1, _DAY).result()
        assert result.passed is True

    def test_all_never_synced_passes_as_info(self) -> None:
        """No collection has ever synced: a not-yet state, never a hard failure."""
        result = SyncRecency(3, None).result()
        assert result.passed is True
        assert "none synced yet" in result.message
