from __future__ import annotations

from pathlib import Path

from quarry.sync import discover_files


class TestDiscoverFiles:
    def test_finds_supported_files(self, tmp_path: Path):
        (tmp_path / "a.pdf").touch()
        (tmp_path / "b.txt").touch()
        (tmp_path / "c.xyz").touch()
        exts = frozenset({".pdf", ".txt"})
        result = discover_files(tmp_path, exts)
        names = [p.name for p in result]
        assert "a.pdf" in names
        assert "b.txt" in names
        assert "c.xyz" not in names

    def test_recursive_discovery(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.pdf").touch()
        exts = frozenset({".pdf"})
        result = discover_files(tmp_path, exts)
        assert len(result) == 1
        assert result[0].name == "deep.pdf"

    def test_ignores_unsupported(self, tmp_path: Path):
        (tmp_path / "notes.log").touch()
        (tmp_path / "data.csv").touch()
        result = discover_files(tmp_path, frozenset({".pdf"}))
        assert result == []

    def test_empty_directory(self, tmp_path: Path):
        result = discover_files(tmp_path, frozenset({".pdf", ".txt"}))
        assert result == []

    def test_returns_sorted_absolute_paths(self, tmp_path: Path):
        (tmp_path / "z.pdf").touch()
        (tmp_path / "a.pdf").touch()
        result = discover_files(tmp_path, frozenset({".pdf"}))
        assert len(result) == 2
        assert result[0].name == "a.pdf"
        assert result[1].name == "z.pdf"
        assert all(p.is_absolute() for p in result)
