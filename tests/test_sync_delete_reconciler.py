"""Tests for DeleteReconciler: the auto-freshen prune keyed on document_path."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import numpy as np

from quarry.config import Settings
from quarry.db.chunk_catalog import ChunkCatalog
from quarry.db.chunk_store import ChunkStore
from quarry.db.storage import get_db
from quarry.ingestion.pipeline import plan_file_chunks
from quarry.sync_delete_reconciler import DeleteReconciler

if TYPE_CHECKING:
    from pathlib import Path

    from quarry.types import LanceDB

_SENTENCE = "The quick brown fox jumps over the lazy dog. "


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        lancedb_path=tmp_path / "lancedb", registry_path=tmp_path / "registry.db"
    )


def _seed(db: LanceDB, settings: Settings, file_path: Path, document_name: str) -> None:
    """Store one document whose stored document_path is *file_path*.resolve()."""
    chunks, _ = plan_file_chunks(
        file_path, settings, collection="col", document_name=document_name
    )
    ChunkStore(db).insert(chunks, np.zeros((len(chunks), 768), dtype=np.float32))


def _stale(db: LanceDB) -> list[str]:
    """Return the reconciler's prune set for an empty registry (the re-adopt path)."""
    return DeleteReconciler(db, "col").to_delete([], registry_tracked=False)


class TestStaleDocuments:
    """The prune keys on the authoritative absolute document_path, fail-safe.

    ``document_name`` is only resolved-relative for sync-ingested docs; the
    pipeline default and captures store the BASENAME. Reconstructing a path as
    ``resolved / document_name`` mislocates a nested doc and prunes a live
    document. The prune gates on the stored absolute ``document_path`` and removes
    a doc ONLY on definite absence, keeping it on any lookup error.
    """

    def test_basename_docname_not_pruned_while_on_disk(self, tmp_path: Path):
        """A nested doc stored under its BASENAME is not pruned (data-loss repro).

        ``resolved / "report.txt"`` is absent for a file at ``resolved/sub/
        report.txt``, so the old resolved-relative logic pruned this live doc.
        Keying on document_path (the real absolute location) keeps it.
        """
        settings = _settings(tmp_path)
        db = get_db(settings.lancedb_path)
        nested = tmp_path / "docs" / "sub"
        nested.mkdir(parents=True)
        f = nested / "report.txt"
        f.write_text(_SENTENCE * 3)
        _seed(db, settings, f, "report.txt")  # BASENAME, not "sub/report.txt"

        assert _stale(db) == []  # on disk → kept

    def test_unreadable_parent_not_pruned_and_no_raise(self, tmp_path: Path):
        """A doc under a chmod-0 parent is kept, and the scan does not raise.

        A lookup that cannot prove absence (PermissionError / IO error) fails
        SAFE: the document is kept and retried next sync, never pruned or raised.
        """
        settings = _settings(tmp_path)
        db = get_db(settings.lancedb_path)
        locked = tmp_path / "docs" / "locked"
        locked.mkdir(parents=True)
        f = locked / "secret.txt"
        f.write_text(_SENTENCE * 3)
        _seed(db, settings, f, "secret.txt")
        locked.chmod(0)
        try:
            stale = _stale(db)  # must not raise
        finally:
            locked.chmod(0o700)
        assert stale == []  # cannot prove absence → kept

    def test_genuinely_absent_document_is_pruned(self, tmp_path: Path):
        """A doc whose file was deleted is pruned (definite absence)."""
        settings = _settings(tmp_path)
        db = get_db(settings.lancedb_path)
        docs = tmp_path / "docs"
        docs.mkdir()
        f = docs / "gone.txt"
        f.write_text(_SENTENCE * 3)
        _seed(db, settings, f, "gone.txt")
        f.unlink()

        assert _stale(db) == ["gone.txt"]

    def test_unprovable_document_paths_are_kept(self, tmp_path: Path):
        """Only a provably-absent ABSOLUTE path is pruned; unprovable paths kept.

        A NULL Arrow ``document_path`` stringifies to ``"None"`` (not ``""``)
        through ``list_documents``; that, a blank, and a relative path are all
        non-absolute and cannot be proven absent here, so they are kept
        (fail-safe). Only the absolute path whose file is gone is pruned.
        """
        db = get_db(_settings(tmp_path).lancedb_path)
        gone = tmp_path / "gone.txt"  # absolute, absent → prune
        here = tmp_path / "here.txt"
        here.write_text("x")  # absolute, present → keep
        docs = [
            {"document_name": "null-doc", "document_path": "None"},
            {"document_name": "blank-doc", "document_path": ""},
            {"document_name": "rel-doc", "document_path": "sub/rel.txt"},
            {"document_name": "here-doc", "document_path": str(here)},
            {"document_name": "gone-doc", "document_path": str(gone)},
        ]
        with patch.object(ChunkCatalog, "list_documents", return_value=docs):
            stale = _stale(db)
        assert stale == ["gone-doc"]

    def test_registry_tracked_skips_the_scan(self, tmp_path: Path):
        """When the registry tracks files, its delta is returned unchanged."""
        db = get_db(_settings(tmp_path).lancedb_path)
        reconciler = DeleteReconciler(db, "col")
        assert reconciler.to_delete(["a.txt"], registry_tracked=True) == ["a.txt"]
