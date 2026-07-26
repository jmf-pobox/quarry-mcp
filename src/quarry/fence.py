"""Track the open Markdown code fence while scanning a file's lines in order."""

from __future__ import annotations

from typing import Self, final

__all__ = ["FenceScanner"]


@final
class FenceScanner:
    """Report which lines are shielded by a Markdown code fence, line by line.

    Feed lines top to bottom to :meth:`shields`. A fence opens on a non-indented
    run of three or more backticks or three or more tildes and closes only on a
    later non-indented run of the SAME character whose length is at least the
    opener's (CommonMark §4.5). Indented lines (a tab or four or more leading
    spaces) are code-block content and never change fence state. A line is
    *shielded* when it sits inside a fence or is itself a fence delimiter — such
    a line is code, not prose, so a Claude Code ``@``-import on it is inert.
    """

    __slots__ = ("_char", "_length")

    _char: str
    _length: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._char = ""
        self._length = 0
        return self

    def shields(self, raw: str) -> bool:
        """Return whether *raw* is code, not a top-level line, advancing fence state."""
        indented = raw.startswith(("\t", "    "))
        if self._char:
            if not indented and self._closes(raw):
                self._char = ""
                self._length = 0
            return True
        if indented:
            return True
        opener = self._fence_run(raw)
        if opener is None:
            return False
        self._char, self._length = opener
        return True

    def _closes(self, raw: str) -> bool:
        """Return whether *raw* closes the open fence: same char, length >= opener."""
        run = self._fence_run(raw)
        return run is not None and run[0] == self._char and run[1] >= self._length

    @staticmethod
    def _fence_run(raw: str) -> tuple[str, int] | None:  # None: no fence run present
        """Return the ``(marker, length)`` of a leading fence run, else ``None``."""
        stripped = raw.rstrip("\r\n").lstrip(" ")
        for marker in ("`", "~"):
            run = len(stripped) - len(stripped.lstrip(marker))
            if run >= 3:
                return marker, run
        return None
