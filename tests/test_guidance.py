"""Tests for repo guide deposit and legacy-block migration."""

from __future__ import annotations

from pathlib import Path

from quarry.guidance import REPO_IMPORT_LINE, Guidance


def test_repo_import_line_is_canonical() -> None:
    assert REPO_IMPORT_LINE == "@.punt-labs/quarry/CLAUDE.md"


def test_deposit_writes_guide_wholesale(tmp_path: Path) -> None:
    guidance = Guidance(tmp_path)
    guidance.deposit()
    text = guidance.guide_path.read_text()
    assert guidance.guide_path == tmp_path / ".punt-labs" / "quarry" / "CLAUDE.md"
    assert text.startswith("# Quarry\n")
    assert "/find" in text


def test_deposit_overwrites_hand_edit(tmp_path: Path) -> None:
    """The vendored zone is deterministic: a hand edit is replaced wholesale."""
    guidance = Guidance(tmp_path)
    guidance.deposit()
    guidance.guide_path.write_text("tampered\n")
    guidance.deposit()
    assert guidance.guide_path.read_text().startswith("# Quarry\n")


def test_strip_legacy_block_removes_and_preserves_prose(tmp_path: Path) -> None:
    host = tmp_path / "CLAUDE.md"
    host.write_text(
        "# My rules\n\nBe concise.\n\n"
        "<!-- quarry:begin -->\n## Quarry\n\nold body\n<!-- quarry:end -->\n"
    )
    assert Guidance(tmp_path).strip_legacy_block() is True
    remaining = host.read_text()
    assert "quarry:begin" not in remaining
    assert "old body" not in remaining
    assert "# My rules\n\nBe concise.\n" in remaining


def test_strip_legacy_block_absent_is_noop(tmp_path: Path) -> None:
    host = tmp_path / "CLAUDE.md"
    host.write_text("# My rules\n")
    assert Guidance(tmp_path).strip_legacy_block() is False
    assert host.read_text() == "# My rules\n"


def test_strip_legacy_block_no_file_is_noop(tmp_path: Path) -> None:
    assert Guidance(tmp_path).strip_legacy_block() is False


def test_strip_legacy_block_partial_marker_is_noop(tmp_path: Path) -> None:
    """A lone begin marker is user content, not a partial block to guess at."""
    host = tmp_path / "CLAUDE.md"
    host.write_text("# rules\n<!-- quarry:begin -->\nnot closed\n")
    assert Guidance(tmp_path).strip_legacy_block() is False
    assert "not closed" in host.read_text()


def test_strip_legacy_block_preserves_crlf(tmp_path: Path) -> None:
    host = tmp_path / "CLAUDE.md"
    host.write_bytes(
        b"# rules\r\n<!-- quarry:begin -->\r\nbody\r\n<!-- quarry:end -->\r\n"
    )
    assert Guidance(tmp_path).strip_legacy_block() is True
    # The user's CRLF prose line survives byte-identical.
    assert b"# rules\r\n" in host.read_bytes()
    assert b"quarry:begin" not in host.read_bytes()
