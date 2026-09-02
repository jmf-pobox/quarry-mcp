"""Non-HTML capture regression (quarry-jzqw / G4).

The capture route re-fetches when the client-side payload is empty by
building an ``IngestJob(scrub=True)`` and running :meth:`IngestJob._ingest`.
That path today calls :func:`quarry.ingestion.pipeline.ingest_url`, which
delegates to :meth:`quarry.ingestion.web_fetch.WebFetcher.fetch` — and
``fetch`` raises ``ValueError: URL returned non-HTML content`` for any
non-HTML media type.  So a JSON/plain-text/XML URL captured via the
empty-payload fallback loses its content and dumps a traceback into the
daemon log instead of storing the body as text.

The G4 fix on the :class:`CaptureIngestJob._refetch` branch handled
non-HTML correctly by routing through :meth:`WebFetcher.fetch_body` and
:func:`ingest_content` with a ``<!-- media_type: X -->`` marker.  The same
routing is missing on :class:`IngestJob._ingest`.  These tests assert the
same non-HTML contract at that entry point — they FAIL on v3.2.0 because
``ingest_url`` still raises, and they pass once ``_ingest`` grows the same
media-type branch its sibling already has.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

import pytest

from quarry.daemon.ingest_jobs import IngestJob
from quarry.ingestion.web_fetch import FetchedBody

if TYPE_CHECKING:
    from quarry.daemon.context import DaemonContext


pytestmark = pytest.mark.hook_integration


_QUARRY_JZQW_SUMMARY = (
    "quarry-jzqw (G4): IngestJob._ingest still raises ValueError on non-HTML "
    "URLs — capture re-fetch drops the body instead of storing it as text."
)


def _ctx() -> DaemonContext:
    """Return a minimal :class:`DaemonContext` stand-in for the ingest call."""
    return cast(
        "DaemonContext",
        SimpleNamespace(database=MagicMock(), settings=MagicMock()),
    )


def _job(url: str) -> IngestJob:
    """Return an IngestJob shaped like the daemon's capture-refetch fallback."""
    return IngestJob(
        source=url,
        overwrite=True,
        collection="repo-captures",
        scrub=True,
        agent_handle="",
        memory_type="",
        summary="",
    )


@pytest.mark.xfail(
    reason=(
        "quarry-jzqw: IngestJob._ingest still routes non-HTML URLs through "
        "ingest_url, which raises ValueError instead of storing the body as text."
    ),
    strict=True,
)
@pytest.mark.parametrize(
    ("media_type", "body_text"),
    [
        ("application/json", '{"ok": true, "count": 42}'),
        ("text/plain", "hello world\nline two\n"),
        ("application/xml", "<?xml version='1.0'?><root><child/></root>"),
    ],
    ids=["json", "text", "xml"],
)
def test_ingest_captures_non_html_as_text(media_type: str, body_text: str) -> None:
    """A non-HTML URL routes through ingest_content with a mime marker (no ValueError).

    Today ``IngestJob._ingest`` calls ``ingest_url``, whose internal
    :meth:`WebFetcher.fetch` raises ``ValueError`` for anything that is not
    HTML.  The fix teaches ``_ingest`` to switch on :meth:`fetch_body`'s
    ``media_type`` — HTML through the extractor, everything else through
    :func:`ingest_content` with a leading ``<!-- media_type: X -->`` marker,
    mirroring :meth:`CaptureIngestJob._refetch`.
    """
    url = "https://example.test/data"
    body = FetchedBody(text=body_text, media_type=media_type)
    with (
        patch(
            "quarry.ingestion.web_fetch.WebFetcher.fetch_body",
            return_value=body,
        ),
        patch(
            "quarry.ingestion.pipeline.ingest_content",
            return_value={"chunks": 1, "sections": 1},
        ) as mock_ingest_content,
        patch(
            "quarry.ingestion.pipeline.ingest_url",
            return_value={"chunks": 1, "sections": 1},
        ),
    ):
        try:
            result = _job(url)._ingest(_ctx())
        except ValueError as exc:
            pytest.fail(
                f"{_QUARRY_JZQW_SUMMARY}\n"
                f"  media_type={media_type!r}\n"
                f"  raised ValueError: {exc}\n"
                "  remove the @pytest.mark.xfail marker when this passes"
            )

    assert mock_ingest_content.called, (
        f"{_QUARRY_JZQW_SUMMARY}\n"
        f"  media_type={media_type!r}: ingest_content was never called; "
        "the non-HTML body was dropped instead of stored as text.\n"
        "  remove the @pytest.mark.xfail marker when this passes"
    )
    call = mock_ingest_content.call_args
    content_arg = call.args[0] if call.args else call.kwargs.get("content", "")
    assert content_arg.startswith("<!-- media_type: "), (
        f"{_QUARRY_JZQW_SUMMARY}\n"
        f"  media_type={media_type!r}: stored content lacks the "
        f"'<!-- media_type: X -->' marker "
        "that lets a reader (and downstream grep) know the body's shape.\n"
        f"  content prefix: {content_arg[:80]!r}\n"
        "  remove the @pytest.mark.xfail marker when this passes"
    )
    chunks_reported = int(cast("int", result.get("chunks", 0)))
    assert chunks_reported >= 1, (
        f"{_QUARRY_JZQW_SUMMARY}\n"
        f"  media_type={media_type!r}: ingest_content returned zero chunks; "
        "the capture would still be dropped.\n"
        "  remove the @pytest.mark.xfail marker when this passes"
    )
