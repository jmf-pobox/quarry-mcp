"""Sitemap-driven and auto-discovered bulk URL ingestion."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, final

from quarry.ingest_collection import IngestCollection
from quarry.ingestion.bulk_ingest import (
    BulkIngestRunner,
    BulkOptions,
    SafeEntrySelector,
)
from quarry.ingestion.web_ingest import UrlIngest, ingest_url
from quarry.results import SitemapResult

if TYPE_CHECKING:
    from quarry.ingestion.ingest_context import IngestContext, Progress
    from quarry.results import IngestResult
    from quarry.sitemap import SitemapEntry

logger = logging.getLogger(__name__)


@final
@dataclass(frozen=True, slots=True)
class SitemapCrawl:
    """A discovered set of sitemap entries plus their originating URL."""

    entries: list[SitemapEntry]
    source_url: str


@final
class SitemapIngest:
    """Sitemap-driven and auto-discovered bulk URL ingestion, funneled through
    :class:`BulkIngestRunner`.
    """

    @staticmethod
    def _bulk_ingest_entries(
        crawl: SitemapCrawl,
        progress: Progress,
        context: IngestContext,
        options: BulkOptions,
    ) -> SitemapResult:
        """Filter, dedup, and parallel-ingest a list of sitemap entries.

        Shared by ``ingest_sitemap`` (explicit sitemap URL) and
        ``ingest_auto`` (auto-discovered pages).
        """
        selector = SafeEntrySelector(
            include=options.include, exclude=options.exclude, limit=options.limit
        )
        filtered = selector.select_safe(crawl.entries)
        progress("Selected %d safe URLs to ingest", len(filtered))
        to_ingest, skipped = selector.partition(filtered, context)
        progress("%d to ingest, %d up-to-date", len(to_ingest), skipped)
        ingested, failed, errors = BulkIngestRunner(
            ingest_one=ingest_url, workers=options.workers
        ).run(to_ingest, progress, context, options)
        progress("Done: %d ingested, %d skipped, %d failed", ingested, skipped, failed)

        return SitemapResult(
            sitemap_url=crawl.source_url,
            collection=context.collection,
            total_discovered=len(crawl.entries),
            after_filter=len(filtered),
            ingested=ingested,
            skipped=skipped,
            failed=failed,
            errors=errors,
        )

    @staticmethod
    def ingest_sitemap(
        url: str,
        progress: Progress,
        context: IngestContext,
        options: BulkOptions,
    ) -> SitemapResult:
        """Crawl a sitemap and ingest all discovered URLs.

        Fetches the sitemap, discovers all URLs (following sitemap indexes),
        applies include/exclude filters, deduplicates against existing documents
        via <lastmod>, and ingests new/changed URLs in parallel.

        Args:
            url: Sitemap URL.
            progress: Progress reporter.
            context: Shared database/settings/overwrite/memory-tag knobs.
                ``context.collection`` defaults to the sitemap URL's domain
                when empty.
            options: Worker count, delay, timeout, and include/exclude/limit.

        Returns:
            SitemapResult with counts and error details.
        """
        from quarry.sitemap import SitemapDiscovery  # noqa: PLC0415

        # IngestContext.collection defaults to "default" (the right default for
        # ingest_document/content/url, which have no per-URL bucketing). A
        # sitemap crawl's own "let the pipeline decide" signal is an EMPTY
        # collection (IngestCollection.resolve's documented contract) -- and
        # "default" is that resolver's own no-host fallback name -- so an
        # unspecified context.collection is treated the same way here as a
        # caller who passed "" explicitly: derive from the URL's hostname.
        requested = "" if context.collection == "default" else context.collection
        context = replace(
            context, collection=IngestCollection.resolve(url, requested).name
        )

        progress("Fetching sitemap: %s", url)
        entries = SitemapDiscovery.discover_urls(url)
        progress("Discovered %d URLs", len(entries))

        return SitemapIngest._bulk_ingest_entries(
            SitemapCrawl(entries=entries, source_url=url), progress, context, options
        )

    @staticmethod
    def ingest_auto(
        url: str,
        progress: Progress,
        context: IngestContext,
        options: BulkOptions,
    ) -> IngestResult | SitemapResult:
        """Smart URL ingestion: discover sitemap, crawl if found, else single page.

        Uses ultimate-sitemap-parser (USP) for robust sitemap discovery via
        robots.txt, well-known locations, and multiple sitemap formats
        (XML, RSS, Atom, plain text).

        1. If the URL is itself a sitemap, crawl it directly.
        2. Otherwise, auto-discover sitemaps for the site origin.
        3. If pages found, apply path-prefix filter and bulk-ingest.
        4. If no sitemap found, fall back to single-page ingestion.

        Args:
            url: Any HTTP(S) URL on the target site.
            progress: Progress reporter.
            context: Shared database/settings/overwrite/memory-tag knobs.
                ``context.collection`` defaults to the URL hostname when empty.
            options: Worker count, delay, and timeout for a sitemap crawl.

        Returns:
            SitemapResult if a sitemap was discovered, IngestResult otherwise.
        """
        from urllib.parse import urlparse  # noqa: PLC0415

        from usp.exceptions import (  # noqa: PLC0415
            GunzipException,
            SitemapException,
            SitemapXMLParsingException,
            StripURLToHomepageException,
        )

        from quarry.sitemap import SitemapDiscovery  # noqa: PLC0415

        parsed = urlparse(url)
        # See ingest_sitemap's matching comment: "default" is IngestContext's
        # dataclass default, not a caller's explicit choice, so it is treated
        # as the resolver's "" (derive from hostname) signal here too.
        requested = "" if context.collection == "default" else context.collection
        context = replace(
            context, collection=IngestCollection.resolve(url, requested).name
        )

        # If the URL itself is a sitemap, skip discovery and crawl directly.
        # Match sitemap files (*.xml, *.xml.gz) and /sitemap paths, but not
        # pages that merely contain "sitemap" as a substring (e.g. /sitemap-guide).
        path_lower = parsed.path.lower()
        last_segment = path_lower.rsplit("/", 1)[-1]
        is_sitemap = last_segment.startswith("sitemap") and (
            last_segment.endswith((".xml", ".xml.gz", ".txt"))
            or last_segment == "sitemap"
        )
        if is_sitemap:
            progress("URL is a sitemap, crawling directly")
            return SitemapIngest.ingest_sitemap(url, progress, context, options)

        progress("Discovering sitemaps for %s://%s", parsed.scheme, parsed.netloc)
        try:
            entries = SitemapDiscovery.discover_pages(url)
        except (
            SitemapException,
            SitemapXMLParsingException,
            GunzipException,
            StripURLToHomepageException,
        ) as exc:
            # USP's own documented failure modes -- a malformed homepage URL,
            # unparseable XML, a corrupt gzip body -- are the sitemap being
            # genuinely absent or broken, so this still falls back to a
            # single-page ingest below.  Anything else is a programmer error
            # and must propagate, not be swallowed as "no sitemap found."
            logger.exception("Sitemap discovery failed for %s", url)
            progress("Sitemap discovery error for %s: %s", url, exc)
            entries = []

        if not entries:
            progress("No sitemap found, ingesting single page")
            request = UrlIngest(url=url, timeout=options.timeout)
            return ingest_url(request, progress, context)

        progress("Discovered %d pages via sitemap", len(entries))

        # Derive include filter from input URL path, applied once up front to
        # avoid double-filtering inside _bulk_ingest_entries.
        path = parsed.path.rstrip("/")
        if path:
            entries = SitemapDiscovery.filter_entries(
                entries, include=[path, f"{path}/*"]
            )

        # If filtering dropped everything, fall back to single-page ingestion.
        # This handles sites whose sitemap is partially parseable but doesn't
        # contain the requested path (e.g. namespace-prefixed XML).
        if not entries:
            progress("Sitemap has no pages matching %s, ingesting single page", path)
            request = UrlIngest(url=url, timeout=options.timeout)
            return ingest_url(request, progress, context)

        return SitemapIngest._bulk_ingest_entries(
            SitemapCrawl(entries=entries, source_url=url), progress, context, options
        )


# Module-level aliases: every existing caller and the package's public API spell
# these ``ingest_sitemap(...)`` and ``ingest_auto(...)`` (no receiver) — binding
# the class's staticmethods to bare module names keeps that calling convention
# while the funnel's entry points live as real, class-scoped methods above.
ingest_sitemap = SitemapIngest.ingest_sitemap
ingest_auto = SitemapIngest.ingest_auto

__all__ = ["SitemapCrawl", "SitemapIngest", "ingest_auto", "ingest_sitemap"]
