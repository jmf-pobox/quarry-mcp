"""Tests for the repo ``enabled`` marker (tool-enable-disable.md §2.7)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

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


def test_write_returns_true_on_create_false_when_present(tmp_path: Path) -> None:
    """write() reports whether it created the marker, mirroring remove()."""
    marker = EnabledMarker(tmp_path)
    assert marker.write() is True
    assert marker.write() is False


def test_write_present_does_not_bump_mtime(tmp_path: Path) -> None:
    """Re-enabling a present marker is a true no-op: the mtime is left as-is."""
    marker = EnabledMarker(tmp_path)
    marker.write()
    past = 1_000_000_000  # fixed past timestamp; a touch would bump it to now
    os.utime(marker.path, (past, past))
    marker.write()
    assert marker.path.stat().st_mtime == past


def test_write_uses_mode_0644_under_restrictive_umask(tmp_path: Path) -> None:
    """The creation-path chmod forces 0644 even when the umask would mask it."""
    old_umask = os.umask(0o077)
    try:
        marker = EnabledMarker(tmp_path)
        marker.write()
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(marker.path.stat().st_mode) == 0o644


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


# ── symlink safety: never follow a planted final-component symlink ────


def test_write_refuses_existing_symlink_and_leaves_target(tmp_path: Path) -> None:
    """A symlink at the marker path is refused, not followed: the target is safe."""
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")
    outside.chmod(0o600)
    marker = EnabledMarker(tmp_path)
    marker.path.parent.mkdir(parents=True, exist_ok=True)
    marker.path.symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        marker.write()

    # The external target is untouched — neither its bytes nor its mode changed.
    assert outside.read_text() == "secret\n"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o600
    assert marker.path.is_symlink()


def test_write_refuses_dangling_symlink_and_creates_no_target(tmp_path: Path) -> None:
    """A dangling symlink must not let write() create a file outside the repo."""
    external = tmp_path / "external_target"  # does not exist yet
    marker = EnabledMarker(tmp_path)
    marker.path.parent.mkdir(parents=True, exist_ok=True)
    marker.path.symlink_to(external)

    with pytest.raises(ValueError, match="symlink"):
        marker.write()

    assert not external.exists()


def test_is_present_false_for_symlink_to_file(tmp_path: Path) -> None:
    """A symlink to a real file does not spoof the enabled signal."""
    outside = tmp_path / "outside.txt"
    outside.write_text("x\n")
    marker = EnabledMarker(tmp_path)
    marker.path.parent.mkdir(parents=True, exist_ok=True)
    marker.path.symlink_to(outside)

    assert marker.is_present() is False


def test_remove_leaves_symlink_and_target(tmp_path: Path) -> None:
    """remove() does not unlink or follow a symlink at the marker path."""
    outside = tmp_path / "outside.txt"
    outside.write_text("keep\n")
    marker = EnabledMarker(tmp_path)
    marker.path.parent.mkdir(parents=True, exist_ok=True)
    marker.path.symlink_to(outside)

    assert marker.remove() is False
    assert marker.path.is_symlink()
    assert outside.read_text() == "keep\n"
