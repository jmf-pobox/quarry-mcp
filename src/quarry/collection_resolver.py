"""Registry-backed resolution of the collection a directory maps to."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from quarry.sync_registry import SyncRegistry


@final
class CollectionResolver:
    """Resolve the collection a directory maps to, over an open sync registry.

    Bundles the (registry, directory) resolution policy the session-start hook
    applies: the collection covering a cwd, the archive a directory owns (the
    re-adopt lookup), and a fresh unique name that avoids both live and archived
    names.  These three share the same registry + directory vocabulary, so they
    are methods on one resolver rather than free functions (PY-OO-7).  The
    hooks-side counterpart of the client's ``Registrations`` view.
    """

    __slots__ = ("_conn",)

    _conn: SyncRegistry

    def __new__(cls, conn: SyncRegistry) -> Self:
        self = super().__new__(cls)
        self._conn = conn
        return self

    def covering_collection(self, cwd: str) -> str | None:
        """Return the registered collection covering *cwd* (exact or parent), else None.

        Walks up from *cwd* to the filesystem root; None means no registration
        covers it — the documented "no coverage" contract, not a failure.
        """
        reg_map = {r.directory: r.collection for r in self._conn.list_registrations()}
        if not reg_map:
            return None
        current = Path(cwd).resolve()
        while True:
            found = reg_map.get(str(current))
            if found is not None:
                return found
            parent = current.parent
            if parent == current:
                return None
            current = parent

    def archived_collection_for(self, directory: Path) -> str | None:
        """Return the archived (keep-data) collection *directory* owns, else None.

        The same directory-identity re-adopt policy ``quarry enable`` applies over
        the wire (``Registrations.archived_collection_for``), here over the
        registry's ``retained_markers``.  A legacy blank-origin marker matches no
        resolved directory and is never re-adopted.  None is the "this directory
        owns no archive" contract.
        """
        target = str(directory.resolve())
        return next(
            (
                m.collection
                for m in self._conn.markers.retained_markers()
                if m.original_directory == target
            ),
            None,
        )

    def unique_collection_name(self, directory: Path) -> str:
        """Derive a collection name colliding with no live OR archived collection.

        Prefers ``directory.name``.  If that's taken — by a live registration or a
        keep-data ``retained`` marker — appends the parent directory name
        (``leaf-parent``), then a path-hash suffix.  Avoiding archived names keeps
        an unrelated directory from silently inheriting another project's kept
        chunks (and from tripping ``register_directory``'s identity guard).
        """
        retained = set(self._conn.markers.list_retained())

        def _available(name: str) -> bool:
            return self._conn.get_registration(name) is None and name not in retained

        # A filesystem-root directory has an empty ``.name``; fall back to "root"
        # so a collection is never registered under an empty name.
        leaf = directory.name or "root"
        if _available(leaf):
            return leaf
        parent = directory.parent.name or "root"
        candidate = f"{leaf}-{parent}"
        if _available(candidate):
            return candidate
        suffix = hashlib.sha256(str(directory).encode()).hexdigest()[:8]
        return f"{leaf}-{suffix}"
