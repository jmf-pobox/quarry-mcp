"""Deposit quarry's repo user-guide and strip its legacy marker block."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from quarry.atomic_file import AtomicFile
from quarry.file_lock import FileLock

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["REPO_IMPORT_LINE", "Guidance"]

# The canonical repo import line (tool-enable-disable.md § 2.4): forward
# slashes, no ``./`` prefix, no trailing slash, one physical line. quarry's
# guidance is repo-scoped, so only this repo-scope line is ever written.
REPO_IMPORT_LINE = "@.punt-labs/quarry/CLAUDE.md"

# The vendored user guide (§ 2.5): how an agent DRIVES quarry, deposited
# verbatim into ``<repo>/.punt-labs/quarry/CLAUDE.md`` and imported by the
# repo's CLAUDE.md. Static content shipped with the tool — the same guide
# everywhere, overwritten wholesale on every enable/upgrade.
_GUIDE = """\
# Quarry

Local semantic search is available via quarry. Use it to search indexed
documents by meaning, ingest new content, and recall knowledge across sessions.

- Before using WebSearch or WebFetch for research, run `/find` with the query
  first. Quarry indexes this codebase, design docs, prior session transcripts,
  and web pages from previous research. If quarry returns relevant results,
  use them — do not re-research what has already been found.
- Use grep for symbol lookups and value lookups; use quarry for "why", "how",
  and "what did we decide about X" questions.
- **Slash commands**: `/find`, `/ingest`, `/remember`, `/explain`, `/source`,
  `/quarry`
- **Research agent**: `researcher` — combines quarry local search with web
  research. Use for deep investigation across local docs and the web.
- **Auto-behaviors**: working directory is auto-indexed at session start;
  URLs fetched via WebFetch are auto-ingested; transcripts are captured before
  context compaction.
- **Search tip**: natural language queries work best ("What were Q3 margins?"
  outperforms "Q3 margins").
"""

# The legacy marker block quarry appended into a repo CLAUDE.md before the
# @-import model (retired in this release, forward-integration, no shim). The
# migration strips it on first enable, preserving every other byte.
_LEGACY_BEGIN = "<!-- quarry:begin -->"
_LEGACY_END = "<!-- quarry:end -->"


@final
class Guidance:
    """Own quarry's repo user-guide file and the migration off the legacy block.

    Two responsibilities over one repo:

    * :meth:`deposit` writes ``<repo>/.punt-labs/quarry/CLAUDE.md`` wholesale —
      the vendored zone (punt-labs-dir.md § 7), overwritten on every enable so
      the same tool version always produces identical output.
    * :meth:`strip_legacy_block` removes the retired ``quarry:begin`` /
      ``quarry:end`` marker block from ``<repo>/CLAUDE.md`` on first enable,
      under the same exclusive lock as the import-line write (§ 2.4), leaving
      the user's prose byte-for-byte intact.
    """

    __slots__ = ("_root",)

    _root: Path

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._root = root
        return self

    @property
    def guide_path(self) -> Path:
        """Return the deposited guide's path under the tool subtree."""
        return self._root / ".punt-labs" / "quarry" / "CLAUDE.md"

    def deposit(self) -> None:
        """Write the vendored guide wholesale (creating parents as needed)."""
        AtomicFile(self.guide_path).replace(_GUIDE)

    def strip_legacy_block(self) -> bool:
        """Remove the legacy ``quarry:begin``/``end`` block; return whether removed.

        Idempotent and prose-preserving: a repo CLAUDE.md with no legacy block
        (or no file at all) is left untouched. Both markers must be present, in
        order, for a removal — a lone marker is treated as user content, not a
        partial block to guess at.

        The removal is line-based (drop the marker lines and everything between,
        with their terminators) rather than a regex over the raw text, so the
        surrounding prose survives byte-for-byte across LF, CRLF, and lone-CR — a
        naive ``\\n?`` regex would split a preceding CRLF into a lone CR.
        """
        host = self._root / "CLAUDE.md"
        with FileLock(host):
            file = AtomicFile(host)
            lines = file.read().splitlines(keepends=True)
            span = self._legacy_span(lines)
            if span is None:
                return False
            begin, end = span
            file.replace("".join(lines[:begin] + lines[end + 1 :]))
            return True

    @staticmethod
    def _legacy_span(lines: list[str]) -> tuple[int, int] | None:
        """Return the inclusive ``(begin, end)`` line span of the legacy block.

        ``None`` when the begin marker is absent, or no end marker follows it.
        Markers are matched net of their terminator so a CRLF host matches too.
        """
        begin: int | None = None
        for i, raw in enumerate(lines):
            body = raw.rstrip("\r\n")
            if begin is None and body == _LEGACY_BEGIN:
                begin = i
            elif begin is not None and body == _LEGACY_END:
                return begin, i
        return None
