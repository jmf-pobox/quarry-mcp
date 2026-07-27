"""Deposit quarry's vendored repo user-guide under the tool subtree."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from quarry.safe_paths import SafeRepoPath

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["REPO_IMPORT_LINE", "Guidance"]

_GUIDE_RELATIVE = (".punt-labs", "quarry", "CLAUDE.md")

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


@final
class Guidance:
    """Own quarry's vendored repo user-guide file.

    :meth:`deposit` writes ``<repo>/.punt-labs/quarry/CLAUDE.md`` wholesale —
    the vendored zone (punt-labs-dir.md § 7), overwritten on every enable so the
    same tool version always produces identical output.
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
        return self._root.joinpath(*_GUIDE_RELATIVE)

    def deposit(self) -> None:
        """Write the vendored guide wholesale, following no symlink.

        Routes through :class:`quarry.safe_paths.SafeRepoPath` so a hostile repo
        cannot redirect the wholesale overwrite outside the repo by planting a
        symlink at ``.punt-labs`` or ``.punt-labs/quarry``: a symlinked ancestor
        is refused, and the write lands atomically on the real in-repo guide.
        """
        SafeRepoPath(self._root, _GUIDE_RELATIVE).write_atomic(_GUIDE, mode=0o644)
