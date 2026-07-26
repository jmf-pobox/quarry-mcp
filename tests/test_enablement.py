"""Tests for the repo CLAUDE.md enable/disable orchestrator."""

from __future__ import annotations

from pathlib import Path

import pytest

from quarry.claude_import import ClaudeMdImport
from quarry.enabled_marker import EnabledMarker
from quarry.enablement import Enablement
from quarry.guidance import REPO_IMPORT_LINE


def test_enable_writes_guide_marker_and_import(tmp_path: Path) -> None:
    result = Enablement(tmp_path).enable()
    assert result.guide_deposited is True
    assert result.enabled_marker_written is True
    assert result.import_registered is True
    assert EnabledMarker(tmp_path).is_present()
    assert REPO_IMPORT_LINE in (tmp_path / "CLAUDE.md").read_text()
    assert (tmp_path / ".punt-labs" / "quarry" / "CLAUDE.md").exists()


def test_enable_biconditional_marker_iff_import(tmp_path: Path) -> None:
    """§2.11: after enable, marker present AND import present, together."""
    Enablement(tmp_path).enable()
    marker_present = EnabledMarker(tmp_path).is_present()
    import_present = REPO_IMPORT_LINE in (tmp_path / "CLAUDE.md").read_text()
    assert marker_present and import_present


def test_enable_is_idempotent(tmp_path: Path) -> None:
    first = Enablement(tmp_path).enable()
    second = Enablement(tmp_path).enable()
    assert first.import_registered is True
    assert first.enabled_marker_written is True
    assert second.import_registered is False
    assert second.enabled_marker_written is False
    assert (tmp_path / "CLAUDE.md").read_text().count(REPO_IMPORT_LINE) == 1


def test_enable_leaves_no_marker_when_register_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2.11: a register() failure leaves neither marker nor import behind."""

    def boom(self: ClaudeMdImport, import_line: str) -> bool:
        raise OSError("register failed")

    monkeypatch.setattr(ClaudeMdImport, "register", boom)

    with pytest.raises(OSError, match="register failed"):
        Enablement(tmp_path).enable()

    assert not EnabledMarker(tmp_path).is_present()


def test_enable_leaves_no_marker_when_host_ends_in_open_fence(tmp_path: Path) -> None:
    """§2.11: enabling a CLAUDE.md that ends in an unterminated fence fails closed.

    The import would land inside the open fence — inert — so register raises and
    the marker is never written, leaving neither an inert import nor a marker
    that would falsely advertise enablement.
    """
    (tmp_path / "CLAUDE.md").write_text("# rules\n\n```\nnever closed\n")

    with pytest.raises(ValueError, match="unterminated code fence"):
        Enablement(tmp_path).enable()

    assert not EnabledMarker(tmp_path).is_present()
    assert REPO_IMPORT_LINE not in (tmp_path / "CLAUDE.md").read_text()


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
    assert not marker_present and not import_present


def test_disable_removes_marker_before_prune_can_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2.11: a prune() failure during disable leaves marker-absent, never present."""
    Enablement(tmp_path).enable()

    def boom(self: ClaudeMdImport, import_line: str) -> bool:
        raise OSError("prune failed")

    monkeypatch.setattr(ClaudeMdImport, "prune", boom)

    with pytest.raises(OSError, match="prune failed"):
        Enablement(tmp_path).disable()

    assert not EnabledMarker(tmp_path).is_present()


def test_disable_is_idempotent(tmp_path: Path) -> None:
    Enablement(tmp_path).enable()
    Enablement(tmp_path).disable()
    second = Enablement(tmp_path).disable()
    assert second.import_pruned is False
    assert second.enabled_marker_removed is False
