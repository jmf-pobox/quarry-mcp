"""Non-file bulk ingest: safe entry selection, options, and threaded fan-out."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, final

from quarry.ingestion.web_ingest import UrlIngest

if TYPE_CHECKING:
    from collections.abc import Callable

    from quarry.ingestion.ingest_context import IngestContext, Progress
    from quarry.results import IngestResult
    from quarry.sitemap import SitemapEntry

logger = logging.getLogger(__name__)


@final
@dataclass(frozen=True, slots=True)
class BulkOptions:
    """Non-context knobs shared by every bulk URL ingest path."""

    workers: int = 4
    delay: float = 0.5
    timeout: int = 30
    include: list[str] | None = None
    exclude: list[str] | None = None
    limit: int = 0

    def __post_init__(self) -> None:
        """Clamp workers to at least 1 — a thread pool needs at least one worker.

        Frozen dataclasses need ``object.__setattr__`` to fix up a field after
        construction; this is the one write that bypasses immutability, and
        only to enforce the invariant, not to change caller-visible state
        after the fact.
        """
        if self.workers < 1:
            object.__setattr__(self, "workers", 1)


@final
@dataclass(frozen=True, slots=True)
class SafeEntrySelector:
    """Filters sitemap entries to a safe, capped, deduped-against-existing set."""

    include: list[str] | None = None
    exclude: list[str] | None = None
    limit: int = 0

    def select_safe(self, entries: list[SitemapEntry]) -> list[SitemapEntry]:
        """Glob-filter -> SSRF-gate -> cap at ``limit`` SAFE entries (one lazy pass)."""
        from quarry.sitemap import SitemapDiscovery  # noqa: PLC0415

        return SitemapDiscovery.select_safe(
            entries, include=self.include, exclude=self.exclude, limit=self.limit
        )

    def partition(
        self, filtered: list[SitemapEntry], context: IngestContext
    ) -> tuple[list[tuple[str, str | None]], int]:
        """Split filtered entries into ``(to_ingest, skipped_count)`` via dedup.

        Dedup compares each entry's ``<lastmod>`` against the stored ingestion
        timestamp of the same document in *context*'s collection.
        """
        existing_docs = context.database.catalog.list_documents(
            collection_filter=context.collection
        )
        existing_timestamps: dict[str, str] = {
            doc["document_name"]: doc["ingestion_timestamp"] for doc in existing_docs
        }
        to_ingest: list[tuple[str, str | None]] = []
        skipped = 0
        for entry in filtered:
            existing_ts = existing_timestamps.get(entry.loc)
            if (
                existing_ts
                and not context.overwrite
                and entry.lastmod is not None
                and self._entry_is_current(existing_ts, entry.lastmod)
            ):
                skipped += 1
                continue
            to_ingest.append((entry.loc, None))
        return to_ingest, skipped

    @staticmethod
    def _entry_is_current(existing_ts: str, lastmod: datetime) -> bool:
        """Return True if *lastmod* is not newer than the stored *existing_ts*.

        An unparseable stored timestamp returns False so the URL is re-ingested
        rather than silently skipped.
        """
        try:
            existing_dt = datetime.fromisoformat(
                str(existing_ts).replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            logger.warning(
                "sitemap dedup: unparseable stored ingestion_timestamp %r — "
                "forcing re-ingest",
                existing_ts,
            )
            return False
        if existing_dt.tzinfo is None:
            existing_dt = existing_dt.replace(tzinfo=UTC)
        return lastmod <= existing_dt


@final
@dataclass(frozen=True, slots=True)
class BulkIngestRunner:
    """Fans out ``ingest_one`` over a thread pool and aggregates outcomes."""

    ingest_one: Callable[[UrlIngest, Progress, IngestContext], IngestResult]
    workers: int = 4

    def run(
        self,
        to_ingest: list[tuple[str, str | None]],
        progress: Progress,
        context: IngestContext,
        options: BulkOptions,
    ) -> tuple[int, int, list[str]]:
        """Return ``(ingested_count, failed_count, error_messages)``."""
        ingested = 0
        failed = 0
        errors: list[str] = []

        if to_ingest:
            # Always replace existing chunks for URLs that passed dedup — the
            # dedup already skipped unchanged URLs, so every submitted entry is
            # a genuine (re)ingest.
            bulk_context = replace(context, overwrite=True)
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = {
                    executor.submit(
                        self.ingest_one,
                        UrlIngest(
                            url=page_url,
                            document_name=doc_name,
                            timeout=options.timeout,
                            delay=options.delay,
                        ),
                        progress,
                        bulk_context,
                    ): page_url
                    for page_url, doc_name in to_ingest
                }
                for future in as_completed(futures):
                    page_url = futures[future]
                    try:
                        future.result()
                        ingested += 1
                        progress(
                            "Ingested %s (%d/%d)", page_url, ingested, len(to_ingest)
                        )
                    except Exception as exc:
                        failed += 1
                        errors.append(f"{page_url}: {exc}")
                        logger.exception("Failed to ingest %s", page_url)
                        progress("Failed %s: %s", page_url, exc)

        return ingested, failed, errors
