"""The ``.punt-labs/quarry/enabled`` marker that signals repo enablement."""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["EnabledMarker"]


@final
class EnabledMarker:
    """The presence marker for quarry being enabled in a repo.

    quarry is enabled in a repo when ``<repo>/.punt-labs/quarry/enabled``
    exists (tool-enable-disable.md § 2.7). ``enable`` writes it; ``disable``
    deletes it. This is a distinct signal from directory presence — the
    vendored guide persists after ``disable`` (the dormant state, § 2.9), so
    directory presence cannot mean "enabled." Both hook gates and ``punt
    audit`` read this one file. Per § 2.11 the marker is a commit point:
    :class:`quarry.enablement.Enablement` writes it only after the repo
    ``@.punt-labs/quarry/CLAUDE.md`` import is effective, so marker present ⇒
    import present. The reverse can differ mid-operation (import written, marker
    not) — the recoverable state a re-run reconciles.
    """

    __slots__ = ("_path",)

    _path: Path

    _RELATIVE = (".punt-labs", "quarry", "enabled")

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._path = root.joinpath(*cls._RELATIVE)
        return self

    @property
    def path(self) -> Path:
        """Return the marker file path."""
        return self._path

    def is_present(self) -> bool:
        """Return whether a regular-file marker exists (quarry is enabled here).

        Uses ``lstat`` and refuses to follow a final-component symlink: in an
        untrusted repo the marker path could be a planted symlink to a file
        elsewhere, and a follow would let that external target spoof the enabled
        signal. Only a genuine regular file — the shape ``write`` creates — is
        "enabled."
        """
        try:
            return stat.S_ISREG(os.lstat(self._path).st_mode)
        except OSError:
            return False

    def write(self) -> bool:
        """Create the marker at mode ``0644`` without following a symlink.

        Returns whether the marker was created. A present regular marker is left
        untouched — no mtime bump — and ``False`` is returned, so re-enabling is
        a true idempotent no-op the caller can report as such.

        ``O_CREAT | O_EXCL | O_NOFOLLOW`` is the security boundary (untrusted
        repo): ``O_EXCL`` refuses to open anything that already exists and
        ``O_NOFOLLOW`` refuses a final-component symlink, so a planted symlink
        (even a dangling one) can never make ``touch`` write *through* it to an
        arbitrary path outside the repo. ``fchmod`` on the returned descriptor
        forces ``0644`` independent of the umask — ``O_CREAT``'s mode is masked,
        so a restrictive umask would otherwise yield ``0600``. An existing
        symlink is refused with ``ValueError`` rather than followed; an existing
        regular marker is the idempotent no-op.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(
                self._path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                0o644,
            )
        except FileExistsError:
            if self._path.is_symlink():
                msg = f"refusing to follow symlink at marker path: {self._path}"
                raise ValueError(msg) from None
            return False
        try:
            os.fchmod(fd, 0o644)
        finally:
            os.close(fd)
        return True

    def remove(self) -> bool:
        """Delete the marker; return whether a regular-file marker was removed.

        Uses the same no-follow presence check as :meth:`write`: a symlink at
        the marker path is not the signal quarry wrote, so it is left untouched
        rather than followed or unlinked. Leaves the rest of
        ``.punt-labs/quarry/`` in place — ``disable`` removes only the signal it
        wrote, never the dormant vendored guide (§ 2.9).
        """
        if not self.is_present():
            return False
        self._path.unlink()
        return True
