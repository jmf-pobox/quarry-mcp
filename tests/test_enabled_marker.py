"""Tests for the repo ``enabled`` marker (tool-enable-disable.md §2.7)."""

from __future__ import annotations

import stat
from pathlib import Path

from quarry.enabled_marker import EnabledMarker


def test_absent_by_default(tmp_path: Path) -> None:
    assert EnabledMarker(tmp_path).is_present() is False


def test_write_creates_marker_and_parents(tmp_path: Path) -> None:
    marker = EnabledMarker(tmp_path)
    marker.write()
    assert marker.is_present()
    assert (tmp_path / ".punt-labs" / "quarry" / "enabled").is_file()


def test_write_uses_mode_0644(tmp_path: Path) -> None:
    marker = EnabledMarker(tmp_path)
    marker.write()
    assert stat.S_IMODE(marker.path.stat().st_mode) == 0o644


def test_write_is_idempotent(tmp_path: Path) -> None:
    marker = EnabledMarker(tmp_path)
    marker.write()
    marker.path.write_text("sentinel")  # content is irrelevant to the signal
    marker.write()
    assert marker.path.read_text() == "sentinel"


def test_remove_deletes_marker_only(tmp_path: Path) -> None:
    """Remove takes the marker but leaves the dormant vendored subtree (§2.9)."""
    marker = EnabledMarker(tmp_path)
    marker.write()
    guide = tmp_path / ".punt-labs" / "quarry" / "CLAUDE.md"
    guide.write_text("# guide\n")

    assert marker.remove() is True
    assert marker.is_present() is False
    assert guide.read_text() == "# guide\n"


def test_remove_absent_is_false(tmp_path: Path) -> None:
    assert EnabledMarker(tmp_path).remove() is False
