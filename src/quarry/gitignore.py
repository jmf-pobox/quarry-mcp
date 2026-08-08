"""Ensure quarry's captures path is excluded from a repo's ``.gitignore``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from quarry.atomic_file import AtomicFile
from quarry.file_lock import FileLock

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["CAPTURES_GITIGNORE_ENTRY", "CapturesGitignore"]

# The path quarry's CaptureWriter writes auto-captures under (session
# transcripts, web fetches — DES-036). A repo that never excludes it can
# commit raw, unscrubbed captures the moment the redaction pipeline lags a
# new capture kind or is bypassed — the root cause of the pkit-kcps leak.
CAPTURES_GITIGNORE_ENTRY = ".punt-labs/quarry/captures/"


@final
class CapturesGitignore:
    """Own the one ``.gitignore`` line that excludes quarry's captures path.

    ``ensure`` mirrors :meth:`quarry.claude_import.ClaudeMdImport.register`:
    append the entry if no exact line is already present, no-op otherwise.
    Unlike the ``@``-import, a ``.gitignore`` has no fenced-code-block
    concept to shield against, so presence is a direct per-line match. A
    missing ``.gitignore`` is created by the same atomic write that appends
    the entry, so a repo with none yet still gets one.
    """

    __slots__ = ("_file",)

    _file: AtomicFile

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._file = AtomicFile(root / ".gitignore")
        return self

    @property
    def path(self) -> Path:
        """Return the managed ``.gitignore`` path."""
        return self._file.path

    def ensure(self) -> bool:
        """Append :data:`CAPTURES_GITIGNORE_ENTRY` if absent; return whether written.

        Idempotent: a repo that already excludes the captures path — from a
        prior ``enable`` or the user's own edit — is left byte-for-byte
        unchanged and this returns ``False``. Locked the same way
        ``ClaudeMdImport.register`` locks its host file, so two concurrent
        ``enable`` runs cannot lose one update to the other's overwrite.
        """
        with FileLock(self._file.path):
            content = self._file.read()
            lines = content.splitlines(keepends=True)
            already_present = any(
                line.rstrip("\r\n") == CAPTURES_GITIGNORE_ENTRY for line in lines
            )
            if already_present:
                return False
            eol = self._host_eol(content)
            if content and not content.endswith(("\n", "\r")):
                content += eol
            self._file.replace(content + CAPTURES_GITIGNORE_ENTRY + eol)
            return True

    @staticmethod
    def _host_eol(content: str) -> str:
        """Return the host's line ending from its FIRST newline: CRLF, lone CR, or LF.

        Mirrors :meth:`ClaudeMdImport._host_eol` — detecting the first
        terminator, not "contains anywhere", keeps a stray ``\\r`` later in the
        file from overriding a mostly-LF file's true ending.
        """
        cr = content.find("\r")
        lf = content.find("\n")
        if cr != -1 and (lf == -1 or cr < lf):
            return "\r\n" if content[cr + 1 : cr + 2] == "\n" else "\r"
        return "\n"
