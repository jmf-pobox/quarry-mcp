"""Stdlib-only helpers for lightweight hook execution.

This module contains functions extracted from heavier modules
(``hooks``, ``__main__``) that only need stdlib imports.  Hook entry
points import from here to avoid pulling in pydantic, lancedb,
onnxruntime, and the full pipeline dependency tree.

Every function in this module MUST use only stdlib imports.
Adding a third-party import here defeats the entire purpose.
"""

from __future__ import annotations

import json
import logging
import os
import select
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_CONFIG_FILENAME = ".claude/quarry.local.md"


# ── Hook config ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class HookConfig:
    """Per-project hook configuration from ``.claude/quarry.local.md``."""

    session_sync: bool = True
    web_fetch: bool = True
    compaction: bool = True
    convention_hints: bool = True


def load_hook_config(cwd: str) -> HookConfig:
    """Load hook config from YAML frontmatter in the project's config file.

    Falls back to a pure-stdlib key: value parser when PyYAML is not
    available (which is the common case in the lightweight hook path).
    Returns defaults (all enabled) if the file is missing or unparseable.
    """
    path = Path(cwd) / _CONFIG_FILENAME
    if not path.is_file():
        return HookConfig()

    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return HookConfig()

    # Parse YAML frontmatter between --- delimiter lines.
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return HookConfig()

    end_index = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = i
            break

    if end_index is None:
        return HookConfig()

    frontmatter_lines = lines[1:end_index]

    # Extract auto_capture block with stdlib-only parsing.
    auto = _parse_auto_capture(frontmatter_lines)
    if auto is None:
        return HookConfig()

    return HookConfig(
        session_sync=_bool_field(auto, "session_sync", default=True),
        web_fetch=_bool_field(auto, "web_fetch", default=True),
        compaction=_bool_field(auto, "compaction", default=True),
        convention_hints=_bool_field(auto, "convention_hints", default=True),
    )


def _parse_auto_capture(lines: list[str]) -> dict[str, str] | None:
    """Extract key-value pairs under ``auto_capture:`` from frontmatter lines.

    Handles the simple nested YAML subset used by quarry config:
    ``auto_capture:\\n  key: value``.  Returns None if the block is absent.
    """
    result: dict[str, str] = {}
    in_block = False
    for line in lines:
        stripped = line.strip()
        if stripped == "auto_capture:":
            in_block = True
            continue
        if in_block:
            # Indented continuation lines belong to the block.
            if line.startswith((" ", "\t")) and ":" in stripped:
                key, _, val = stripped.partition(":")
                result[key.strip()] = val.strip()
            else:
                # Non-indented line ends the block.
                break
    return result if in_block else None


def _bool_field(data: dict[str, str], key: str, *, default: bool) -> bool:
    """Parse a boolean value from a string dict, with a default."""
    val = data.get(key)
    if val is None:
        return default
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    return default


# ── Hook stdin/stdout plumbing ───────────────────────────────────────


def read_hook_stdin() -> str:
    """Read hook payload from stdin without blocking.

    Claude Code may not always provide stdin (e.g. SessionStart with no
    payload).  A naive ``sys.stdin.read()`` blocks forever when no data
    and no EOF arrive.

    Uses ``select`` + ``os.read`` to consume whatever bytes are available
    within a tight timeout window, then returns.

    Falls back to ``sys.stdin.read()`` when stdin is not a real file
    descriptor (e.g. under test harnesses like ``CliRunner``).
    """
    try:
        fd = sys.stdin.fileno()
    except (AttributeError, OSError):
        return sys.stdin.read()

    if not select.select([fd], [], [], 0.1)[0]:
        return ""
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
        if not select.select([fd], [], [], 0.05)[0]:
            break
    return b"".join(chunks).decode()


def run_hook(handler: Callable[[dict[str, object]], dict[str, object]]) -> None:
    """Read stdin JSON, call *handler*, write stdout JSON.  Fail-open."""
    try:
        raw = read_hook_stdin()
        payload: dict[str, object] = json.loads(raw) if raw.strip() else {}
        result = handler(payload)
        sys.stdout.write(json.dumps(result))
        sys.stdout.write("\n")
    except Exception:
        logger.exception("Hook %s failed (fail-open)", handler.__name__)
        sys.stdout.write("{}\n")
