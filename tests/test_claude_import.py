"""Tests for the bare ``@``-import reconciler (tool-enable-disable.md §2.4)."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from quarry.claude_import import ClaudeMdImport

IMPORT = "@.punt-labs/quarry/CLAUDE.md"


# ── register: presence, idempotence, separation ──────────────────────


def test_register_appends_to_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    assert ClaudeMdImport(path).register(IMPORT) is True
    assert path.read_text() == f"{IMPORT}\n"


def test_register_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    imp = ClaudeMdImport(path)
    assert imp.register(IMPORT) is True
    assert imp.register(IMPORT) is False
    assert path.read_text().count(IMPORT) == 1


def test_register_ensures_separation_from_last_line(tmp_path: Path) -> None:
    """A host file with no trailing newline gets one before the import."""
    path = tmp_path / "CLAUDE.md"
    path.write_text("my rules")  # no trailing newline
    ClaudeMdImport(path).register(IMPORT)
    assert path.read_text() == f"my rules\n{IMPORT}\n"


def test_register_preserves_user_prose(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    prose = "# My rules\n\nBe concise.\n"
    path.write_text(prose)
    ClaudeMdImport(path).register(IMPORT)
    assert path.read_text() == f"{prose}{IMPORT}\n"


# ── host EOL preservation ────────────────────────────────────────────


def test_register_uses_crlf_on_crlf_host(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_bytes(b"rule one\r\nrule two\r\n")
    ClaudeMdImport(path).register(IMPORT)
    assert path.read_bytes() == f"rule one\r\nrule two\r\n{IMPORT}\r\n".encode()


def test_register_uses_lone_cr_on_cr_host(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_bytes(b"rule one\rrule two\r")
    ClaudeMdImport(path).register(IMPORT)
    assert path.read_bytes() == f"rule one\rrule two\r{IMPORT}\r".encode()


def test_register_idempotent_on_crlf_host(tmp_path: Path) -> None:
    """Terminator-insensitive match: a CRLF-terminated import is not duplicated."""
    path = tmp_path / "CLAUDE.md"
    path.write_bytes(f"{IMPORT}\r\n".encode())
    assert ClaudeMdImport(path).register(IMPORT) is False
    assert path.read_bytes() == f"{IMPORT}\r\n".encode()


def test_register_uses_lf_first_newline_despite_stray_cr(tmp_path: Path) -> None:
    """A mostly-LF host with a stray CR mid-body gets an LF-terminated import."""
    path = tmp_path / "CLAUDE.md"
    path.write_bytes(b"line one\nli\rne two\n")
    ClaudeMdImport(path).register(IMPORT)
    assert path.read_bytes() == b"line one\nli\rne two\n" + f"{IMPORT}\n".encode()


# ── prune ────────────────────────────────────────────────────────────


def test_prune_removes_the_line(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"# rules\n{IMPORT}\n")
    assert ClaudeMdImport(path).prune(IMPORT) is True
    assert path.read_text() == "# rules\n"


def test_prune_absent_is_noop(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_text("# rules\n")
    assert ClaudeMdImport(path).prune(IMPORT) is False
    assert path.read_text() == "# rules\n"


def test_prune_collapses_accidental_duplicate(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"{IMPORT}\nmiddle\n{IMPORT}\n")
    assert ClaudeMdImport(path).prune(IMPORT) is True
    assert path.read_text() == "middle\n"


def test_prune_on_crlf_host(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_bytes(f"# rules\r\n{IMPORT}\r\n".encode())
    assert ClaudeMdImport(path).prune(IMPORT) is True
    assert path.read_bytes() == b"# rules\r\n"


# ── code-block skip (fenced + indented) ──────────────────────────────


def test_register_ignores_fenced_copy(tmp_path: Path) -> None:
    """A fenced example of the import is not a real import: register still appends."""
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"# docs\n\n```\n{IMPORT}\n```\n")
    assert ClaudeMdImport(path).register(IMPORT) is True
    # The fenced copy stays; a real top-level import is appended at EOF.
    text = path.read_text()
    assert text.endswith(f"```\n{IMPORT}\n")
    assert text.count(IMPORT) == 2


def test_prune_leaves_fenced_copy(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"```text\n{IMPORT}\n```\n{IMPORT}\n")
    assert ClaudeMdImport(path).prune(IMPORT) is True
    # Only the top-level copy is removed; the fenced example survives.
    assert path.read_text() == f"```text\n{IMPORT}\n```\n"


def test_prune_leaves_tilde_fenced_copy(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"~~~\n{IMPORT}\n~~~\n{IMPORT}\n")
    assert ClaudeMdImport(path).prune(IMPORT) is True
    assert path.read_text() == f"~~~\n{IMPORT}\n~~~\n"


def test_prune_leaves_indented_copy(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"    {IMPORT}\n{IMPORT}\n")
    assert ClaudeMdImport(path).prune(IMPORT) is True
    assert path.read_text() == f"    {IMPORT}\n"


def test_prune_leaves_tab_indented_copy(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"\t{IMPORT}\n{IMPORT}\n")
    assert ClaudeMdImport(path).prune(IMPORT) is True
    assert path.read_text() == f"\t{IMPORT}\n"


def test_register_ignores_copy_after_closed_fence(tmp_path: Path) -> None:
    """After a fence closes, a top-level copy IS seen: register is a no-op."""
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"```\nexample\n```\n{IMPORT}\n")
    assert ClaudeMdImport(path).register(IMPORT) is False


def test_prune_sees_both_imports_across_indented_fence(tmp_path: Path) -> None:
    """An indented ``` is code, not a fence: both top-level imports still prune."""
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"{IMPORT}\n    ```\n{IMPORT}\n")
    assert ClaudeMdImport(path).prune(IMPORT) is True
    # Both top-level copies removed; the indented example line survives.
    assert path.read_text() == "    ```\n"


def test_prune_leaves_import_in_backtick_fence_holding_tilde_line(
    tmp_path: Path,
) -> None:
    """A ~~~ line does not close a ```-fence: the inside import is shielded."""
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"```\n~~~\n{IMPORT}\n```\n{IMPORT}\n")
    assert ClaudeMdImport(path).prune(IMPORT) is True
    # Only the top-level copy after the fence is removed; the fenced one stays.
    assert path.read_text() == f"```\n~~~\n{IMPORT}\n```\n"


def test_prune_leaves_import_after_info_string_line_inside_fence(
    tmp_path: Path,
) -> None:
    """A ```note line has an info string, so it does not close the fence."""
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"```\n```note\n{IMPORT}\n```\n{IMPORT}\n")
    assert ClaudeMdImport(path).prune(IMPORT) is True
    # The import inside the still-open fence survives; only the top-level one goes.
    assert path.read_text() == f"```\n```note\n{IMPORT}\n```\n"


# ── boundary validation ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "no-at-prefix", "@has space at end ", " @leading", "@a\nb"],
)
def test_register_rejects_malformed_line(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="import line"):
        ClaudeMdImport(tmp_path / "CLAUDE.md").register(bad)


# ── symlink ──────────────────────────────────────────────────────────


def test_register_through_symlink_preserves_link(tmp_path: Path) -> None:
    real = tmp_path / "real.md"
    real.write_text("# rules\n")
    link = tmp_path / "CLAUDE.md"
    link.symlink_to(real)
    ClaudeMdImport(link).register(IMPORT)
    assert link.is_symlink()
    assert real.read_text() == f"# rules\n{IMPORT}\n"


# ── exclusive lock: no lost update under concurrency ─────────────────


def _register_line(path_str: str, line: str) -> None:
    ClaudeMdImport(Path(path_str)).register(line)


def test_concurrent_registers_do_not_lose_updates(tmp_path: Path) -> None:
    """Two processes registering distinct lines both land (the lock's job)."""
    path = tmp_path / "CLAUDE.md"
    path.write_text("# rules\n")
    lines = [f"@.punt-labs/tool{i}/CLAUDE.md" for i in range(8)]
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_register_line, args=(str(path), ln)) for ln in lines]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
    for p in procs:
        if p.is_alive():
            p.terminate()
        assert p.exitcode == 0, "a child did not finish cleanly"
    text = path.read_text()
    for ln in lines:
        assert ln in text, f"lost update: {ln} missing"
