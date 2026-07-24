"""Tests for ClaudeMdBlock: append/remove the quarry block in a CLAUDE.md."""

from __future__ import annotations

from typing import TYPE_CHECKING

from quarry.claudemd_block import ClaudeMdBlock

if TYPE_CHECKING:
    from pathlib import Path


class TestAppendTo:
    def test_creates_file_when_missing(self, tmp_path: Path) -> None:
        block = ClaudeMdBlock()
        appended = block.append_to(tmp_path)

        assert appended is True
        claudemd = tmp_path / "CLAUDE.md"
        assert claudemd.exists()
        assert claudemd.read_text() == block.body

    def test_appends_newline_to_file_without_trailing_newline(
        self, tmp_path: Path
    ) -> None:
        claudemd = tmp_path / "CLAUDE.md"
        claudemd.write_text("no trailing newline")
        block = ClaudeMdBlock()

        appended = block.append_to(tmp_path)

        assert appended is True
        content = claudemd.read_text()
        assert block.begin in content

    def test_idempotent_when_block_present(self, tmp_path: Path) -> None:
        block = ClaudeMdBlock()
        assert block.append_to(tmp_path) is True
        assert block.append_to(tmp_path) is False  # already present → no-op
        content = (tmp_path / "CLAUDE.md").read_text()
        assert content.count(block.begin) == 1


class TestRemoveFrom:
    def test_no_markers_no_change(self, tmp_path: Path) -> None:
        claudemd = tmp_path / "CLAUDE.md"
        original = "# Untouched\n"
        claudemd.write_text(original)

        removed = ClaudeMdBlock().remove_from(tmp_path)

        assert removed is False
        assert claudemd.read_text() == original

    def test_missing_file_no_error(self, tmp_path: Path) -> None:
        removed = ClaudeMdBlock().remove_from(tmp_path)
        assert removed is False

    def test_removes_block_preserving_other_content(self, tmp_path: Path) -> None:
        claudemd = tmp_path / "CLAUDE.md"
        claudemd.write_text("# Keep\n\nMine.\n")
        block = ClaudeMdBlock()
        block.append_to(tmp_path)

        removed = block.remove_from(tmp_path)

        assert removed is True
        content = claudemd.read_text()
        assert "# Keep" in content
        assert "Mine." in content
        assert block.begin not in content
        assert block.end not in content
