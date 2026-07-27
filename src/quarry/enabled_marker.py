"""The ``.punt-labs/quarry/enabled`` marker that signals repo enablement."""

from __future__ import annotations

import contextlib
import os
import stat
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Generator
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

    Every access is symlink-safe against an *untrusted* repo. The repo root is
    the trust anchor, but each fixed component below it (``.punt-labs``,
    ``quarry``, ``enabled``) is opened without following a symlink, so a hostile
    repo cannot redirect a create/stat/unlink to a target outside the repo — not
    via a symlinked leaf (``O_NOFOLLOW`` on the final open) and not via a
    symlinked ancestor (the ``openat`` walk in :meth:`_parent_dir_fd`).
    """

    __slots__ = ("_root",)

    _root: Path

    _RELATIVE = (".punt-labs", "quarry", "enabled")

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._root = root
        return self

    @property
    def path(self) -> Path:
        """Return the marker file path."""
        return self._root.joinpath(*self._RELATIVE)

    def is_present(self) -> bool:
        """Return whether a regular-file marker exists (quarry is enabled here).

        Resolves the parent through the ancestor-safe walk and ``lstat``\\ s the
        leaf relative to it, so neither a symlinked leaf nor a symlinked ancestor
        can let an external target spoof the enabled signal. A refused ancestor,
        a missing directory, or a non-regular leaf all read as "not enabled" —
        a query never raises.
        """
        try:
            with self._parent_dir_fd(create=False) as parent_fd:
                if parent_fd is None:
                    return False
                mode = os.lstat(self._RELATIVE[-1], dir_fd=parent_fd).st_mode
                return stat.S_ISREG(mode)
        except (OSError, ValueError):
            return False

    def write(self) -> bool:
        """Create the marker at mode ``0644`` without following any symlink.

        Returns whether the marker was created. A present regular marker is left
        untouched — no mtime bump — and ``False`` is returned, so re-enabling is
        a true idempotent no-op the caller can report as such.

        The final open uses ``O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW`` relative
        to the ancestor-verified parent fd, and ``fchmod`` sets ``0644`` on the
        descriptor independent of the umask. Two symlink boundaries are enforced:
        ``O_NOFOLLOW`` refuses a symlinked *leaf*, and :meth:`_parent_dir_fd`
        refuses a symlinked *ancestor* — together no planted symlink can make the
        create escape the repo.

        On a pre-existing entry the predicate is generalized rather than
        special-cased: only a genuine regular file is the idempotent no-op
        (return ``False``). Anything else — symlink, directory, fifo, socket,
        device — is not a valid marker, so it is refused with ``ValueError``
        rather than silently reported as "already present": a caller that read
        ``False`` as "already enabled" while :meth:`is_present` stayed ``False``
        would strand an import with no real marker (the § 2.11 forbidden state).
        """
        leaf = self._RELATIVE[-1]
        with self._parent_dir_fd(create=True) as parent_fd:
            try:
                fd = os.open(
                    leaf,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                    0o644,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                if stat.S_ISREG(os.lstat(leaf, dir_fd=parent_fd).st_mode):
                    return False
                msg = f"marker path is not a regular file: {self.path}"
                raise ValueError(msg) from None
            try:
                os.fchmod(fd, 0o644)
            finally:
                os.close(fd)
            return True

    def remove(self) -> bool:
        """Delete the marker; return whether a regular-file marker was removed.

        Acts relative to the ancestor-verified parent fd, so a symlinked ancestor
        is refused (``ValueError``) rather than followed — never an unlink that
        escapes the repo. A symlinked or otherwise non-regular *leaf* is not the
        signal quarry wrote, so it is left in place and ``False`` is returned.
        Leaves the rest of ``.punt-labs/quarry/`` intact — ``disable`` removes
        only the signal it wrote, never the dormant vendored guide (§ 2.9).
        """
        leaf = self._RELATIVE[-1]
        with self._parent_dir_fd(create=False) as parent_fd:
            if parent_fd is None:
                return False
            try:
                is_regular = stat.S_ISREG(os.lstat(leaf, dir_fd=parent_fd).st_mode)
            except FileNotFoundError:
                return False
            if not is_regular:
                return False
            os.unlink(leaf, dir_fd=parent_fd)
            return True

    @contextlib.contextmanager
    def _parent_dir_fd(self, *, create: bool) -> Generator[int | None]:
        """Yield a dir fd for the marker's parent via an ancestor-symlink-safe walk.

        Open each fixed intermediate component relative to the prior directory fd
        with ``O_DIRECTORY | O_NOFOLLOW`` (``openat`` semantics), so a symlinked
        ancestor — a hostile repo shipping ``.punt-labs`` or ``.punt-labs/quarry``
        as a link to an external directory — fails the ``O_NOFOLLOW`` open and is
        refused with ``ValueError`` before any create/stat/unlink can escape the
        repo. The caller acts on the ``enabled`` leaf relative to the yielded fd.

        The repo root is the trust anchor (opened following symlinks); only the
        components below it are pinned. Yields ``None`` when an ancestor is absent
        and *create* is False (no marker can exist); with *create* True each
        missing ancestor is created first.
        """
        if create:
            self._root.mkdir(parents=True, exist_ok=True)
        dir_fd = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for component in self._RELATIVE[:-1]:
                if create:
                    with contextlib.suppress(FileExistsError):
                        os.mkdir(component, 0o755, dir_fd=dir_fd)
                try:
                    child_fd = os.open(
                        component,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=dir_fd,
                    )
                except FileNotFoundError:
                    if create:
                        raise
                    yield None
                    return
                except OSError as exc:
                    # O_NOFOLLOW on a symlinked ancestor raises ELOOP; O_DIRECTORY
                    # on a non-directory raises ENOTDIR. Either means the fixed
                    # .punt-labs/quarry chain is not a real repo-internal
                    # directory: refuse before a create/unlink can escape.
                    msg = (
                        "refusing symlinked or non-directory ancestor of "
                        f"marker: {self.path}"
                    )
                    raise ValueError(msg) from exc
                os.close(dir_fd)
                dir_fd = child_fd
            yield dir_fd
        finally:
            os.close(dir_fd)
