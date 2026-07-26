"""Unit tests for the shared temp/scratch exclusion predicate (DES-045)."""

from __future__ import annotations

from pathlib import Path

import pytest

from quarry.scratch_paths import ScratchGuard


@pytest.mark.parametrize(
    "root",
    [
        Path("/tmp"),
        Path("/tmp/quarry-xyz"),
        Path("/private/tmp"),
        Path("/private/tmp/scan-dir"),
        Path("/var/folders/ab/xxxx/T/quarry"),
        Path("/private/var/folders/ab/xxxx/T"),
        # /var/tmp is standard OS temp on both Linux and macOS.
        Path("/var/tmp"),
        Path("/var/tmp/quarry-xyz"),
        Path("/private/var/tmp/scan-dir"),
        # Case variants — case-insensitive APFS resolves these to the same dirs,
        # so the guard casefolds both sides; /Private/Tmp caps the first letter
        # too, which casefold still normalises.
        Path("/private/TMP"),
        Path("/private/Tmp/scan-dir"),
        Path("/Private/Tmp"),
        Path("/var/Folders/ab/xxxx/T"),
        Path("/VAR/TMP/x"),
    ],
)
def test_os_temp_roots_are_refused(root: Path) -> None:
    """An OS-temp root (the /private/tmp the daemon watched) is refused."""
    assert ScratchGuard().refuses_root(root) is True


def test_repo_scratch_root_is_refused(tmp_path: Path) -> None:
    """``<repo>/.tmp`` (a repo's gitignored scratch) is refused as a root."""
    (tmp_path / ".git").mkdir()  # mark tmp_path as a git repo root
    scratch_root = tmp_path / ".tmp" / "pytest-of-me" / "docs"
    scratch_root.mkdir(parents=True)
    assert ScratchGuard().refuses_root(scratch_root) is True


def test_nested_repo_under_outer_scratch_is_refused(tmp_path: Path) -> None:
    """A nested git repo under ``<outer>/.tmp`` does not shadow the outer scratch.

    A first-``.git``-wins check would find the INNER repo (whose own ``.tmp`` the
    root is not under) and wrongly permit a root still inside the OUTER repo's
    ``.tmp`` — reopening the OCR storm.  Walking every ancestor refuses it.
    """
    (tmp_path / ".git").mkdir()  # OUTER repo
    inner = tmp_path / ".tmp" / "inner"
    inner.mkdir(parents=True)
    (inner / ".git").mkdir()  # nested INNER repo under outer's scratch
    root = inner / "docs"
    root.mkdir()
    assert ScratchGuard().refuses_root(root) is True


def test_project_root_is_not_refused(tmp_path: Path) -> None:
    """A project dir that is not inside any repo's ``.tmp`` is not refused.

    ``<repo>/src/docs`` is ordinary source, not scratch, so it is watched.  (A
    dir under a repo's OWN ``.tmp`` — including a checkout or worktree living
    there — IS refused; that over-refusal is the accepted tradeoff that closes
    the nested-repo bypass, exercised by ``test_nested_repo...``.)
    """
    (tmp_path / ".git").mkdir()
    project = tmp_path / "src" / "docs"
    project.mkdir(parents=True)
    assert ScratchGuard().refuses_root(project) is False


def test_dot_tmp_ancestor_without_repo_boundary_is_not_refused() -> None:
    """A bare ``.tmp`` ancestor with no enclosing git repo does not refuse a root."""
    # No .git anywhere on this synthetic path → repo-scratch anchor is absent.
    assert ScratchGuard().refuses_root(Path("/home/u/.tmp/watch-wt/src")) is False


@pytest.mark.parametrize(
    "name",
    [
        ".git",
        ".beads",
        ".venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        "htmlcov",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    ],
)
def test_skip_names_are_pruned_below_root(name: str) -> None:
    """Every always-skip subdirectory name is pruned below a root."""
    guard = ScratchGuard()
    assert guard.is_skip_name(name) is True
    assert guard.skips_below_root(Path(name) / "child.md") is True


def test_egg_info_suffix_is_pruned() -> None:
    """A ``*.egg-info`` build-metadata component is pruned below a root."""
    guard = ScratchGuard()
    assert guard.is_skip_name("punt_quarry.egg-info") is True
    assert guard.skips_below_root(Path("punt_quarry.egg-info/PKG-INFO")) is True


def test_ordinary_relative_path_is_not_pruned() -> None:
    """A normal root-relative path has no scratch component."""
    assert ScratchGuard().skips_below_root(Path("src/quarry/sync.py")) is False


def test_substring_match_does_not_false_positive() -> None:
    """A component that merely contains a skip name is not pruned."""
    # "mybuild"/"distribution" are not the skip names "build"/"dist".
    assert ScratchGuard().skips_below_root(Path("mybuild/distribution/n.md")) is False
