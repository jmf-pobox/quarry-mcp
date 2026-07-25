"""Derive a collection name for a directory that collides with no taken name."""

from __future__ import annotations

import hashlib
from itertools import count
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Set as AbstractSet
    from pathlib import Path


@final
class CollectionNamer:
    """Pick a unique collection name for a directory, avoiding every taken name.

    ``taken`` is the union of every name a new registration must steer clear of —
    live registrations, retained (keep-data) archives, and chunk-bearing
    collections.  Both surfaces build that set from their own source (the remote
    client from the wire ``RegistrationList``; the local hooks resolver from the
    registry + catalog) and delegate here, so the two pick identically for the
    same state (remote/local parity), and a different directory can never be
    auto-assigned a name that already holds another project's chunks.
    """

    __slots__ = ("_directory", "_taken")

    _directory: Path
    _taken: AbstractSet[str]

    def __new__(cls, directory: Path, taken: AbstractSet[str]) -> Self:
        self = super().__new__(cls)
        self._directory = directory
        self._taken = taken
        return self

    def unique(self) -> str:
        """Return the leaf name, else a parent-, hash-, or counter-disambiguated name.

        Prefers the directory's leaf name; on collision appends the parent
        directory name (``leaf-parent``), then a lengthening path-hash suffix, and
        finally a numeric counter on the full digest.  A filesystem-root directory
        has an empty ``.name``, so the leaf falls back to ``"root"`` — a collection
        is never named the empty string.  Because ``taken`` is finite and the
        counter is unbounded, unique() can never return a taken name by
        construction, even if the full digest itself is (impossibly) taken.
        """
        leaf = self._directory.name or "root"
        if leaf not in self._taken:
            return leaf
        candidate = f"{leaf}-{self._directory.parent.name or 'root'}"
        if candidate not in self._taken:
            return candidate
        digest = hashlib.sha256(str(self._directory).encode()).hexdigest()
        for length in range(8, len(digest) + 1):
            candidate = f"{leaf}-{digest[:length]}"
            if candidate not in self._taken:
                return candidate
        # Full digest exhausted (a cryptographically impossible collision): count
        # up until the name is free.  taken is finite, so next() always yields.
        return next(
            cand
            for n in count(2)
            if (cand := f"{leaf}-{digest}-{n}") not in self._taken
        )
