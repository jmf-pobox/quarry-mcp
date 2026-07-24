"""SQLite registry for sync: registered directories and file state."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from quarry.collection_marker_store import CollectionMarkerStore
from quarry.sync_file_store import FileStore
from quarry.sync_schema import SyncSchema


@dataclass(frozen=True, slots=True)
class DirectoryRegistration:
    directory: str
    collection: str
    registered_at: str


class SyncRegistry:
    """Manages the SQLite registry for directory registrations and markers.

    Wraps a sqlite3.Connection and exposes the directory-registration operations
    (register, deregister, list, get) plus the low-level connection interface
    (execute, commit, close). Per-file rows live in a composed :class:`FileStore`
    (:attr:`files`); the retained + pending-purge collection markers live in a
    composed :class:`CollectionMarkerStore` (:attr:`markers`).  Both share this
    connection, so a marker change and the directories-row change commit in one
    transaction — atomic together.
    """

    _conn: sqlite3.Connection
    _files: FileStore
    _markers: CollectionMarkerStore

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the connection is written only from the calling
        # thread (never from ThreadPoolExecutor workers) but is passed across
        # boundaries that include threaded code paths, so disable the affinity check.
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        try:
            self._ensure_schema()
        except Exception:
            self._conn.close()
            raise
        self._files = FileStore(self._conn)
        self._markers = CollectionMarkerStore(self._conn)
        return self

    @property
    def files(self) -> FileStore:
        """Return the per-file row store sharing this registry's connection."""
        return self._files

    @property
    def markers(self) -> CollectionMarkerStore:
        """Return the retained + pending-purge marker store on this connection."""
        return self._markers

    def _ensure_schema(self) -> None:
        """Set connection pragmas, create tables, and apply migrations."""
        self._conn.execute("PRAGMA journal_mode=WAL")
        # Wait up to 5 s for a contended write lock, not instant lock error.
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        schema = SyncSchema(self._conn)
        schema.initialize()
        schema.migrate()

    # ------------------------------------------------------------------
    # sqlite3.Connection proxy — callers may call these directly on conn
    # ------------------------------------------------------------------

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> sqlite3.Cursor:
        """Execute *sql* on the underlying connection."""
        cursor: sqlite3.Cursor = self._conn.execute(sql, parameters)
        return cursor

    def executescript(self, sql_script: str) -> sqlite3.Cursor:
        """Execute *sql_script* via the underlying connection."""
        cursor: sqlite3.Cursor = self._conn.executescript(sql_script)
        return cursor

    def commit(self) -> None:
        """Commit the current transaction."""
        self._conn.commit()

    def rollback(self) -> None:
        """Roll back the current transaction."""
        self._conn.rollback()

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Registry operations
    # ------------------------------------------------------------------

    def register_directory(
        self,
        directory: Path,
        collection: str,
    ) -> tuple[DirectoryRegistration, list[str]]:
        """Register a directory for incremental sync.

        Subsumption rules:

        - If *directory* is an ancestor of existing registrations, the children
          are deregistered (the parent subsumes them).
        - If an existing registration is an ancestor of *directory*, the
          registration is rejected — the child is already covered.

        Return the new registration and the collections it subsumed, so the
        caller can tear down each subsumed child's watch and purge its chunks
        (whose ``directories`` row this call just deleted).  The list is empty
        unless *directory* was a parent of existing registrations.

        Raises:
            FileNotFoundError: If *directory* does not exist.
            ValueError: If *directory* is already registered, *collection*
                name is already in use, or *directory* is a child of an
                existing registration.
        """
        resolved = directory.resolve()
        if not resolved.is_dir():
            msg = f"Directory not found: {resolved}"
            raise FileNotFoundError(msg)

        # Guard BEFORE any mutation so a rejection leaves the registry untouched.
        self._guard_retained_identity(resolved, collection)
        subsumed = self._enforce_subsumption(resolved)

        now = datetime.now(UTC).isoformat()
        try:
            self._conn.execute(
                "INSERT INTO directories (directory, collection, registered_at) "
                "VALUES (?, ?, ?)",
                (str(resolved), collection, now),
            )
            # The guard proved any surviving marker is this same directory's, so
            # re-registering re-adopts its kept chunks: drop the retained marker to
            # make the collection live again, and drop any pending-purge marker so
            # the orphan sweep cannot delete the now-live collection's chunks. Both
            # execute on this connection, committing with the INSERT above.
            self._markers.clear_retained(collection)
            self._markers.clear_pending(collection)
        except sqlite3.IntegrityError:
            self._raise_for_integrity(resolved, collection)
        except sqlite3.Error:
            self._conn.rollback()
            raise
        self._conn.commit()
        registration = DirectoryRegistration(
            directory=str(resolved),
            collection=collection,
            registered_at=now,
        )
        return registration, subsumed

    def _enforce_subsumption(self, resolved: Path) -> list[str]:
        """Reject child-of-parent, evict children of new parent, return them."""
        existing_regs = self.list_registrations()
        for reg in existing_regs:
            reg_path = Path(reg.directory).resolve()
            if self._is_ancestor_of(reg_path, resolved):
                msg = (
                    f"directory already covered by parent registration "
                    f"'{reg.collection}' ({reg.directory})"
                )
                raise ValueError(msg)
        # Inline the DELETE SQL instead of calling deregister_directory() so the
        # child removals and parent INSERT share one transaction — if the INSERT
        # fails, the children are preserved.
        subsumed = [
            reg.collection
            for reg in existing_regs
            if self._is_ancestor_of(resolved, Path(reg.directory).resolve())
        ]
        self._evict_subsumed(subsumed)
        return subsumed

    def _evict_subsumed(self, subsumed: list[str]) -> None:
        """Delete files/directory rows of each subsumed child and mark it for purge.

        The child's chunks are now orphaned (its directory row is gone), so mark
        it in the same transaction — the orphan sweep drains the delete even if
        the caller's immediate purge is shed or the daemon restarts first.
        """
        for child_collection in subsumed:
            self._conn.execute(
                "DELETE FROM files WHERE collection = ?", (child_collection,)
            )
            self._conn.execute(
                "DELETE FROM directories WHERE collection = ?", (child_collection,)
            )
            self._markers.mark_pending(child_collection)

    def _raise_for_integrity(self, resolved: Path, collection: str) -> None:
        """Translate an INSERT IntegrityError into a precise ValueError."""
        self._conn.rollback()
        existing = self._conn.execute(
            "SELECT directory, collection FROM directories "
            "WHERE directory = ? OR collection = ?",
            (str(resolved), collection),
        ).fetchone()
        if existing and existing[0] == str(resolved):
            msg = (
                f"Directory already registered: {resolved} (collection '{existing[1]}')"
            )
        else:
            msg = f"Collection name already in use: '{collection}'"
        raise ValueError(msg) from None

    def deregister_directory(
        self, collection: str, *, keep_data: bool = False
    ) -> list[str]:
        """Remove a directory registration and its file records.

        When *keep_data* is set, record the collection as retained IN THE SAME
        transaction as the row removal, tagged with the directory it was
        registered under, so only that same directory may later re-adopt the kept
        chunks (a different directory re-using the name is refused at register —
        see :meth:`_guard_retained_identity`).  Return the document_names of files
        that were tracked, so the caller can clean them from LanceDB.
        """
        # Capture the directory BEFORE deleting its row: the retained marker's
        # identity tag is what lets the same directory re-adopt and blocks a
        # different one from silently merging into the archived chunks.
        dir_row = self._conn.execute(
            "SELECT directory FROM directories WHERE collection = ?",
            (collection,),
        ).fetchone()
        original_directory = dir_row[0] if dir_row is not None else None
        rows = self._conn.execute(
            "SELECT DISTINCT document_name FROM files WHERE collection = ? "
            "ORDER BY document_name",
            (collection,),
        ).fetchall()
        document_names = [r[0] for r in rows]
        self._conn.execute("DELETE FROM files WHERE collection = ?", (collection,))
        self._conn.execute(
            "DELETE FROM directories WHERE collection = ?",
            (collection,),
        )
        if keep_data:
            # Retained, not purged: record the keep marker and clear any stale
            # pending-purge mark so the orphan sweep never deletes the kept chunks.
            self._markers.mark_retained(collection, original_directory)
            self._markers.clear_pending(collection)
        else:
            # Mark for purge IN THE SAME transaction as the row removal: the sweep
            # purges ONLY explicitly-marked collections, so a shed immediate purge
            # is drained on a later reconcile, surviving a restart (the closed-set
            # backstop that keeps captures/memories/remember targets unreachable).
            self._markers.mark_pending(collection)
        self._conn.commit()
        return document_names

    def _guard_retained_identity(self, resolved: Path, collection: str) -> None:
        """Refuse re-using an archived collection name from a different directory.

        A keep-data deregister archives a collection's chunks under a retained
        marker tagged with its original directory.  Only that same directory may
        re-register the name — re-adopting its own kept chunks.  A different
        directory re-using the name would silently merge two projects' data into
        one collection (the opposite of keep-data's promise), so it is refused.

        A legacy marker with no recorded origin (``original_directory`` NULL,
        written before the column existed) matches no directory and is refused for
        every directory: without a verifiable origin the safe default is to never
        merge.  Delete the archived collection, or choose another name, to proceed.
        """
        marker = self._markers.retained_marker(collection)
        if marker is None or marker.original_directory == str(resolved):
            return
        origin = marker.original_directory or "an unknown directory"
        msg = (
            f"collection {collection!r} holds archived (keep-data) chunks from "
            f"{origin}; choose a different name or delete that collection first"
        )
        raise ValueError(msg)

    def has_registrations_under(self, directory: Path) -> bool:
        """Return whether any registration's directory lies strictly under *directory*.

        Answers the auto-register subsumption guard: registering *directory* would
        subsume those children, so the caller skips auto-register rather than
        cause data loss.
        """
        resolved = directory.resolve()
        return any(
            self._is_ancestor_of(resolved, Path(reg.directory).resolve())
            for reg in self.list_registrations()
        )

    def list_registrations(self) -> list[DirectoryRegistration]:
        """Return all registered directories."""
        rows = self._conn.execute(
            "SELECT directory, collection, registered_at FROM directories "
            "ORDER BY collection"
        ).fetchall()
        return [
            DirectoryRegistration(directory=r[0], collection=r[1], registered_at=r[2])
            for r in rows
        ]

    def get_registration(self, collection: str) -> DirectoryRegistration | None:
        """Look up a single registration by collection name."""
        row = self._conn.execute(
            "SELECT directory, collection, registered_at FROM directories "
            "WHERE collection = ?",
            (collection,),
        ).fetchone()
        if row is None:
            return None
        return DirectoryRegistration(
            directory=row[0], collection=row[1], registered_at=row[2]
        )

    @staticmethod
    def _is_ancestor_of(ancestor: Path, descendant: Path) -> bool:
        """Return True if *ancestor* is a strict ancestor of *descendant*.

        Both paths should be resolved (absolute, no symlinks); strict inequality
        means a path is not its own ancestor.
        """
        return ancestor != descendant and descendant.is_relative_to(ancestor)
