"""Tests for repo guide deposit."""

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
