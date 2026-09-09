"""Tests for quarry.ingestion.bulk_ingest — SafeEntrySelector and BulkIngestRunner.

These give SafeEntrySelector/BulkIngestRunner direct unit coverage, closing the
gap where they were previously only reached transitively through
``ingest_sitemap``/``ingest_auto`` in ``tests/test_sitemap.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from quarry.config import Settings
from quarry.db import Database
from quarry.ingestion.bulk_ingest import (
    BulkIngestRunner,
    BulkOptions,
    SafeEntrySelector,
)
from quarry.ingestion.ingest_context import IngestContext, Progress
from quarry.sitemap import SitemapEntry

if TYPE_CHECKING:
    from quarry.ingestion.web_ingest import UrlIngest
    from quarry.results import IngestResult

_GETADDRINFO = "quarry.url_safety.socket_module.getaddrinfo"


def _addrinfo(ip: str) -> list[tuple[int, int, int, str, tuple[object, ...]]]:
    """One getaddrinfo record resolving to *ip*."""
    family = 10 if ":" in ip else 2
    sockaddr: tuple[object, ...] = (ip, 0, 0, 0) if ":" in ip else (ip, 0)
    return [(family, 1, 6, "", sockaddr)]


@pytest.fixture(autouse=True)
def _resolve_public(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve every host to a public address by default.

    ``select_safe`` delegates to ``SitemapDiscovery.select_safe``, which
    SSRF-gates each entry by resolving its host; an un-mocked test would hit
    real DNS. ``test_ssrf_gate_drops_internal_entry`` overrides this with a
    host-specific internal address.
    """
    monkeypatch.setattr(_GETADDRINFO, lambda *_a, **_k: _addrinfo("93.184.216.34"))


def _context(*, overwrite: bool = False) -> IngestContext:
    return IngestContext(Database(MagicMock()), Settings(), overwrite=overwrite)


def _existing_docs(monkeypatch: pytest.MonkeyPatch, docs: list[dict[str, str]]) -> None:
    """Stub the DB boundary ``partition`` reads for its dedup lookup."""
    monkeypatch.setattr(
        "quarry.db.chunk_catalog.ChunkCatalog.list_documents",
        lambda _self, **_kw: docs,
    )


class TestSelectSafe:
    """select_safe: glob-filter -> SSRF-gate -> cap at limit, in one lazy pass."""

    def test_include_filters_by_glob(self) -> None:
        entries = [
            SitemapEntry(loc="https://example.com/docs/a", lastmod=None),
            SitemapEntry(loc="https://example.com/blog/b", lastmod=None),
        ]
        safe = SafeEntrySelector(include=["/docs/*"]).select_safe(entries)
        assert [e.loc for e in safe] == ["https://example.com/docs/a"]

    def test_exclude_filters_by_glob(self) -> None:
        entries = [
            SitemapEntry(loc="https://example.com/docs/a", lastmod=None),
            SitemapEntry(loc="https://example.com/docs/v1/old", lastmod=None),
        ]
        safe = SafeEntrySelector(exclude=["/docs/v1/*"]).select_safe(entries)
        assert [e.loc for e in safe] == ["https://example.com/docs/a"]

    def test_ssrf_gate_drops_internal_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """select_safe's SSRF gate delegates to SitemapDiscovery.select_safe."""
        resolve = {"internal.example": "10.0.0.9"}

        def _resolver(host: str, *_a: object, **_k: object) -> object:
            return _addrinfo(resolve.get(host, "93.184.216.34"))

        monkeypatch.setattr(_GETADDRINFO, _resolver)
        entries = [
            SitemapEntry(loc="https://safe.example/a", lastmod=None),
            SitemapEntry(loc="https://internal.example/secret", lastmod=None),
        ]
        safe = SafeEntrySelector().select_safe(entries)
        assert [e.loc for e in safe] == ["https://safe.example/a"]

    def test_limit_caps_at_n_safe_entries(self) -> None:
        entries = [
            SitemapEntry(loc=f"https://example.com/{i}", lastmod=None) for i in range(5)
        ]
        safe = SafeEntrySelector(limit=2).select_safe(entries)
        assert len(safe) == 2


class TestPartition:
    """partition: dedup filtered entries against existing docs' <lastmod>."""

    def test_fresh_entry_with_no_existing_doc_goes_to_ingest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _existing_docs(monkeypatch, [])
        entries = [SitemapEntry(loc="https://example.com/new", lastmod=None)]

        to_ingest, skipped = SafeEntrySelector().partition(entries, _context())

        assert to_ingest == [("https://example.com/new", None)]
        assert skipped == 0

    def test_stale_entry_is_skipped_without_overwrite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _existing_docs(
            monkeypatch,
            [
                {
                    "document_name": "https://example.com/p",
                    "ingestion_timestamp": "2025-06-01T00:00:00+00:00",
                }
            ],
        )
        entries = [
            SitemapEntry(
                loc="https://example.com/p", lastmod=datetime(2025, 1, 1, tzinfo=UTC)
            )
        ]

        to_ingest, skipped = SafeEntrySelector().partition(entries, _context())

        assert to_ingest == []
        assert skipped == 1

    def test_overwrite_bypasses_dedup_for_a_current_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _existing_docs(
            monkeypatch,
            [
                {
                    "document_name": "https://example.com/p",
                    "ingestion_timestamp": "2025-06-01T00:00:00+00:00",
                }
            ],
        )
        entries = [
            SitemapEntry(
                loc="https://example.com/p", lastmod=datetime(2025, 1, 1, tzinfo=UTC)
            )
        ]

        to_ingest, skipped = SafeEntrySelector().partition(
            entries, _context(overwrite=True)
        )

        assert to_ingest == [("https://example.com/p", None)]
        assert skipped == 0

    def test_unparseable_stored_timestamp_forces_reingest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail-open: an unparseable stored timestamp re-ingests rather than skips."""
        _existing_docs(
            monkeypatch,
            [
                {
                    "document_name": "https://example.com/p",
                    "ingestion_timestamp": "not-a-timestamp",
                }
            ],
        )
        entries = [
            SitemapEntry(
                loc="https://example.com/p", lastmod=datetime(2025, 1, 1, tzinfo=UTC)
            )
        ]

        to_ingest, skipped = SafeEntrySelector().partition(entries, _context())

        assert to_ingest == [("https://example.com/p", None)]
        assert skipped == 0


class TestBulkIngestRunnerRun:
    """run: fan out ingest_one over a thread pool, aggregating outcomes."""

    def test_all_success_counts_every_url_ingested(self) -> None:
        def _stub(
            request: UrlIngest, _progress: Progress, _context: IngestContext
        ) -> IngestResult:
            return {"document_name": request.url, "collection": "c", "chunks": 1}

        runner = BulkIngestRunner(ingest_one=_stub, workers=2)
        to_ingest: list[tuple[str, str | None]] = [
            ("https://a.example", None),
            ("https://b.example", None),
        ]

        ingested, failed, errors = runner.run(
            to_ingest, Progress(None), _context(), BulkOptions()
        )

        assert (ingested, failed, errors) == (2, 0, [])

    def test_one_failure_is_isolated_and_its_message_captured(self) -> None:
        def _stub(
            request: UrlIngest, _progress: Progress, _context: IngestContext
        ) -> IngestResult:
            if "bad" in request.url:
                msg = "boom"
                raise ValueError(msg)
            return {"document_name": request.url, "collection": "c", "chunks": 1}

        runner = BulkIngestRunner(ingest_one=_stub, workers=2)
        to_ingest: list[tuple[str, str | None]] = [
            ("https://good.example", None),
            ("https://bad.example", None),
        ]

        ingested, failed, errors = runner.run(
            to_ingest, Progress(None), _context(), BulkOptions()
        )

        assert ingested == 1
        assert failed == 1
        assert len(errors) == 1
        assert "bad.example" in errors[0]
        assert "boom" in errors[0]

    def test_forces_overwrite_for_every_url_that_passed_dedup(self) -> None:
        """run() always replaces chunks for URLs that passed dedup (bulk_ingest.py).

        Pins the ``replace(context, overwrite=True)`` before fan-out: deleting
        that line fails no OTHER test here, but would duplicate chunks on
        every sitemap refresh.
        """
        seen_contexts: list[IngestContext] = []

        def _stub(
            request: UrlIngest, _progress: Progress, context: IngestContext
        ) -> IngestResult:
            seen_contexts.append(context)
            return {"document_name": request.url, "collection": "c", "chunks": 1}

        runner = BulkIngestRunner(ingest_one=_stub)
        to_ingest: list[tuple[str, str | None]] = [("https://a.example", None)]

        runner.run(to_ingest, Progress(None), _context(overwrite=False), BulkOptions())

        assert seen_contexts
        assert seen_contexts[0].overwrite is True

    def test_workers_do_not_receive_the_caller_callback(self) -> None:
        """Worker threads get a callback-less Progress, matching the
        pre-decomposition _bulk_ingest_entries, which never forwarded its
        progress_callback into the parallel ingest_url calls -- only this
        method's own aggregation messages used it. Sharing one
        callback-bearing Progress across threads would be a concurrency
        hazard for a stateful callback (Progress.__call__ has no lock).
        """
        seen_progress: list[Progress] = []

        def _stub(
            request: UrlIngest, progress: Progress, _context: IngestContext
        ) -> IngestResult:
            seen_progress.append(progress)
            return {"document_name": request.url, "collection": "c", "chunks": 1}

        caller_messages: list[str] = []
        caller_progress = Progress(caller_messages.append, log=False)
        runner = BulkIngestRunner(ingest_one=_stub)
        to_ingest: list[tuple[str, str | None]] = [("https://a.example", None)]

        runner.run(to_ingest, caller_progress, _context(), BulkOptions())

        assert seen_progress
        assert seen_progress[0] is not caller_progress
        # run()'s own aggregation messages ("Ingested ...") legitimately reach
        # the caller's callback; a message sent through the WORKER's Progress
        # must not -- that would mean it can still reach caller_messages.
        seen_progress[0]("worker-only message")
        assert "worker-only message" not in caller_messages

    def test_empty_to_ingest_short_circuits_without_calling_ingest_one(self) -> None:
        calls: list[UrlIngest] = []

        def _stub(
            request: UrlIngest, _progress: Progress, _context: IngestContext
        ) -> IngestResult:
            calls.append(request)
            return {"document_name": request.url, "collection": "c", "chunks": 1}

        runner = BulkIngestRunner(ingest_one=_stub)

        ingested, failed, errors = runner.run(
            [], Progress(None), _context(), BulkOptions()
        )

        assert (ingested, failed, errors) == (0, 0, [])
        assert calls == []
