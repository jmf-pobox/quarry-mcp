"""Symlink-safe writes to a fixed path under an untrusted repository root."""

from __future__ import annotations

import contextlib
import os
import secrets
import stat
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence
    from pathlib import Path

__all__ = ["SafeRepoPath"]


@final
class SafeRepoPath:
    """A fixed path under a repo root, written without following any symlink.

    Every writer under an untrusted repo's ``.punt-labs/quarry/`` tree (the
    ``enabled`` marker, the vendored guide, ``config.md``) routes through this
    one primitive so the symlink-safe walk lives in a single place. The repo
    root is the trust anchor; each component below it — every ancestor directory
    and the leaf — is opened with ``O_NOFOLLOW`` via an ``openat`` walk relative
    to the prior directory fd. A hostile repo therefore cannot redirect a
    create, overwrite, stat, or unlink to a target outside the repo by planting
    a symlink at any component: a symlinked ancestor fails the ``O_DIRECTORY |
    O_NOFOLLOW`` open, and a symlinked leaf fails the ``O_NOFOLLOW`` create.
    Because the fds pin the real inode chain, the walk is free of the
    resolve-then-act TOCTOU a realpath-containment check would carry.
    """

    __slots__ = ("_relative", "_root")

    _root: Path
    _relative: tuple[str, ...]

    def __new__(cls, root: Path, relative: Sequence[str]) -> Self:
        self = super().__new__(cls)
        self._root = root
        self._relative = tuple(relative)
        return self

    @property
    def path(self) -> Path:
        """Return the full path (the root joined with the relative components)."""
        return self._root.joinpath(*self._relative)

    def is_regular_file(self) -> bool:
        """Return whether the leaf is a regular file, following no symlink.

        A symlinked ancestor, a missing directory, or a non-regular leaf all
        read as absent — this query never raises or escapes the repo.
        """
        leaf = self._relative[-1]
        try:
            with self._parent_fd(create=False) as parent_fd:
                return stat.S_ISREG(os.lstat(leaf, dir_fd=parent_fd).st_mode)
        except (OSError, ValueError):
            return False

    def create_exclusive(self, text: str, *, mode: int) -> bool:
        """Create the leaf with *text* at *mode*; return whether it was created.

        Uses ``O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW`` relative to the
        ancestor-verified parent fd, so neither a symlinked ancestor nor a
        symlinked leaf can redirect the create outside the repo. An existing
        regular file is the idempotent no-op (return ``False``); any other
        existing entry — symlink, directory, fifo, socket, device — is refused
        with ``ValueError`` rather than silently reported as already present.
        """
        leaf = self._relative[-1]
        with self._parent_fd(create=True) as parent_fd:
            try:
                fd = os.open(
                    leaf,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                    mode,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                if stat.S_ISREG(os.lstat(leaf, dir_fd=parent_fd).st_mode):
                    return False
                msg = f"path is not a regular file: {self.path}"
                raise ValueError(msg) from None
            try:
                self._fill_and_close(fd, text, mode)
            except BaseException:
                # A write/fsync/fchmod failure leaves the just-created leaf on
                # disk; unlink it so the next create_exclusive does not see an
                # "existing regular file" and skip as a no-op, stranding the
                # retry with a truncated marker or config. Mirrors write_atomic.
                with contextlib.suppress(OSError):
                    os.unlink(leaf, dir_fd=parent_fd)
                raise
            return True

    def write_atomic(self, text: str, *, mode: int) -> None:
        """Overwrite the leaf atomically with *text*, following no symlink.

        Create a temp file with ``O_EXCL | O_NOFOLLOW`` in the ancestor-verified
        parent, ``fsync`` it, then ``os.replace`` it over the leaf — every step
        relative to the parent fd, so no ancestor or leaf symlink is traversed.
        The rename is atomic, so an interrupted write leaves the previous guide
        intact rather than truncated; the temp is removed on any failure.
        """
        leaf = self._relative[-1]
        tmp = f".{leaf}.{secrets.token_hex(8)}.tmp"
        with self._parent_fd(create=True) as parent_fd:
            fd = os.open(
                tmp,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                mode,
                dir_fd=parent_fd,
            )
            try:
                self._fill_and_close(fd, text, mode)
                os.replace(tmp, leaf, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp, dir_fd=parent_fd)
                raise

    def remove(self) -> bool:
        """Unlink the leaf when it is a regular file; return whether one was removed.

        Acts relative to the ancestor-verified parent fd, so a symlinked ancestor
        is refused (``ValueError``) rather than followed — never an unlink that
        escapes the repo. A missing ancestor or leaf, or a non-regular leaf,
        returns ``False`` (nothing of ours to remove).
        """
        leaf = self._relative[-1]
        try:
            with self._parent_fd(create=False) as parent_fd:
                if not stat.S_ISREG(os.lstat(leaf, dir_fd=parent_fd).st_mode):
                    return False
                os.unlink(leaf, dir_fd=parent_fd)
                return True
        except FileNotFoundError:
            return False

    @staticmethod
    def _fill_and_close(fd: int, text: str, mode: int) -> None:
        """Write *text* to *fd*, fsync, force *mode*, and close it on every path.

        Takes ownership of *fd*: if ``fdopen`` raises before owning it, the raw
        fd is closed here; otherwise the handle's ``with`` closes it. ``fchmod``
        forces *mode* on the descriptor (``O_CREAT``'s mode is umask-masked).
        """
        try:
            handle = os.fdopen(fd, "w", encoding="utf-8")
        except BaseException:
            os.close(fd)
            raise
        with handle:
            if text:
                handle.write(text)
                handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), mode)

    @contextlib.contextmanager
    def _parent_fd(self, *, create: bool) -> Generator[int]:
        """Yield a dir fd for the leaf's parent via an ancestor-symlink-safe walk.

        Open each ancestor component with ``O_DIRECTORY | O_NOFOLLOW`` relative
        to the prior directory fd (``openat`` semantics). A symlinked or
        non-directory ancestor fails the open and is refused with ``ValueError``;
        an absent ancestor propagates ``FileNotFoundError`` (the read callers
        read that as "nothing here"). With *create* True each missing ancestor
        is made first, and the root (the trust anchor, followed) is created too.
        The fd is always closed, on every path.
        """
        if create:
            self._root.mkdir(parents=True, exist_ok=True)
        dir_fd = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for component in self._relative[:-1]:
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
                    # Absent ancestor — not a symlink violation; let the read
                    # callers treat it as "nothing here."
                    raise
                except OSError as exc:
                    # O_NOFOLLOW on a symlinked ancestor raises ELOOP;
                    # O_DIRECTORY on a non-directory raises ENOTDIR. Either means
                    # the chain is not the real repo-internal directory we
                    # require: refuse before any create/stat/unlink escapes.
                    msg = f"refusing symlinked or non-directory ancestor of {self.path}"
                    raise ValueError(msg) from exc
                os.close(dir_fd)
                dir_fd = child_fd
            yield dir_fd
        finally:
            os.close(dir_fd)
