"""Unit tests for :class:`~quarry.ignore_spec.IgnoreRules`.

The behavior is also exercised indirectly through
:class:`~quarry.sync_discovery.FileDiscovery` in ``tests/test_sync.py``; these
tests pin the class's own contract directly so it stays correct even if
``FileDiscovery`` stops calling one of these methods.
"""

from __future__ import annotations

from pathlib import Path

from quarry.ignore_spec import _DEFAULT_IGNORE_PATTERNS, IgnoreRules
from quarry.scratch_paths import ScratchGuard


class TestRootSpec:
    def test_no_ignore_files_uses_defaults(self, tmp_path: Path):
        spec = IgnoreRules(tmp_path, ScratchGuard()).root_spec()
        assert spec.match_file("module.pyc")
        assert spec.match_file(".DS_Store")
        assert not spec.match_file("src/app.py")

    def test_loads_gitignore(self, tmp_path: Path):
        (tmp_path / ".gitignore").write_text("*.log\noutput/\n")
        spec = IgnoreRules(tmp_path, ScratchGuard()).root_spec()
        assert spec.match_file("debug.log")
        assert spec.match_file("output/")
        assert not spec.match_file("app.py")

    def test_loads_quarryignore(self, tmp_path: Path):
        (tmp_path / ".quarryignore").write_text("scratch/\n")
        spec = IgnoreRules(tmp_path, ScratchGuard()).root_spec()
        assert spec.match_file("scratch/")

    def test_comments_and_blanks_ignored(self, tmp_path: Path):
        (tmp_path / ".gitignore").write_text("# comment\n\n*.log\n")
        spec = IgnoreRules(tmp_path, ScratchGuard()).root_spec()
        assert spec.match_file("debug.log")
        assert not spec.match_file("# comment")


class TestLocalSpec:
    def test_root_directory_has_no_local_spec(self, tmp_path: Path):
        """The root's own .gitignore is folded into root_spec, not local_spec."""
        (tmp_path / ".gitignore").write_text("*.log\n")
        assert IgnoreRules(tmp_path, ScratchGuard()).local_spec(tmp_path) is None

    def test_subdirectory_without_gitignore_has_no_local_spec(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        assert IgnoreRules(tmp_path, ScratchGuard()).local_spec(sub) is None

    def test_subdirectory_gitignore_becomes_local_spec(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / ".gitignore").write_text("*.tmp\n")
        spec = IgnoreRules(tmp_path, ScratchGuard()).local_spec(sub)
        assert spec is not None
        assert spec.match_file("scratch.tmp")
        assert not spec.match_file("keep.py")


class TestKeepsDir:
    def test_plain_name_is_kept(self, tmp_path: Path):
        rules = IgnoreRules(tmp_path, ScratchGuard())
        root_spec = rules.root_spec()
        assert rules.keeps_dir(Path(), "src", root_spec, None) is True

    def test_hidden_name_is_pruned(self, tmp_path: Path):
        rules = IgnoreRules(tmp_path, ScratchGuard())
        root_spec = rules.root_spec()
        assert rules.keeps_dir(Path(), ".git", root_spec, None) is False

    def test_scratch_guard_name_is_pruned(self, tmp_path: Path):
        rules = IgnoreRules(tmp_path, ScratchGuard())
        root_spec = rules.root_spec()
        assert rules.keeps_dir(Path(), "node_modules", root_spec, None) is False

    def test_root_spec_match_prunes_the_name(self, tmp_path: Path):
        (tmp_path / ".gitignore").write_text("build/\n")
        rules = IgnoreRules(tmp_path, ScratchGuard())
        root_spec = rules.root_spec()
        assert rules.keeps_dir(Path(), "build", root_spec, None) is False

    def test_local_spec_match_prunes_the_name(self, tmp_path: Path):
        rules = IgnoreRules(tmp_path, ScratchGuard())
        root_spec = rules.root_spec()
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / ".gitignore").write_text("logs/\n")
        local_spec = rules.local_spec(sub)
        assert local_spec is not None
        assert rules.keeps_dir(Path("sub"), "logs", root_spec, local_spec) is False


class TestReadIgnoreLines:
    def test_absent_file_returns_empty(self, tmp_path: Path):
        assert IgnoreRules._read_ignore_lines(tmp_path / ".gitignore") == []

    def test_unreadable_file_returns_empty_not_raise(self, tmp_path: Path):
        """A directory named .gitignore triggers IsADirectoryError, not a crash."""
        (tmp_path / ".gitignore").mkdir()
        assert IgnoreRules._read_ignore_lines(tmp_path / ".gitignore") == []

    def test_reads_lines_from_a_real_file(self, tmp_path: Path):
        path = tmp_path / ".gitignore"
        path.write_text("*.log\ndata/\n")
        assert IgnoreRules._read_ignore_lines(path) == ["*.log", "data/"]


def test_default_patterns_are_globs_not_dir_names():
    # Glob patterns stay in the pathspec defaults; scratch/VCS/cache DIR names
    # live in ScratchGuard (pruned by name), so they are not duplicated here.
    assert "*.pyc" in _DEFAULT_IGNORE_PATTERNS
    assert ".DS_Store" in _DEFAULT_IGNORE_PATTERNS
    assert "node_modules/" not in _DEFAULT_IGNORE_PATTERNS
    assert "venv/" not in _DEFAULT_IGNORE_PATTERNS
