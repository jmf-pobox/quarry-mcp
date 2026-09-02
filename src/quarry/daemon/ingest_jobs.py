"""The daemon's content-ingestion jobs: scrubbed inline text and fetched URLs.

Each request is validated into an immutable *job* value object that owns its own
background execution, so the validated fields travel together instead of as a
ten-argument task function.  Both the ``remember`` and ``capture`` front doors
build :class:`ScrubbedIngestJob`; the URL route builds :class:`IngestJob`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.concurrency import run_in_threadpool

from quarry.daemon.job_spool import SpoolRecord
from quarry.daemon.tasks import task_terminal
from quarry.ingestion.web_fetch import WebFetcher

if TYPE_CHECKING:
    from quarry.daemon.context import DaemonContext
    from quarry.daemon.tasks import TaskState
    from quarry.ingestion.web_fetch import FetchedBody

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScrubbedIngestJob:
    """A validated inline-ingest request that always scrubs before storing.

    The scrub runs on the worker thread inside ``run_in_threadpool``, never on
    the event loop, so its regex passes do not stall other requests.  Scrubbing
    precedes embedding and storage, so a scrub that raises aborts the whole
    operation before a single chunk is written — a failed scrub leaves nothing
    half-redacted in the database.  The free-form metadata (document name and
    summary) is scrubbed too, but at the choke point: passing ``content_scrubber``
    to ``ingest_content`` is the signal that redacts content AND metadata, so
    this job forwards the raw name/summary and lets the pipeline redact once —
    no surface can forget it (the stdio MCP remember once did).
    """

    name: str
    content: str
    collection: str
    format_hint: str
    overwrite: bool
    scrub_label: str
    agent_handle: str
    memory_type: str
    summary: str

    async def run(self, ctx: DaemonContext, state: TaskState) -> None:
        """Scrub then ingest the content in a background thread, tracking state."""
        with task_terminal(state):
            result = await run_in_threadpool(self.scrub_and_ingest, ctx)
            state.status = "completed"
            state.results = dict(result)

    def spool_record(self) -> SpoolRecord | None:
        """Return a scrubbed snapshot; ``remember`` has no durable client copy.

        The content and name are scrubbed here (the same redaction ``run`` would
        apply at ingest), so a drain-abort snapshot never lands unredacted on
        disk while still carrying the knowledge back for recovery.
        """
        return SpoolRecord(
            kind=self.scrub_label,
            collection=self.collection,
            name=self._scrubbed(self.name),
            payload=self._scrubbed(self.content),
        )

    def _scrubbed(self, text: str) -> str:
        """Redact *text* under this job's scrub label (shared by ingest + spool)."""
        from quarry.scrub import scrub_and_log  # noqa: PLC0415

        return scrub_and_log(text, self.scrub_label)

    def scrub_and_ingest(self, ctx: DaemonContext) -> dict[str, object]:
        """Ingest with a scrubber; the pipeline redacts content AND metadata."""
        from quarry.ingestion.pipeline import ingest_content  # noqa: PLC0415

        return dict(
            ingest_content(
                self.content,
                self.name,
                ctx.database,
                ctx.settings,
                overwrite=self.overwrite,
                collection=self.collection,
                format_hint=self.format_hint,
                content_scrubber=self._scrubbed,
                agent_handle=self.agent_handle,
                memory_type=self.memory_type,
                summary=self.summary,
            )
        )


@dataclass(frozen=True, slots=True)
class IngestJob:
    """A validated ingest request that fetches and indexes a URL.

    ``scrub`` set marks a web-fetch capture re-fetch (the hook's fallback): the
    URL is fetched once through the SSRF-checked path, scrubbed, and stored in
    the ``<repo>-captures`` collection the route already resolved into
    ``collection`` (``default-captures`` when the working directory is
    unregistered) — never a sitemap crawl.  ``scrub`` unset is a plain
    ``quarry ingest``: sitemap-aware and unscrubbed, since a deliberately
    ingested document is stored byte-for-byte.  ``collection`` is the routing key
    the queue serializes on, so the route resolves it before the job is built.

    ``document_name_override`` is empty for the primary URL route (the URL is
    the natural name).  A capture *re-fetch* built by
    :meth:`CaptureIngestJob._refetch` sets it to the inline capture's friendly
    name (e.g. ``"WebFetch — example.com — 2026-…"``), so a non-HTML capture
    stored via the text pipeline keeps that name instead of falling back to the
    raw URL.
    """

    source: str
    overwrite: bool
    collection: str
    scrub: bool
    agent_handle: str
    memory_type: str
    summary: str
    document_name_override: str = ""

    async def run(self, ctx: DaemonContext, state: TaskState) -> None:
        """Fetch and index the URL in a background thread, updating task state."""
        with task_terminal(state):
            result = await run_in_threadpool(self._ingest, ctx)
            state.status = "completed"
            state.results = dict(result)

    def spool_record(self) -> SpoolRecord | None:
        """Return a snapshot of the source URL; an ``ingest`` has no client copy.

        The source is the recoverable unit — re-issuing the ingest re-fetches it.
        It is stored as given (a plain ingest already persists the URL verbatim),
        so recovery has the exact URL to retry.
        """
        return SpoolRecord(
            kind="ingest",
            collection=self.collection,
            name=self.source,
            payload=self.source,
        )

    def _ingest(self, ctx: DaemonContext) -> dict[str, object]:
        """Run the capture re-fetch (scrubbed, captures collection) or plain ingest.

        The scrubbed branch fetches via :meth:`WebFetcher.fetch_body` first so a
        JSON/plain-text/XML URL (a REST endpoint, a raw log) is captured as text
        rather than raising ``ValueError`` from the HTML-only :meth:`fetch`.  The
        HTML-vs-text routing then lives in :meth:`ingest_captured_body`, shared
        with :meth:`CaptureIngestJob._refetch`.
        """
        if self.scrub:
            body = WebFetcher().fetch_body(self.source)
            return self.ingest_captured_body(ctx, body)

        from quarry.ingestion.pipeline import ingest_auto  # noqa: PLC0415

        return dict(
            ingest_auto(
                self.source,
                ctx.database,
                ctx.settings,
                overwrite=self.overwrite,
                collection=self.collection,
                agent_handle=self.agent_handle,
                memory_type=self.memory_type,
                summary=self.summary,
            )
        )

    def ingest_captured_body(
        self, ctx: DaemonContext, body: FetchedBody
    ) -> dict[str, object]:
        """Route a fetched capture body: HTML via extractor, else text with mime marker.

        Shared by :meth:`_ingest` (primary capture) and
        :meth:`CaptureIngestJob._refetch` (empty-inline fallback) so both paths
        agree on the media-type contract: an HTML body flows through
        :func:`ingest_url` with the already-fetched text reused via
        ``prefetched_html`` (no double fetch), and anything else is stored via
        :func:`ingest_content` with a leading ``<!-- media_type: X -->`` marker
        so a reader — and a downstream grep — knows the shape.  The marker is
        inert to the markdown extractor and to the scrub choke point.
        """
        from quarry.ingestion.pipeline import (  # noqa: PLC0415
            ingest_content,
            ingest_url,
        )
        from quarry.scrub import scrub_and_log  # noqa: PLC0415

        def scrub(text: str) -> str:
            return scrub_and_log(text, "web-fetch")

        if body.is_html:
            return dict(
                ingest_url(
                    self.source,
                    ctx.database,
                    ctx.settings,
                    overwrite=self.overwrite,
                    collection=self.collection,
                    content_scrubber=scrub,
                    agent_handle=self.agent_handle,
                    memory_type=self.memory_type,
                    summary=self.summary,
                    prefetched_html=body.text,
                )
            )

        media_type = body.media_type or "unknown"
        content = f"<!-- media_type: {media_type} -->\n{body.text}"
        return dict(
            ingest_content(
                content,
                self.document_name_override or self.source,
                ctx.database,
                ctx.settings,
                overwrite=self.overwrite,
                collection=self.collection,
                format_hint="markdown",
                content_scrubber=scrub,
                agent_handle=self.agent_handle,
                memory_type=self.memory_type,
                summary=self.summary,
            )
        )


@dataclass(frozen=True, slots=True)
class CaptureIngestJob:
    """A web-fetch capture: scrub the fetched HTML inline, re-fetch if it's empty.

    The daemon scrubs and stores the already-fetched HTML through the composed
    :class:`ScrubbedIngestJob`.  A JS-rendered or otherwise text-empty page can
    extract to zero chunks; rather than silently index nothing, the daemon then
    re-fetches the *source URL* server-side (scrub on, same captures collection)
    so the page is captured instead of dropped.  That re-fetch is an SSRF sink,
    so the capture route runs the ``UrlSafetyCheck`` gate on ``source_url`` at
    the boundary before building this job — the job trusts an already-validated
    URL and does not re-check.  A capture with no source URL (a compaction
    transcript) simply stores what it has.  The re-fetch scrubs content and
    summary, matching the inline phase.
    """

    inline: ScrubbedIngestJob
    source_url: str

    @property
    def collection(self) -> str:
        """Return the captures collection this job writes (the queue routing key)."""
        return self.inline.collection

    def spool_record(self) -> SpoolRecord | None:
        """Return ``None``: a capture's transcript ``.md`` predates the POST.

        The client-side artifact already outlives a drain-abort and ``quarry
        backfill`` re-ingests it, so the daemon need not spool this job.
        """
        return None

    async def run(self, ctx: DaemonContext, state: TaskState) -> None:
        """Ingest inline, re-fetching the source on empty, tracking task state."""
        with task_terminal(state):
            result = await run_in_threadpool(self._capture, ctx)
            state.status = "completed"
            state.results = dict(result)

    def _capture(self, ctx: DaemonContext) -> dict[str, object]:
        """Scrub-ingest inline; on zero chunks with a source URL, re-fetch it."""
        result = self.inline.scrub_and_ingest(ctx)
        if result.get("chunks") or not self.source_url:
            return result
        return self._refetch(ctx)

    def _refetch(self, ctx: DaemonContext) -> dict[str, object]:
        """Re-fetch source URL and delegate routing to :class:`IngestJob`.

        A safety/network failure logs cleanly at WARN and returns an empty
        result — never a traceback — because ``_capture`` already stored what
        the inline phase had.  A successful fetch flows through the same
        HTML-vs-text routing :class:`IngestJob` uses for the primary URL path
        (:meth:`IngestJob.ingest_captured_body`), so both paths agree on the
        media-type contract instead of drifting.
        """
        from quarry.capture_url import CaptureUrl  # noqa: PLC0415

        try:
            body = WebFetcher().fetch_body(self.source_url)
        except (OSError, ValueError, TimeoutError) as exc:
            # Redact the URL through the same normaliser writes use (drops
            # userinfo/query/fragment) and log only the exception class — the
            # exception's own text quotes the raw URL and can carry ?token=
            # or user:pass@ secrets into the persistent quarry.log (CWE-532).
            logger.warning(
                "capture: refetch of %s failed (%s); skipping",
                CaptureUrl.for_web_fetch(self.source_url),
                type(exc).__name__,
            )
            return {"chunks": 0, "sections": 0}

        logger.info(
            "capture: %s inline extracted to zero chunks — re-fetching via daemon (%s)",
            self.inline.name,
            body.media_type or "unknown",
        )
        return IngestJob(
            source=self.source_url,
            overwrite=self.inline.overwrite,
            collection=self.inline.collection,
            scrub=True,
            agent_handle=self.inline.agent_handle,
            memory_type=self.inline.memory_type,
            summary=self.inline.summary,
            document_name_override=self.inline.name,
        ).ingest_captured_body(ctx, body)
