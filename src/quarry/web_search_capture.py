"""Parse a PostToolUse WebSearch hook payload into a searchable digest.

Mirrors :mod:`quarry.web_capture` for search results: the payload's ``query``
and ``tool_response`` become a short markdown digest that ``handle_post_web_search``
files under ``<repo>-captures``.  A full page fetch is not attempted — WebSearch
never fetches page bodies; the digest is the useful signal.

The exact shape of ``tool_response`` is under-specified in Claude Code's own
docs, so parsing is defensive: any failure yields ``None`` for the property in
question and the handler skips the capture.  Absence is the documented contract,
not a failure — see :class:`WebFetchPayload` for the precedent this file mirrors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WebSearchPayload:
    """A PostToolUse WebSearch payload, parsed into what a capture needs.

    ``query`` is the search string the agent submitted; ``digest`` is a short
    markdown summary of the result list (title, url, snippet per result).  Both
    return ``None`` when the payload lacks a usable value.
    """

    _raw: dict[str, object]

    @property
    def query(self) -> str | None:
        """Return the search query string, or ``None`` when absent/blank."""
        tool_input = self._raw.get("tool_input")
        if isinstance(tool_input, dict):
            query = tool_input.get("query")
            if isinstance(query, str) and query.strip():
                return query.strip()
        return None

    @property
    def digest(self) -> str | None:
        """Return a markdown digest of the search results, or ``None``.

        Handles two shapes observed for ``tool_response``: a JSON-encoded string
        holding a list/dict, or an already-parsed dict.  A response with no
        result items yields ``None`` so the handler skips a content-free capture.
        """
        results = self._results()
        if not results:
            return None
        lines = [f"# Web search: {self.query or '(no query)'}\n"]
        for item in results:
            line = self._format_item(item)
            if line:
                lines.append(line)
        if len(lines) == 1:
            return None
        return "\n".join(lines)

    def _results(self) -> list[object]:
        """Return the raw result items from ``tool_response``, or an empty list."""
        raw = self._raw.get("tool_response")
        parsed = self._as_parsed(raw)
        if isinstance(parsed, list):
            return list(parsed)
        if isinstance(parsed, dict):
            candidates = parsed.get("results") or parsed.get("result")
            if isinstance(candidates, list):
                return list(candidates)
        return []

    @staticmethod
    def _as_parsed(raw: object) -> object:
        """Return *raw* decoded from JSON if it's a string, else *raw* itself."""
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                return None
        return raw

    @classmethod
    def _format_item(cls, item: object) -> str:
        """Format a single result item as ``- [title](url): snippet``.

        Missing fields degrade individually — a hit with only a URL still emits
        a useful line.  A non-dict item is dropped.
        """
        if not isinstance(item, dict):
            return ""
        title = cls._str_field(item.get("title"))
        url = cls._str_field(item.get("url"))
        snippet = cls._str_field(item.get("snippet") or item.get("description"))
        if not (title or url or snippet):
            return ""
        label = title or url or "result"
        head = f"- [{label}]({url})" if url else f"- {label}"
        return f"{head}: {snippet}" if snippet else head

    @staticmethod
    def _str_field(value: object) -> str:
        """Return *value* stripped when it is a non-blank string, else ``""``."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
        return ""
