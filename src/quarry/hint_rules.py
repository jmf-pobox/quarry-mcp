"""Convention hint rules: instant and sequence-based.

Pure functions that map commands (and recent event history) to
advisory hint strings.  No I/O, no side effects, fully deterministic.
"""

from __future__ import annotations

import re

from quarry.hint_accumulator import ToolEvent

# ---------------------------------------------------------------------------
# Instant rules — fire on the current command alone
# ---------------------------------------------------------------------------

_INSTANT_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"git\s+add\s+(-A|\.)\s*$"),
        "Reminder: stage specific files by name rather than `git add -A` or "
        "`git add .` — avoids accidentally staging secrets or large binaries.",
    ),
    (
        re.compile(r"(?<!\buv\s)(?<!\buv\s\s)\bpip\s+install\b"),
        "Reminder: use `uv` for package management, not `pip`.",
    ),
    (
        re.compile(r"git\s+push\s.*(-f|--force)\b"),
        "Reminder: force-push is destructive — confirm this is intentional.",
    ),
    (
        re.compile(r"git\s+commit\s.*(-n\b|--no-verify)"),
        "Reminder: do not skip hooks (`--no-verify`) unless explicitly asked.",
    ),
]


def check_instant_rules(command: str) -> str | None:
    """Return the first matching instant hint, or ``None``."""
    for pattern, hint in _INSTANT_RULES:
        if pattern.search(command):
            return hint
    return None


# ---------------------------------------------------------------------------
# Sequence rules — require temporal context from the accumulator
# ---------------------------------------------------------------------------

_GATE_COMPONENTS = frozenset({"ruff check", "ruff format", "mypy", "pyright", "pytest"})

_FULL_GATE = (
    "Reminder: run the full quality gate before committing: "
    "`uv run ruff check . && uv run ruff format --check . "
    "&& uv run mypy src/ tests/ && uv run pyright && uv run pytest`"
)

_SOLO_GATE_HINT = (
    "Tip: prefer the full quality gate chain (`uv run ruff check . && ...`) "
    "over running individual tools separately."
)

_SOLO_GATE_PATTERN = re.compile(
    r"^uv\s+run\s+(ruff\s+check|ruff\s+format|mypy|pyright|pytest)\b"
)


def _command_has_full_gate(command: str) -> bool:
    """Check if *command* contains all quality gate components."""
    return all(component in command for component in _GATE_COMPONENTS)


def check_sequence_rules(events: list[ToolEvent], command: str) -> str | None:
    """Return the first matching sequence hint, or ``None``.

    Parameters
    ----------
    events:
        Recent events from the accumulator (already pruned).
    command:
        The current command about to be executed.
    """
    # Rule: git commit without preceding full gate
    if re.search(r"\bgit\s+commit\b", command):
        recent = events[-10:]
        if not any(_command_has_full_gate(e.command) for e in recent):
            return _FULL_GATE

    # Rule: 2+ consecutive solo gate tools (chained commands don't count)
    if _SOLO_GATE_PATTERN.search(command) and "&&" not in command:
        consecutive = 0
        for e in reversed(events):
            if _SOLO_GATE_PATTERN.search(e.command):
                consecutive += 1
            else:
                break
        if consecutive >= 1:
            return _SOLO_GATE_HINT

    return None
