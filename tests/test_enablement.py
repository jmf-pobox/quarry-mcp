"""Tests for the repo CLAUDE.md enable/disable orchestrator."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from quarry.claude_import import ClaudeMdImport
from quarry.enabled_marker import EnabledMarker
from quarry.enablement import Enablement
from quarry.file_lock import FileLock
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


def test_disable_symlinked_ancestor_does_not_strand_import(tmp_path: Path) -> None:
    """A SafeRepoPath marker refusal during disable must still prune the import.

    A hostile symlinked .punt-labs ancestor makes marker.remove() refuse. The
    prune must still run so a prior deregister does not leave the @-import
    lingering; the refused marker is not a real in-repo marker, and the external
    symlink target is untouched.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text(f"# rules\n{REPO_IMPORT_LINE}\n")
    external = tmp_path / "external"
    external.mkdir()
    (repo / ".punt-labs").symlink_to(external)

    result = Enablement(repo).disable()

    assert result.import_pruned is True
    assert result.enabled_marker_removed is False
    assert REPO_IMPORT_LINE not in (repo / "CLAUDE.md").read_text()
    assert list(external.iterdir()) == []  # no external effect


def test_disable_is_idempotent(tmp_path: Path) -> None:
    Enablement(tmp_path).enable()
    Enablement(tmp_path).disable()
    second = Enablement(tmp_path).disable()
    assert second.import_pruned is False
    assert second.enabled_marker_removed is False


# ── concurrency: enable/disable are atomic, never stranding the marker ─


def _churn_enable_disable(dir_str: str, iterations: int) -> None:
    enablement = Enablement(Path(dir_str))
    for _ in range(iterations):
        enablement.enable()
        enablement.disable()


def _sample_invariant(
    dir_str: str, samples: int, out: multiprocessing.Queue[int]
) -> None:
    root = Path(dir_str)
    claude = root / "CLAUDE.md"
    marker = EnabledMarker(root)
    violations = 0
    for _ in range(samples):
        # Sample marker and import together UNDER the lock, so no enable/disable
        # is mid-flight: the snapshot is a committed state, never a torn one.
        with FileLock(claude):
            marker_present = marker.is_present()
            text = claude.read_text() if claude.exists() else ""
        if marker_present and REPO_IMPORT_LINE not in text:
            violations += 1
    out.put(violations)


def test_concurrent_enable_disable_never_strands_marker(tmp_path: Path) -> None:
    """§2.11 under concurrency: no observer ever sees marker-present + import-absent.

    Churners hammer enable/disable while a sampler reads both signals under the
    shared FileLock. Because enable (register+marker) and disable (marker+prune)
    each commit atomically under that lock, a locked observer only ever sees a
    consistent state. Without the marker inside the lock, a churner's marker
    write could land between another's prune and this read — the forbidden state.
    """
    ctx = multiprocessing.get_context("spawn")
    out: multiprocessing.Queue[int] = ctx.Queue()
    churners = [
        ctx.Process(target=_churn_enable_disable, args=(str(tmp_path), 50))
        for _ in range(3)
    ]
    sampler = ctx.Process(target=_sample_invariant, args=(str(tmp_path), 500, out))
    for p in churners:
        p.start()
    sampler.start()
    for p in churners:
        p.join(timeout=60)
    sampler.join(timeout=60)
    for p in (*churners, sampler):
        if p.is_alive():
            p.terminate()
        assert p.exitcode == 0, "a child did not finish cleanly"
    violations = out.get(timeout=5)
    assert violations == 0, f"marker-present + import-absent observed {violations}x"
