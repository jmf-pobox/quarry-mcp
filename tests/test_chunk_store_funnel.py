"""Tests for quarry.ingestion.chunk_store_funnel — the DES-036 convergence point.

These exercise ``_chunk_embed_store`` directly, closing the coverage gap where
it was previously only reached transitively through ``ingest_document`` /
``ingest_content`` in ``test_pipeline.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import numpy as np

from quarry.config import Settings
from quarry.db import Database
from quarry.ingestion.chunk_store_funnel import _chunk_embed_store
from quarry.ingestion.extracted_document import ExtractedDocument
from quarry.ingestion.ingest_context import IngestContext, Progress
from quarry.ingestion.ingest_stats import IngestStats
from quarry.models import Chunk, PageContent, PageType

if TYPE_CHECKING:
    import pytest

_PROGRESS = Progress(None)


def _settings() -> Settings:
    return Settings()


def _page() -> PageContent:
    return PageContent(
        document_name="doc.txt",
        document_path="/doc.txt",
        page_number=1,
        total_pages=1,
        text="hello",
        page_type=PageType.TEXT,
    )


def _extracted(*, stats: IngestStats | None = None) -> ExtractedDocument:
    return ExtractedDocument(
        pages=[_page()], stats=stats or IngestStats(), source_format=".txt"
    )


def _chunk() -> Chunk:
    return Chunk(
        document_name="doc.txt",
        document_path="/doc.txt",
        collection="default",
        page_number=1,
        total_pages=1,
        chunk_index=0,
        text="hello",
        page_raw_text="hello",
        page_type="text",
        source_format=".txt",
        ingestion_timestamp=datetime.now(tz=UTC),
    )


def _context(*, overwrite: bool = False) -> IngestContext:
    return IngestContext(Database(MagicMock()), _settings(), overwrite=overwrite)


def _mock_embedding_backend(
    monkeypatch: pytest.MonkeyPatch, vectors: np.ndarray
) -> None:
    backend = MagicMock()
    backend.embed_texts.return_value = vectors
    backend.model_name = "test-model"
    monkeypatch.setattr(
        "quarry.ingestion.streaming.get_embedding_backend", lambda _settings: backend
    )


class TestEmptyChunksFailClosed:
    def test_zero_chunks_skips_delete_and_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "quarry.ingestion.streaming.chunk_pages",
            lambda _pages, max_chars, overlap_chars, **_kw: [],
        )
        deleted: list[str] = []
        monkeypatch.setattr(
            "quarry.db.chunk_store.ChunkStore.delete_document",
            lambda _self, name, **_kw: deleted.append(name),
        )

        result = _chunk_embed_store(
            _extracted(), "doc.txt", _PROGRESS, _context(overwrite=True)
        )

        assert deleted == []
        assert result["chunks"] == 0


class TestNonEmptyChunksStore:
    def test_overwrite_deletes_before_storing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "quarry.ingestion.streaming.chunk_pages",
            lambda _pages, max_chars, overlap_chars, **_kw: [_chunk()],
        )
        _mock_embedding_backend(monkeypatch, np.zeros((1, 768), dtype=np.float32))
        monkeypatch.setattr(
            "quarry.db.chunk_store.ChunkStore.insert_records",
            lambda _self, records: len(records),
        )
        deleted: list[str] = []
        monkeypatch.setattr(
            "quarry.db.chunk_store.ChunkStore.delete_document",
            lambda _self, name, **_kw: deleted.append(name),
        )

        result = _chunk_embed_store(
            _extracted(), "doc.txt", _PROGRESS, _context(overwrite=True)
        )

        assert deleted == ["doc.txt"]
        assert result["chunks"] == 1

    def test_no_overwrite_skips_delete(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "quarry.ingestion.streaming.chunk_pages",
            lambda _pages, max_chars, overlap_chars, **_kw: [_chunk()],
        )
        _mock_embedding_backend(monkeypatch, np.zeros((1, 768), dtype=np.float32))
        monkeypatch.setattr(
            "quarry.db.chunk_store.ChunkStore.insert_records",
            lambda _self, records: len(records),
        )
        deleted: list[str] = []
        monkeypatch.setattr(
            "quarry.db.chunk_store.ChunkStore.delete_document",
            lambda _self, name, **_kw: deleted.append(name),
        )

        result = _chunk_embed_store(_extracted(), "doc.txt", _PROGRESS, _context())

        assert deleted == []
        assert result["chunks"] == 1


class TestStatsMergedIntoResult:
    def test_stats_fields_appear_in_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "quarry.ingestion.streaming.chunk_pages",
            lambda _pages, max_chars, overlap_chars, **_kw: [],
        )

        stats = IngestStats(total_pages=1, text_pages=1, image_pages=0)
        result = _chunk_embed_store(
            _extracted(stats=stats), "doc.txt", _PROGRESS, _context()
        )

        assert result.get("total_pages") == 1
        assert result.get("text_pages") == 1
        assert result.get("image_pages") == 0
        assert result["document_name"] == "doc.txt"
        assert result["collection"] == "default"


class TestProgressReporting:
    def test_progress_called_for_each_phase(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "quarry.ingestion.streaming.chunk_pages",
            lambda _pages, max_chars, overlap_chars, **_kw: [_chunk()],
        )
        _mock_embedding_backend(monkeypatch, np.zeros((1, 768), dtype=np.float32))
        monkeypatch.setattr(
            "quarry.db.chunk_store.ChunkStore.insert_records",
            lambda _self, records: len(records),
        )
        messages: list[str] = []
        progress = Progress(messages.append, log=False)

        _chunk_embed_store(_extracted(), "doc.txt", progress, _context())

        assert "Chunking" in messages
        assert any(m.startswith("Created") for m in messages)
        assert any(m.startswith("Done") for m in messages)
