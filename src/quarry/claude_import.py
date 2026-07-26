"""Add or remove one bare ``@``-import line in a ``CLAUDE.md`` host file."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from quarry.atomic_file import AtomicFile
from quarry.file_lock import FileLock

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["ClaudeMdImport"]


@final
class ClaudeMdImport:
    """Reconcile a single ``@``-import line inside a user-owned ``CLAUDE.md``.

    The only mutation any tool may make to a ``CLAUDE.md`` is to add or remove
    one bare ``@``-import line (tool-enable-disable.md § 2.1). This class owns
    exactly that mutation for one host file and one import string:

    * **Serialized** — an exclusive ``flock`` on a sibling ``.lock`` file wraps
      the whole read-modify-write, so two concurrent ``enable`` runs cannot lose
      one update (§ 2.4). The atomic rename below prevents a torn file but not a
      lost update; the lock closes that gap, which the vox reference lacks.
    * **Idempotent, terminator-insensitive** — presence is decided by matching
      the canonical line against each host line *net of its terminator*, so a
      CRLF host does not carry a spurious ``\\r`` that defeats a byte-exact
      compare. ``register`` appends only if absent; ``prune`` removes every
      match (collapsing an accidental duplicate to zero).
    * **Top-level only** — a match inside a fenced (```` ``` ````/``~~~``) or an
      indented (tab or ≥4 spaces) code block is ignored by both the presence
      scan and the removal, because Claude Code resolves ``@``-imports only at
      the top level.
    * **Byte-preserving, host EOL** — every byte outside the single import line
      is identical before and after across LF, CRLF, and lone-CR; the appended
      line uses the host file's existing EOL. Delegated to :class:`AtomicFile`.
    """

    __slots__ = ("_file",)

    _file: AtomicFile

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._file = AtomicFile(path)
        return self

    @property
    def path(self) -> Path:
        """Return the managed ``CLAUDE.md`` path."""
        return self._file.path

    def register(self, import_line: str) -> bool:
        """Append *import_line* if no top-level copy is present. Return True if written.

        Ensures separation from the user's last line: a host file not ending in
        a newline gets one (in the host EOL) before the import is appended, so
        the import is never glued to the user's prose.
        """
        self._validate_import_line(import_line)
        with FileLock(self._file.path):
            content = self._file.read()
            lines = content.splitlines(keepends=True)
            if self._matching_toplevel_indices(lines, import_line):
                return False
            eol = self._host_eol(content)
            if content and not content.endswith(("\n", "\r")):
                content += eol
            self._file.replace(content + import_line + eol)
            return True

    def prune(self, import_line: str) -> bool:
        """Remove every top-level copy of *import_line*. Return True if written.

        A copy inside a code block is left in place; only top-level imports are
        Claude Code imports, so only those are the tool's to remove.
        """
        self._validate_import_line(import_line)
        with FileLock(self._file.path):
            content = self._file.read()
            lines = content.splitlines(keepends=True)
            hits = set(self._matching_toplevel_indices(lines, import_line))
            if not hits:
                return False
            kept = [line for i, line in enumerate(lines) if i not in hits]
            self._file.replace("".join(kept))
            return True

    @staticmethod
    def _validate_import_line(import_line: str) -> None:
        """Raise ``ValueError`` unless *import_line* is a lone top-level ``@`` line.

        The line is spliced verbatim into the host file, so untrusted text is
        validated at this boundary (PY-EH-1): a padded, multi-line, or non-``@``
        line would inject a blank line, a second import, or inert markdown, and
        a padded line would never match on a later prune.
        """
        if not import_line or import_line.isspace():
            msg = "import line must be non-empty"
            raise ValueError(msg)
        if "\n" in import_line or "\r" in import_line:
            msg = f"import line must be a single line: {import_line!r}"
            raise ValueError(msg)
        if import_line != import_line.strip():
            msg = f"import line has leading/trailing whitespace: {import_line!r}"
            raise ValueError(msg)
        if not import_line.startswith("@"):
            msg = f"import line must begin with '@': {import_line!r}"
            raise ValueError(msg)

    @classmethod
    def _matching_toplevel_indices(
        cls, lines: list[str], import_line: str
    ) -> list[int]:
        """Return indices of *lines* that equal *import_line* net of terminator.

        A line inside a fenced or indented code block is never a match. Fenced
        state is tracked by counting fence delimiters (§ 2.4): a line is inside
        a fenced block when the number of preceding delimiters is odd.
        """
        hits: list[int] = []
        fence_count = 0
        for i, raw in enumerate(lines):
            body = raw.rstrip("\r\n")
            stripped = body.lstrip(" \t")
            inside_fenced = fence_count % 2 == 1
            is_fence = cls._is_fence_delimiter(stripped)
            if is_fence:
                fence_count += 1
            indented = raw.startswith(("\t", "    "))
            if inside_fenced or is_fence or indented:
                continue
            if body == import_line:
                hits.append(i)
        return hits

    @staticmethod
    def _is_fence_delimiter(stripped: str) -> bool:
        """Return whether *stripped* (leading whitespace removed) opens/closes a fence.

        A fence delimiter's first non-whitespace characters are three or more
        backticks or three or more tildes, optionally followed by an info string
        (§ 2.4) — the run need not be the whole line.
        """
        return stripped.startswith(("```", "~~~"))

    @staticmethod
    def _host_eol(content: str) -> str:
        """Return the host file's line ending: CRLF, lone CR, or LF (the default)."""
        if "\r\n" in content:
            return "\r\n"
        if "\r" in content:
            return "\r"
        return "\n"
