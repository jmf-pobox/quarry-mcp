"""Tests for CollectionMarkerStore: retained + pending-purge markers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from quarry.sync_registry import SyncRegistry

if TYPE_CHECKING:
    from pathlib import Path


def _markers(tmp_path: Path) -> SyncRegistry:
    """Return a fresh registry whose ``markers`` store is under test."""
    return SyncRegistry(tmp_path / "r.db")


class TestPendingPurgeMarkers:
    def test_mark_and_clear_pending(self, tmp_path: Path) -> None:
        conn = _markers(tmp_path)
        try:
            conn.markers.mark_pending("gone")
            conn.commit()
            assert conn.markers.pending() == {"gone"}
            conn.markers.clear_pending("gone")
            conn.commit()
            assert conn.markers.pending() == set()
        finally:
            conn.close()

    def test_uncommitted_mark_is_rolled_back(self, tmp_path: Path) -> None:
        # The store shares the registry connection and never commits; a rollback
        # discards the mark, proving marker writes ride the caller's transaction.
        conn = _markers(tmp_path)
        try:
            conn.markers.mark_pending("x")
            conn.rollback()
            assert conn.markers.pending() == set()
        finally:
            conn.close()


class TestRetainedMarkers:
    def test_mark_lists_and_tags_origin(self, tmp_path: Path) -> None:
        conn = _markers(tmp_path)
        try:
            conn.markers.mark_retained("kept", "/home/u/kept")
            conn.commit()
            assert conn.markers.list_retained() == ["kept"]
            marker = conn.markers.retained_marker("kept")
            assert marker is not None
            assert marker.collection == "kept"
            assert marker.original_directory == "/home/u/kept"
        finally:
            conn.close()

    def test_null_origin_becomes_empty_string(self, tmp_path: Path) -> None:
        # A legacy marker with no origin (NULL) reads back as "" — matches no
        # resolved directory, so it is avoided by the picker but never re-adopted.
        conn = _markers(tmp_path)
        try:
            conn.markers.mark_retained("legacy", None)
            conn.commit()
            marker = conn.markers.retained_marker("legacy")
            assert marker is not None
            assert marker.original_directory == ""
        finally:
            conn.close()

    def test_retained_marker_absent_is_none(self, tmp_path: Path) -> None:
        conn = _markers(tmp_path)
        try:
            assert conn.markers.retained_marker("nope") is None
        finally:
            conn.close()

    def test_clear_retained(self, tmp_path: Path) -> None:
        conn = _markers(tmp_path)
        try:
            conn.markers.mark_retained("kept", "/d")
            conn.commit()
            conn.markers.clear_retained("kept")
            conn.commit()
            assert conn.markers.list_retained() == []
        finally:
            conn.close()
