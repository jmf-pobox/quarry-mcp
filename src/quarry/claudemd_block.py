"""The quarry instruction block managed inside a project's CLAUDE.md."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from pathlib import Path

_BEGIN = "<!-- quarry:begin -->"
_END = "<!-- quarry:end -->"

_BODY = """\
<!-- quarry:begin -->
## Quarry

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
<!-- quarry:end -->
"""


@final
class ClaudeMdBlock:
    """Append or remove the quarry marker block in a project's ``CLAUDE.md``.

    Owns the begin/end markers and the block body, so appending and removing are
    two methods over one shared definition rather than free functions sharing
    module constants (PY-OO-7).
    """

    __slots__ = ("_begin", "_body", "_end")

    _begin: str
    _end: str
    _body: str

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._begin = _BEGIN
        self._end = _END
        self._body = _BODY
        return self

    @property
    def begin(self) -> str:
        """Return the opening marker line."""
        return self._begin

    @property
    def end(self) -> str:
        """Return the closing marker line."""
        return self._end

    @property
    def body(self) -> str:
        """Return the full marker-delimited block text."""
        return self._body

    def append_to(self, directory: Path) -> bool:
        """Append the block to ``directory/CLAUDE.md``; return whether it was added.

        Idempotent: creates the file when absent and does nothing when the block
        is already present.
        """
        claudemd = directory / "CLAUDE.md"
        if claudemd.exists():
            content = claudemd.read_text(encoding="utf-8")
            if self._begin in content:
                return False
            if content and not content.endswith("\n"):
                content += "\n"
            content += "\n" + self._body
        else:
            content = self._body
        claudemd.write_text(content, encoding="utf-8")
        return True

    def remove_from(self, directory: Path) -> bool:
        """Remove the block from ``directory/CLAUDE.md``; return whether removed.

        Deletes everything from the begin marker through the end marker inclusive
        (both must be present) and trims the trailing blank lines the removal
        leaves behind.
        """
        claudemd = directory / "CLAUDE.md"
        if not claudemd.exists():
            return False
        content = claudemd.read_text(encoding="utf-8")
        if self._begin not in content or self._end not in content:
            return False
        pattern = (
            r"\n?" + re.escape(self._begin) + r".*?" + re.escape(self._end) + r"\n?"
        )
        cleaned = re.sub(pattern, "", content, flags=re.DOTALL).rstrip() + "\n"
        claudemd.write_text(cleaned, encoding="utf-8")
        return True
