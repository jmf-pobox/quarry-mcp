"""Compute the disk-vs-registry sync plan for one collection, TOCTOU-resilient.

``SyncPlanner`` walks the files discovered under a registered directory and
compares each against the sync registry to bucket it into ingest / refresh /
delete / unchanged.  Every filesystem touch here is hardened against the races
the reconcile actually hits in production:

- a file present at ``discover()`` time but gone at its ``stat()`` turn is a
  DELETE event (routed into ``to_delete``), never a crash of the whole scan;
- a file present but unreadable is skipped and retried next scan (its indexed
  chunks are preserved — the fail-safe);
- a whole-collection delete is REFUSED when the root itself could not be
  resolved (fail-closed): an empty discovery from an unresolvable root must not
  read as "every registered file was deleted" and wipe the collection.

Extracting this from :mod:`quarry.sync` keeps the plan logic — the one place in
the reconcile that stats every file — in a single tested class with a natural
home (``_stat_or_skip``) for the per-file guard.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from quarry.sync_discovery import FileDiscovery

if TYPE_CHECKING:
    from pathlib import Path

    from quarry.sync_file_store import FileRecord
    from quarry.sync_registry import SyncRegistry

logger = logging.getLogger(__name__)


@final
@dataclass(frozen=True, slots=True)
class SyncPlan:
    to_ingest: list[Path]
    to_refresh: list[tuple[Path, str]]
    to_delete: list[str]
    unchanged: int
    # True iff the registry held any file row for the collection (bool(known_files));
    # False when it holds none -- a re-adopt (keep-data disable deleted them) or a
    # never-indexed first sync -- so DeleteReconciler runs the LanceDB-vs-disk prune.
    registry_tracked: bool


@final
class SyncPlanner:
    """Bucket a collection's discovered files against its registry rows.

    One planner serves one ``compute``: it owns the discovery, the collection,
    the registry connection, and the extension filter, so the per-file guard and
    the fail-closed delete rule live as methods rather than free helpers.
    """

    __slots__ = ("_collection", "_conn", "_discovery", "_extensions")

    _discovery: FileDiscovery
    _collection: str
    _conn: SyncRegistry
    _extensions: frozenset[str]

    def __new__(
        cls,
        directory: Path,
        collection: str,
        conn: SyncRegistry,
        extensions: frozenset[str],
    ) -> Self:
        self = super().__new__(cls)
        self._discovery = FileDiscovery(directory)
        self._collection = collection
        self._conn = conn
        self._extensions = extensions
        return self

    def compute(self) -> SyncPlan:
        """Compare files on disk against the registry to produce a sync plan.

        Buckets each discovered file:

        - ``to_ingest``: new files, size mismatches, files whose content hash
          changed, or files with a partial resume watermark (mid-file, DES-034).
        - ``to_refresh``: files whose ``(mtime, size)`` shifted but whose content
          hash still matches — only the registry row is updated.
        - ``to_delete``: ``document_name``s present in the registry but no longer
          on disk (or vanished mid-scan).
        - ``unchanged``: files with identical ``(mtime, size)``.

        Fail-safe rules: size mismatch, missing stored hash, or hash read errors
        all fall through to ``to_ingest``; a vanished file is dropped from
        ``disk_paths`` so it reconciles into ``to_delete``.
        """
        disk_files = self._discovery.discover(self._extensions)
        disk_paths = {str(p) for p in disk_files}
        known_files = {r.path: r for r in self._conn.files.list_files(self._collection)}

        to_ingest, to_refresh, unchanged = self._categorize(
            disk_files, disk_paths, known_files
        )
        return SyncPlan(
            to_ingest=to_ingest,
            to_refresh=to_refresh,
            to_delete=self._deletions(disk_paths, known_files),
            unchanged=unchanged,
            registry_tracked=bool(known_files),
        )

    def _categorize(
        self,
        disk_files: list[Path],
        disk_paths: set[str],
        known_files: dict[str, FileRecord],
    ) -> tuple[list[Path], list[tuple[Path, str]], int]:
        """Split discovered files into ingest / refresh / unchanged buckets.

        Mutates *disk_paths*: a file that vanished between discovery and its
        ``stat()`` is discarded so :meth:`_deletions` reconciles it away.
        """
        to_ingest: list[Path] = []
        to_refresh: list[tuple[Path, str]] = []
        unchanged = 0
        for file_path in disk_files:
            stat = self._stat_or_skip(file_path, disk_paths)
            if stat is None:
                continue
            record = known_files.get(str(file_path))
            if record is None or record.is_partial:
                to_ingest.append(file_path)
                continue
            if record.mtime == stat.st_mtime and record.size == stat.st_size:
                unchanged += 1
                continue
            refresh = self._refresh_hash(file_path, record, stat)
            if refresh is not None:
                to_refresh.append((file_path, refresh))
            else:
                to_ingest.append(file_path)
        return to_ingest, to_refresh, unchanged

    @staticmethod
    def _stat_or_skip(file_path: Path, disk_paths: set[str]) -> os.stat_result | None:
        """Stat *file_path*, or return ``None`` when it should be skipped this scan.

        A file discovered by ``os.walk`` can be gone or unreadable by the time
        this stats it (TOCTOU). ``FileNotFoundError``/``NotADirectoryError`` mean
        it vanished — drop it from *disk_paths* so it reconciles into
        ``to_delete``. Any other ``OSError`` (permission, ``EIO``, ``ENOSPC``…)
        means present-but-unreadable — keep it in *disk_paths* (its chunks and
        row survive) and retry next scan. Either way one file never aborts the
        whole collection's scan.
        """
        try:
            return file_path.stat()
        except (FileNotFoundError, NotADirectoryError):
            disk_paths.discard(str(file_path))
            return None
        except OSError as exc:
            logger.warning(
                "Skipping unreadable file in sync plan: %s: %s", file_path, exc
            )
            return None

    def _deletions(
        self, disk_paths: set[str], known_files: dict[str, FileRecord]
    ) -> list[str]:
        """Registry documents whose path is no longer on disk.

        Fail-closed: when the root could not be resolved (a transient NFS/SMB
        blip, ``ESTALE``, a momentary permission loss on the root), ``discover()``
        returns empty for a reason OTHER than deletion. Producing deletions here
        would treat every registered file as gone and wipe the whole collection,
        which is strictly worse than skipping this scan. So when the root is not
        available, delete nothing and retry next scan. A legitimately empty
        directory (root available, nothing discovered) still deletes correctly.
        """
        if not self._discovery.root_available:
            logger.warning(
                "Sync plan: root unavailable for %s — skipping deletions this scan",
                self._collection,
            )
            return []
        return [
            r.document_name for r in known_files.values() if r.path not in disk_paths
        ]

    @staticmethod
    def _refresh_hash(
        file_path: Path, record: FileRecord, stat: os.stat_result
    ) -> str | None:
        """Return the disk hash when *file_path* is an unchanged refresh, else None.

        A refresh means ``(mtime, size)`` shifted but the content hash still
        matches the stored value, so only the registry row needs updating —
        LanceDB is left alone. Missing stored hash, size mismatch, or a hash read
        error all decline.
        """
        if record.content_hash is None or record.size != stat.st_size:
            return None
        try:
            disk_hash = FileDiscovery.content_hash(file_path)
        except OSError:
            return None
        return disk_hash if disk_hash == record.content_hash else None
