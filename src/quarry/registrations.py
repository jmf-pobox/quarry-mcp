"""Client-side coverage queries over the daemon's authoritative registration list.

``enable``/``disable`` decide reuse-vs-register and the parent-coverage guard from
the daemon's ``RegistrationList`` (read over the wire), never a local
``SyncRegistry`` — the daemon owns the registry (DES-031 I2), so a client cannot
authorize a mutation from a divergent local copy.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from quarry.api import RegistrationInfo, RegistrationList, RetainedCollection


@final
class Registrations:
    """A read-only view over the daemon's registrations for coverage queries."""

    __slots__ = ("_archived_by_dir", "_by_dir", "_taken")

    # wire boundary — the daemon's registrations keyed by their absolute directory.
    _by_dir: dict[str, RegistrationInfo]
    # Collection names a new registration must avoid: live names PLUS archived
    # (retained/keep-data) names, so an unrelated directory never re-uses an
    # archived collection and silently inherits its chunks.
    _taken: frozenset[str]
    # Archived collections keyed by the directory they were kept from, so the
    # SAME directory re-enabling re-adopts its own kept chunks by name.
    _archived_by_dir: dict[str, str]

    def __new__(
        cls,
        registrations: Sequence[RegistrationInfo],
        retained: Sequence[RetainedCollection] = (),
    ) -> Self:
        self = super().__new__(cls)
        self._by_dir = {r.directory: r for r in registrations}
        self._taken = frozenset(r.collection for r in registrations) | frozenset(
            m.collection for m in retained
        )
        # An empty original_directory (legacy marker) is dropped: it matches no
        # resolved path, so a legacy archive is avoided by name but never adopted.
        # Iterate REVERSED so the first marker wins on a duplicate original_directory
        # (a forward dict comprehension is last-wins) — matching the daemon
        # resolver's next() over collection-ordered markers, so local == remote.
        self._archived_by_dir = {
            m.original_directory: m.collection
            for m in reversed(retained)
            if m.original_directory
        }
        return self

    @classmethod
    def from_list(cls, listing: RegistrationList) -> Self:
        """Build a view from the daemon's list response, carrying retained markers."""
        return cls(listing.registrations, listing.retained)

    def archived_collection_for(self, directory: Path) -> str | None:
        """Return the archived collection *directory* itself owns, or None.

        Only the directory the collection was kept from re-adopts it (reusing the
        name and its kept chunks); every other directory gets a fresh name (I7).
        None is the documented "this directory owns no archive" contract.
        """
        return self._archived_by_dir.get(str(directory.resolve()))

    def covering(self, directory: Path) -> RegistrationInfo | None:
        """Return the registration covering *directory* (exact or a parent), else None.

        None = the directory is under no registered tree — the documented
        "no coverage" contract, not a failure. Compares the resolved path against
        the daemon's absolute registration directories.
        """
        # Exact string match is correct ONLY because the daemon persists resolved
        # absolute paths (enable_project registers str(directory.resolve())). If a
        # future change stored a non-normalized path (trailing slash, unresolved
        # symlink), a real parent would be missed → a spurious "no registration
        # covers".
        current = directory.resolve()
        while True:
            found = self._by_dir.get(str(current))
            if found is not None:
                return found
            parent = current.parent
            if parent == current:
                return None
            current = parent

    def unique_collection_name(self, directory: Path) -> str:
        """Return a collection name for *directory* not colliding with an existing one.

        Avoids both live and archived (retained) names: a name kept by a prior
        keep-data disable is off-limits, so an unrelated directory never adopts an
        archived collection's chunks.  Prefers the leaf name; disambiguates with
        the parent dir name, then a path-hash suffix.  A filesystem-root directory
        has an empty ``.name``, so the leaf falls back to ``"root"`` — a collection
        is never registered with an empty name.
        """
        leaf = directory.name or "root"
        if leaf not in self._taken:
            return leaf
        parent = directory.parent.name or "root"
        candidate = f"{leaf}-{parent}"
        if candidate not in self._taken:
            return candidate
        suffix = hashlib.sha256(str(directory).encode()).hexdigest()[:8]
        return f"{leaf}-{suffix}"
