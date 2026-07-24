"""Tests for CollectionPurgeJob's execution-time re-check against the registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from quarry.config import Settings
from quarry.daemon.finalize_job import CollectionPurgeJob
from quarry.db import ChunkCatalog, Database
from quarry.db.storage import get_db
from quarry.ingestion.pipeline import plan_file_chunks
from quarry.sync_registry import SyncRegistry

if TYPE_CHECKING:
    from pathlib import Path

    from quarry.types import LanceDB


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        lancedb_path=tmp_path / "lancedb", registry_path=tmp_path / "registry.db"
    )


def _seed(database: Database, settings: Settings, directory: Path, doc: str) -> None:
    """Ingest one document's chunks into collection ``x`` (LanceDB only)."""
    f = directory / doc
    f.write_text("indexable body " * 20)
    chunks, _ = plan_file_chunks(f, settings, collection="x", document_name=doc)
    database.store.insert(chunks, np.zeros((len(chunks), 768), dtype=np.float32))


def _docnames(db: LanceDB) -> set[str]:
    return {d["document_name"] for d in ChunkCatalog(db).list_documents("x")}


def test_purge_skips_reregistered_collection(tmp_path: Path) -> None:
    """A purge from a STALE sweep snapshot no-ops once the collection is live again.

    Interleaving: disable X (no keep) marks X pending and its immediate purge is
    shed; a sweep snapshots X as an orphan; X is re-enabled (clears the mark, adds
    the directory row) and re-scanned (fresh chunks); THEN the stale sweep's
    CollectionPurgeJob runs. Its execution-time re-check sees X registered (and no
    longer pending) and refuses to delete — the re-ingested chunks survive.
    """
    settings = _settings(tmp_path)
    db = get_db(settings.lancedb_path)
    database = Database(db)
    dir_x = tmp_path / "x"
    dir_x.mkdir()

    conn = SyncRegistry(settings.registry_path)
    try:
        conn.register_directory(dir_x, "x")
        _seed(database, settings, dir_x, "orig.md")
        conn.deregister_directory("x")  # no keep → X marked pending, purge shed
        conn.register_directory(dir_x, "x")  # re-enable: clears mark, adds row
    finally:
        conn.close()
    _seed(database, settings, dir_x, "fresh.md")  # the re-scan's re-ingest
    before = _docnames(db)
    assert before  # fresh chunks present before the stale purge runs

    deleted = CollectionPurgeJob(database, "x", settings.registry_path)._purge()

    assert deleted == 0  # re-registered → the purge no-ops
    assert _docnames(db) == before  # chunks SURVIVE
    conn = SyncRegistry(settings.registry_path)
    try:
        assert conn.get_registration("x") is not None
    finally:
        conn.close()


def test_purge_deletes_still_pending_unregistered(tmp_path: Path) -> None:
    """The normal purge still deletes a collection that is marked and unregistered."""
    settings = _settings(tmp_path)
    db = get_db(settings.lancedb_path)
    database = Database(db)
    dir_x = tmp_path / "x"
    dir_x.mkdir()

    conn = SyncRegistry(settings.registry_path)
    try:
        conn.register_directory(dir_x, "x")
        _seed(database, settings, dir_x, "orig.md")
        conn.deregister_directory("x")  # marked pending, still unregistered
    finally:
        conn.close()
    assert _docnames(db)  # chunks present, awaiting purge

    deleted = CollectionPurgeJob(database, "x", settings.registry_path)._purge()

    assert deleted > 0  # still-pending + unregistered → deleted
    assert _docnames(db) == set()
    conn = SyncRegistry(settings.registry_path)
    try:
        assert "x" not in conn.markers.pending()  # mark cleared post-purge
    finally:
        conn.close()
