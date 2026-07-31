"""Tests for ``scripts/logs-errors.sh`` — the daemon-log error diagnostic.

The quarry daemon appends to ``~/.punt-labs/quarry/logs`` (quarry-stderr.log,
quarry.log, quarry-stdout.log). Nothing surfaced the errors accruing there —
``quarry doctor`` does not read the log and no one greps it — so a broken
watch/sync feature logged 100+ ``Watch index failed`` lines that sat unnoticed
for weeks. ``make logs-errors`` (this script) closes that blind spot.

Per CLAUDE.md Class 5 / testing rule 6, shell logic gets a mock/fixture test,
not just shellcheck (shellcheck coverage for every ``scripts/*.sh`` lives in
``test_build_scripts.py``). These drive the script against a synthetic fixture
log dir and assert it (a) reports the known errors, (b) always exits 0 — it is a
diagnostic, not a gate — and (c) handles a missing or empty log dir gracefully.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOGS_ERRORS = REPO_ROOT / "scripts" / "logs-errors.sh"

# A synthetic stderr log carrying two of the real signals the daemon emits: the
# broken-watch line (the incident that motivated the target) and the historical
# LanceDB fd exhaustion. The INFO line is a benign control that must NOT count.
FIXTURE_STDERR = (
    "2026-07-30 12:00:00 [INFO] quarry.sync: Ingested /x/a.py\n"
    "2026-07-30 12:00:01 Watch index failed for a.py: File not found: /x/a.py\n"
    "2026-07-30 12:00:02 LanceError(IO): Too many open files (os error 24)\n"
)


def _run(
    log_dir: Path, log_lines: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Invoke the script against *log_dir* via the LOG_DIR override.

    LOG_DIR points the scan at a fixture dir so the test never touches the live
    ``~/.punt-labs/quarry/logs``. LOG_LINES, when given, sets the recent-lines
    tail (and exercises the non-integer fallback when passed junk).
    """
    env = {**os.environ, "LOG_DIR": str(log_dir)}
    if log_lines is not None:
        env["LOG_LINES"] = log_lines
    return subprocess.run(
        ["bash", str(LOGS_ERRORS)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _write_log(log_dir: Path, name: str, text: str) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / name).write_text(text)


def test_reports_known_errors_and_exits_zero(tmp_path: Path) -> None:
    """A fixture with known error lines is summarized, and the script exits 0.

    Exit 0 is load-bearing: the target is a diagnostic like ``make report``, not
    a gate. Finding errors must not fail the caller.
    """
    logs = tmp_path / "logs"
    _write_log(logs, "quarry-stderr.log", FIXTURE_STDERR)
    result = _run(logs, log_lines="10")
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    out = result.stdout
    assert "Watch index failed:" in out, "per-signal summary must be present"
    assert "Too many open files / EMFILE:" in out
    # Two distinct lines carry a signal; the INFO line carries none.
    assert "2 error lines found" in out
    # The recent-lines block echoes the actual matching lines back.
    assert "Watch index failed for a.py" in out
    assert "Too many open files" in out


def test_benign_log_reports_no_errors(tmp_path: Path) -> None:
    """A log with only INFO lines reports 'no errors found' and exits 0."""
    logs = tmp_path / "logs"
    _write_log(
        logs,
        "quarry.log",
        "2026-07-30 12:00:00 [INFO] quarry.sync: indexing complete for foo.py\n",
    )
    result = _run(logs)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "no errors found" in result.stdout
    assert "error lines found" not in result.stdout


def test_missing_log_dir_is_graceful(tmp_path: Path) -> None:
    """An absent log dir is the normal pre-daemon state: report it, exit 0.

    This is the exception-boundary discipline (bug class 2) for shell — the
    diagnostic must not error out when the daemon has never written a log.
    """
    missing = tmp_path / "never-created"
    result = _run(missing)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert f"no daemon logs at {missing}" in result.stdout


def test_empty_log_dir_is_graceful(tmp_path: Path) -> None:
    """A log dir that exists but holds no ``*.log`` files exits 0 cleanly."""
    logs = tmp_path / "logs"
    logs.mkdir()
    result = _run(logs)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert f"no daemon logs at {logs}" in result.stdout


def test_non_integer_log_lines_falls_back(tmp_path: Path) -> None:
    """A non-integer LOG_LINES warns and falls back to 40, never crashes tail.

    LOG_LINES feeds ``tail -n``; junk would abort it. The script must warn and
    continue (exit 0), producing its normal report.
    """
    logs = tmp_path / "logs"
    _write_log(logs, "quarry-stderr.log", FIXTURE_STDERR)
    result = _run(logs, log_lines="not-a-number")
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "is not a non-negative integer" in result.stderr
    assert "2 error lines found" in result.stdout


def test_rotated_logs_are_excluded(tmp_path: Path) -> None:
    """Rotated ``quarry.log.1`` files are not scanned — only live ``*.log``.

    The glob targets ``*.log``; ``quarry.log.1`` matches ``*.log.1``, not
    ``*.log``, so a signal that lives only in a rotated file is not counted.
    """
    logs = tmp_path / "logs"
    _write_log(logs, "quarry.log", "2026-07-30 12:00:00 [INFO] quarry.sync: ok\n")
    _write_log(logs, "quarry.log.1", "Watch index failed for old.py: File not found\n")
    result = _run(logs)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "no errors found" in result.stdout
