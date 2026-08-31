"""The capture-push contract: push redacted capture shadows."""

from __future__ import annotations

from pydantic import BaseModel


class CapturesPushResponse(BaseModel):
    """The response for pushing redacted capture shadows.

    ``results`` maps each pushed collection to its per-collection push summary
    (``CaptureSync`` result dict) — a wire-boundary mapping the CLI renders,
    kept as ``dict`` so a summary-field addition never drops on the wire.
    """

    # wire boundary — per-collection push summaries keyed by collection name.
    results: dict[str, dict[str, object]]


class CapturesLookupResponse(BaseModel):
    """Whether a URL is already indexed under a project's captures collection.

    ``document_name`` names the stored capture when ``matched`` is true; it is
    absent (``None``) on a miss — there is nothing to name, not a lookup
    failure.
    """

    matched: bool
    document_name: str | None = None
