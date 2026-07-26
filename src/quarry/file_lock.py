"""An exclusive advisory lock over a sibling lock file, for one host mutation."""

from __future__ import annotations

import contextlib
import fcntl
import os
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

__all__ = ["FileLock"]


@final
class FileLock:
    """Hold an exclusive ``flock`` on a sibling lock file for one read-modify-write.

    Every shared host-file mutation in tool-enable-disable.md § 2.4 — the
    ``CLAUDE.md`` import line and the legacy-block strip both — is a
    read-modify-write on a file other tools and invocations also touch. Atomic
    rename prevents a torn file but not a lost update: two parallel ``enable``
    runs each read the old bytes, write their change, and rename, and the second
    silently clobbers the first. This lock serializes them.

    The lock file lives beside its target (``.CLAUDE.md.lock`` next to
    ``CLAUDE.md``) so it shares the directory the atomic rename needs anyway,
    and is created — never removed — so a waiter and a holder always ``flock``
    the same inode.
    """

    __slots__ = ("_fd", "_lock_path")

    _lock_path: Path
    _fd: int

    def __new__(cls, target: Path) -> Self:
        self = super().__new__(cls)
        self._lock_path = target.parent / f".{target.name}.lock"
        self._fd = -1
        return self

    def __enter__(self) -> Self:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # flock releases on close; unlock first so a waiter wakes even if the
        # interpreter delays the close. Suppress an unlock error so the real
        # exception (if any) from the body propagates unmasked.
        with contextlib.suppress(OSError):
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)
        self._fd = -1
