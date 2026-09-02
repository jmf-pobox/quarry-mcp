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

import logging
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
                f"  raised ValueError: {exc}"
            )

    assert mock_ingest_content.called, (
        f"{_QUARRY_JZQW_SUMMARY}\n"
        f"  media_type={media_type!r}: ingest_content was never called; "
        "the non-HTML body was dropped instead of stored as text."
    )
    call = mock_ingest_content.call_args
    content_arg = call.args[0] if call.args else call.kwargs.get("content", "")
    assert content_arg.startswith("<!-- media_type: "), (
        f"{_QUARRY_JZQW_SUMMARY}\n"
        f"  media_type={media_type!r}: stored content lacks the "
        f"'<!-- media_type: X -->' marker "
        "that lets a reader (and downstream grep) know the body's shape.\n"
        f"  content prefix: {content_arg[:80]!r}"
    )
    chunks_reported = int(cast("int", result.get("chunks", 0)))
    assert chunks_reported >= 1, (
        f"{_QUARRY_JZQW_SUMMARY}\n"
        f"  media_type={media_type!r}: ingest_content returned zero chunks; "
        "the capture would still be dropped."
    )


@pytest.mark.parametrize(
    ("url", "leak"),
    [
        ("https://user:pass@example.test/path", "user:pass@"),
        ("https://example.test/reset?token=secretxyz", "secretxyz"),
        ("https://example.test/page?email=a%40b.com", "email="),
        ("https://example.test/doc#tokenfragment", "tokenfragment"),
    ],
    ids=["userinfo", "token-query", "email-query", "fragment"],
)
def test_non_html_ingest_redacts_url_secrets_in_document_name(
    url: str, leak: str
) -> None:
    """Non-HTML capture routes derive document_name via CaptureUrl.redacted.

    The pipeline's regex scrubber leaves URL structural components
    (``?email=``, ``?token=``, ``user:pass@``, ``#fragment``) on the
    persisted document_name, so passing the raw URL leaks the secret into
    the pushable captures collection (CWE-532).  ``ingest_url`` already
    calls ``CaptureUrl(url).redacted(scrub)`` before ``_scrub_metadata``;
    the non-HTML branch of :meth:`IngestJob.ingest_captured_body` must
    do the same for parity.
    """
    body = FetchedBody(text='{"ok":true}', media_type="application/json")
    with (
        patch(
            "quarry.ingestion.web_fetch.WebFetcher.fetch_body",
            return_value=body,
        ),
        patch(
            "quarry.ingestion.pipeline.ingest_content",
            return_value={"chunks": 1, "sections": 1},
        ) as mock_ingest_content,
    ):
        _job(url)._ingest(_ctx())

    call = mock_ingest_content.call_args
    document_name = (
        call.args[1] if len(call.args) >= 2 else call.kwargs["document_name"]
    )
    assert leak not in document_name, (
        f"non-HTML ingest leaked URL secret {leak!r} into stored document_name:\n"
        f"  url={url!r}\n"
        f"  document_name={document_name!r}"
    )


def test_ingest_fetch_failure_logs_redacted_url_and_returns_zero_chunks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A fetch failure on _ingest logs the URL redacted and returns empty.

    Without the guard, the raw URL rides ``fetch_body``'s exception
    message ("Cannot reach {url}: ...") into ``task_terminal``'s traceback
    and the persisted ``state.error`` — leaking ``?token=`` and
    ``user:pass@`` into the daemon log (CWE-532).  The guard mirrors
    :meth:`CaptureIngestJob._refetch`: redact through ``CaptureUrl``,
    log only the exception class, return an empty result.
    """
    url = "https://user:pass@example.test/reset?token=secretxyz"
    boom = OSError(f"Cannot reach {url}: connection refused")
    with (
        patch(
            "quarry.ingestion.web_fetch.WebFetcher.fetch_body",
            side_effect=boom,
        ),
        caplog.at_level(logging.WARNING, logger="quarry.daemon.ingest_jobs"),
    ):
        result = _job(url)._ingest(_ctx())

    assert result == {"chunks": 0, "sections": 0}
    log_text = caplog.text
    assert "secretxyz" not in log_text, (
        f"fetch-failure log leaked query token:\n{log_text}"
    )
    assert "user:pass" not in log_text, (
        f"fetch-failure log leaked userinfo:\n{log_text}"
    )
    assert "OSError" in log_text, (
        f"fetch-failure log missing exception class name:\n{log_text}"
    )
