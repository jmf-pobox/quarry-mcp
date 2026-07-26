"""Tests for the repo CLAUDE.md enable/disable orchestrator."""

from __future__ import annotations

from pathlib import Path

from quarry.enabled_marker import EnabledMarker
from quarry.enablement import Enablement
from quarry.guidance import REPO_IMPORT_LINE


def test_enable_writes_guide_marker_and_import(tmp_path: Path) -> None:
    result = Enablement(tmp_path).enable()
    assert result.guide_deposited is True
    assert result.enabled_marker_written is True
    assert result.import_registered is True
    assert result.legacy_block_stripped is False
    assert EnabledMarker(tmp_path).is_present()
    assert REPO_IMPORT_LINE in (tmp_path / "CLAUDE.md").read_text()
    assert (tmp_path / ".punt-labs" / "quarry" / "CLAUDE.md").exists()


def test_enable_biconditional_marker_iff_import(tmp_path: Path) -> None:
    """§2.11: after enable, marker present AND import present, together."""
    Enablement(tmp_path).enable()
    marker_present = EnabledMarker(tmp_path).is_present()
    import_present = REPO_IMPORT_LINE in (tmp_path / "CLAUDE.md").read_text()
    assert marker_present == import_present == True  # noqa: E712


def test_enable_is_idempotent(tmp_path: Path) -> None:
    first = Enablement(tmp_path).enable()
    second = Enablement(tmp_path).enable()
    assert first.import_registered is True
    assert second.import_registered is False
    assert (tmp_path / "CLAUDE.md").read_text().count(REPO_IMPORT_LINE) == 1


def test_enable_strips_legacy_block(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text(
        "# rules\n<!-- quarry:begin -->\nold\n<!-- quarry:end -->\n"
    )
    result = Enablement(tmp_path).enable()
    assert result.legacy_block_stripped is True
    content = (tmp_path / "CLAUDE.md").read_text()
    assert "quarry:begin" not in content
    assert REPO_IMPORT_LINE in content
    assert "# rules\n" in content


def test_disable_prunes_import_and_marker_leaves_guide(tmp_path: Path) -> None:
    Enablement(tmp_path).enable()
    result = Enablement(tmp_path).disable()
    assert result.import_pruned is True
    assert result.enabled_marker_removed is True
    assert not EnabledMarker(tmp_path).is_present()
    assert REPO_IMPORT_LINE not in (tmp_path / "CLAUDE.md").read_text()
    # §2.9: vendored guide stays dormant.
    assert (tmp_path / ".punt-labs" / "quarry" / "CLAUDE.md").exists()


def test_disable_biconditional_marker_iff_import(tmp_path: Path) -> None:
    Enablement(tmp_path).enable()
    Enablement(tmp_path).disable()
    marker_present = EnabledMarker(tmp_path).is_present()
    import_present = REPO_IMPORT_LINE in (tmp_path / "CLAUDE.md").read_text()
    assert marker_present == import_present == False  # noqa: E712


def test_disable_is_idempotent(tmp_path: Path) -> None:
    Enablement(tmp_path).enable()
    Enablement(tmp_path).disable()
    second = Enablement(tmp_path).disable()
    assert second.import_pruned is False
    assert second.enabled_marker_removed is False
