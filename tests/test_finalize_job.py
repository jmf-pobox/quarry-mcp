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


def _seed_at(
    database: Database, settings: Settings, file_path: Path, document_name: str
) -> None:
    """Store one document under an explicit *document_name* at *file_path*."""
    file_path.write_text("indexable body " * 20)
    chunks, _ = plan_file_chunks(
        file_path, settings, collection="x", document_name=document_name
    )
    database.store.insert(chunks, np.zeros((len(chunks), 768), dtype=np.float32))


def test_force_purge_clean_slate_leaves_no_old_chunks(tmp_path: Path) -> None:
    """A widen-to-same-name self-subsume forces a clean-slate purge (no duplicates).

    Register the child at ``root/sub`` as "x", index a child-root-relative doc,
    then widen: register the parent ``root`` as "x" (subsumes the child, clears
    its pending mark, adds the directory row). The self-subsume teardown purge
    runs with ``force=True`` — the re-check would see "x" registered and wrongly
    skip, leaving the OLD narrower-root chunks to duplicate the fresh scan. With
    force it deletes clean, so after the re-scan only the parent-relative doc
    remains.
    """
    settings = _settings(tmp_path)
    db = get_db(settings.lancedb_path)
    database = Database(db)
    child = tmp_path / "root" / "sub"
    child.mkdir(parents=True)

    conn = SyncRegistry(settings.registry_path)
    try:
        conn.register_directory(child, "x")
        _seed_at(database, settings, child / "deep.md", "deep.md")  # child-relative
        _reg, subsumed = conn.register_directory(tmp_path / "root", "x")
        assert subsumed == ["x"]  # widening subsumed the child under the same name
    finally:
        conn.close()

    # The awaited self-subsume teardown purge — forced clean slate.
    deleted = CollectionPurgeJob(
        database, "x", settings.registry_path, force=True
    )._purge()
    assert deleted > 0  # deleted despite "x" being registered again

    _seed_at(database, settings, child / "deep.md", "sub/deep.md")  # re-scan output

    assert _docnames(db) == {"sub/deep.md"}  # exactly one set; no old "deep.md"


def test_force_bypasses_the_registered_recheck(tmp_path: Path) -> None:
    """force=True deletes even when the re-check would skip; force=False no-ops."""
    settings = _settings(tmp_path)
    db = get_db(settings.lancedb_path)
    database = Database(db)
    dir_x = tmp_path / "x"
    dir_x.mkdir()

    conn = SyncRegistry(settings.registry_path)
    try:
        conn.register_directory(dir_x, "x")  # registered → re-check would skip
        _seed(database, settings, dir_x, "orig.md")
    finally:
        conn.close()

    unforced = CollectionPurgeJob(database, "x", settings.registry_path)._purge()
    assert unforced == 0  # registered → the marker-gated purge no-ops
    assert _docnames(db)  # chunks survive

    forced = CollectionPurgeJob(
        database, "x", settings.registry_path, force=True
    )._purge()
    assert forced > 0  # force bypasses the re-check
    assert _docnames(db) == set()


def test_force_never_deletes_retained_collection(tmp_path: Path) -> None:
    """force NEVER bypasses the retained guard — keep-data chunks are absolute.

    A run_register self-subsume force purge is a 202 background task; while it is
    queued, a concurrent keep-data deregister of the same collection can mark it
    retained (an independent commit, no FIFO slot). The force purge must then
    honor that retained marker and delete nothing — retained is the one invariant
    force cannot cross, or keep-data's promise breaks.
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
        conn.deregister_directory("x", keep_data=True)  # retained, chunks kept
        assert conn.markers.list_retained() == ["x"]
    finally:
        conn.close()

    deleted = CollectionPurgeJob(
        database, "x", settings.registry_path, force=True
    )._purge()

    assert deleted == 0  # retained → force still refuses to delete
    assert _docnames(db)  # kept chunks survive
