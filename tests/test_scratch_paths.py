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
        # Case variants — case-insensitive APFS resolves these to the same dirs,
        # so the guard must casefold both sides (djb).
        Path("/private/TMP"),
        Path("/private/Tmp/scan-dir"),
        Path("/var/Folders/ab/xxxx/T"),
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


def test_project_root_is_not_refused(tmp_path: Path) -> None:
    """A normal project root — even under a ``.tmp`` ANCESTOR — is not refused.

    A checkout can legitimately live under a ``.tmp`` ancestor (a git worktree);
    only a repo's OWN ``.tmp`` (a direct child of its git root) is scratch.
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
