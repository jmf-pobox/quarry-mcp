"""Handlers for the four new agent-lifecycle hooks: SessionEnd,
PostToolUse:WebSearch, PostToolUse:Read, SubagentStop.

Each is a ``HookAgent`` staticmethod with the ``run_hook`` shape — a
``Callable[[dict[str, object]], dict[str, object]]`` — matching every existing
handler in :mod:`quarry.hooks`.  The orchestration logic (parse → filter →
send) lives in these methods; the substantive work (archive/scrub/send)
lives in the classes each handler delegates to.

**SubagentStop is a BLOCKING hook.**  ``HookAgent.subagent_stop`` must NEVER
populate a ``decision`` field or exit non-zero: a bug there hangs every
subagent in the session.  The design mandates ``{}`` on every path; the
handler tests assert this under crafted-adversarial payloads.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from quarry._stdlib import load_hook_config
from quarry.daemon_capture import DaemonCaptureSender
from quarry.ethos_handle import EthosConfig
from quarry.read_capture import ReadCaptureFilter, ReadPayload
from quarry.scrub import Scrubber, ScrubConfig
from quarry.session_transcript import SessionTranscriptCapture
from quarry.web_search_capture import WebSearchPayload

if TYPE_CHECKING:
    from quarry.collection_resolver import CollectionResolver
    from quarry.config import Settings

logger = logging.getLogger(__name__)

_WEB_SEARCH_UNREACHABLE = (
    "web-search: daemon unreachable; digest not indexed (re-run to retry)"
)
_READ_UNREACHABLE = "post-read: daemon unreachable; file not indexed"

# Secrets-only scrubber, built once: a client-side defense-in-depth check on
# Read content ahead of the daemon's own scrub, relevant when QUARRY_URL
# points at a remote daemon.  PII/profanity passes are off — those aren't
# reasons to withhold a capture, only genuine secrets are.
_SECRET_SCRUBBER = Scrubber(ScrubConfig(scrub_pii=False, scrub_profanity=False))


class HookAgent:
    """Namespace for the four agent-lifecycle hook handlers."""

    @staticmethod
    def session_end(payload: dict[str, object]) -> dict[str, object]:
        """Handle SessionEnd hook: capture the full session transcript unconditionally.

        Fires on every session close (unlike PreCompact, which only fires on
        context compaction) so a short session that never compacts still
        yields a durable capture.  Returns ``{}`` on every path — the session
        is already ending, there is no live user to surface a systemMessage
        to.
        """
        cwd = HookAgent._as_dir(payload.get("cwd"))
        if not cwd:
            logger.debug("session-end: missing or relative cwd, skipping")
            return {}
        if not load_hook_config(cwd).session_end:
            logger.debug("session-end: disabled by config")
            return {}
        transcript_path = HookAgent._as_str(payload.get("transcript_path"))
        session_id = HookAgent._as_str(payload.get("session_id"))
        if not transcript_path or not session_id:
            logger.debug("session-end: missing transcript_path or session_id")
            return {}
        tp = HookAgent._resolve_jsonl(transcript_path, label="session-end")
        if tp is None:
            return {}

        SessionTranscriptCapture(
            cwd=cwd,
            session_id=session_id,
            transcript_path=tp,
            label="session-end",
            agent_handle=EthosConfig.agent_handle_at(cwd),
        ).capture()
        return {}

    @staticmethod
    def post_web_search(payload: dict[str, object]) -> dict[str, object]:
        """Handle PostToolUse on WebSearch: file a scrubbed digest under captures.

        The daemon derives ``<repo>-captures`` from *cwd*; a session opened
        outside any registered directory files under ``default-captures``.
        The query text and result digest both flow through the daemon's
        ``ScrubbedIngestJob`` choke point, so no client-side scrub is needed
        here.
        """
        cwd = HookAgent._as_dir(payload.get("cwd"))
        if cwd and not load_hook_config(cwd).web_search:
            logger.debug("post-web-search: disabled by config")
            return {}

        parsed = WebSearchPayload(payload)
        digest = parsed.digest
        if digest is None:
            logger.debug("post-web-search: no result digest in payload, skipping")
            return {}

        from quarry.api import CaptureIngestRequest  # noqa: PLC0415

        doc_name = f"search: {parsed.query or '(no query)'}"
        DaemonCaptureSender().send_capture(
            CaptureIngestRequest(
                content=digest,
                cwd=cwd,
                document_name=doc_name,
                format_hint="markdown",
            ),
            unreachable_log=_WEB_SEARCH_UNREACHABLE,
        )
        return {}

    @staticmethod
    def post_read(payload: dict[str, object]) -> dict[str, object]:
        """Handle PostToolUse on Read: file the text under captures if it passes
        the filter.

        Config-gated (default OFF via ``HookConfig.read``) because ``Read``
        fires on every file the agent opens.  The four admission checks — in-
        tree exclusion, secret-path denylist, extension allowlist, size cap —
        run in order, fail-closed.  The daemon's ``ScrubbedIngestJob`` scrubs
        both the content and the document name (a raw filesystem path)
        server-side.
        """
        cwd = HookAgent._as_dir(payload.get("cwd"))
        if not cwd or not load_hook_config(cwd).read:
            logger.debug("post-read: disabled by config or missing cwd")
            return {}

        parsed = ReadPayload(payload)
        file_path = parsed.file_path
        if not file_path:
            logger.debug("post-read: no file_path in payload, skipping")
            return {}

        content = parsed.content
        if not content:
            logger.debug("post-read: no content in payload, skipping")
            return {}

        # Fast checks (in-tree/denylist/extension) run before the content is
        # ever encoded — most rejections never need the byte length at all.
        filter_ = ReadCaptureFilter(resolver=HookAgent._collection_resolver_for(cwd))
        if not filter_.should_capture(file_path, cwd=cwd):
            logger.debug("post-read: filter rejected %s", file_path)
            return {}
        # avoid UnicodeEncodeError on lone surrogates; handler must fail open
        content_bytes = len(content.encode("utf-8", errors="replace"))
        if not filter_.should_capture(file_path, cwd=cwd, content_bytes=content_bytes):
            logger.debug("post-read: content too large for %s", file_path)
            return {}

        if HookAgent._content_has_secret(content):
            logger.debug("post-read: secret pattern matched, skipping %s", file_path)
            return {}

        from quarry.api import CaptureIngestRequest  # noqa: PLC0415

        DaemonCaptureSender().send_capture(
            CaptureIngestRequest(
                content=content,
                cwd=cwd,
                document_name=file_path,
                format_hint="auto",
            ),
            unreachable_log=_READ_UNREACHABLE,
        )
        return {}

    @staticmethod
    def subagent_stop(payload: dict[str, object]) -> dict[str, object]:
        """Handle SubagentStop hook: capture the subagent's own transcript.

        **BLOCKING hook — never return a decision/block field.**
        ``SubagentStop`` fires blocking on Claude Code's side (a non-zero
        exit or a ``decision`` key forces the subagent to keep running),
        unlike every other hook this module registers.  Every path returns
        ``{}``.

        Per Ratification R4b (2026-08-30): the payload's
        ``agent_transcript_path`` is subagent-scoped and distinct from
        ``transcript_path`` (the parent's), so we archive the subagent path.
        Identity carrier is ``agent_id``, not ``session_id`` (which is the
        parent's).
        """
        cwd = HookAgent._as_dir(payload.get("cwd"))
        if not cwd:
            logger.debug("subagent-stop: missing or relative cwd, skipping")
            return {}
        if not load_hook_config(cwd).subagent_stop:
            logger.debug("subagent-stop: disabled by config")
            return {}

        agent_transcript_path = HookAgent._as_str(payload.get("agent_transcript_path"))
        agent_id = HookAgent._as_str(payload.get("agent_id"))
        if not agent_transcript_path or not agent_id:
            logger.debug(
                "subagent-stop: missing agent_transcript_path or agent_id, skipping"
            )
            return {}
        tp = HookAgent._resolve_jsonl(agent_transcript_path, label="subagent-stop")
        if tp is None:
            return {}

        agent_type = HookAgent._as_str(payload.get("agent_type"))
        SessionTranscriptCapture(
            cwd=cwd,
            session_id=agent_id,
            transcript_path=tp,
            label="subagent-stop",
            agent_handle=agent_type or EthosConfig.agent_handle_at(cwd),
        ).capture()
        return {}

    @staticmethod
    def _content_has_secret(content: str) -> bool:
        """Return whether *content* matches a secret pattern (PEM/env/PAT/etc).

        Defense-in-depth ahead of the daemon's own scrub — catches an obvious
        secret before it leaves the machine, which matters when ``QUARRY_URL``
        points at a remote daemon.
        """
        _, redactions = _SECRET_SCRUBBER.scrub(content)
        return bool(redactions)

    @staticmethod
    def _as_str(value: object) -> str:
        """Return *value* when it is a ``str``, else ``""`` (treated as absent)."""
        return value if isinstance(value, str) else ""

    @staticmethod
    def _as_dir(value: object) -> str:
        """Return *value* as a ``str`` naming an ABSOLUTE path, else ``""``."""
        cwd = HookAgent._as_str(value)
        return cwd if cwd and Path(cwd).is_absolute() else ""

    @staticmethod
    def _resolve_jsonl(path_str: str, *, label: str) -> Path | None:
        """Resolve *path_str* to a JSONL transcript path, or ``None`` on skip.

        Skip conditions match ``_precompact_target``'s contract: an OS-invalid
        path or a non-``.jsonl`` suffix returns ``None`` per the no-op
        contract, never crashes the hook.
        """
        try:
            resolved = Path(path_str).resolve()
        except (OSError, ValueError):
            logger.warning("%s: unresolvable transcript_path", label, exc_info=True)
            return None
        if resolved.suffix != ".jsonl":
            logger.warning("%s: unexpected suffix %s", label, resolved.suffix)
            return None
        return resolved

    @staticmethod
    def _collection_resolver_for(cwd: str) -> CollectionResolver | None:
        """Open a CollectionResolver over the settings registry, or ``None`` on failure.

        Read fires often; a settings-load failure must never crash the
        handler.  ``None`` is the documented "no in-tree exclusion possible"
        contract — :class:`ReadCaptureFilter` treats it as "resolver
        unavailable" and skips the first check while running the remaining
        three.
        """
        del cwd  # resolver is settings-scoped; cwd flows to should_capture below
        try:
            settings = HookAgent._resolve_settings()
        except (OSError, ValueError):
            return None
        try:
            from quarry.collection_resolver import CollectionResolver  # noqa: PLC0415
            from quarry.sync_registry import SyncRegistry  # noqa: PLC0415

            conn = SyncRegistry(settings.registry_path)
        except (OSError, ValueError):
            return None
        return CollectionResolver(conn)

    @staticmethod
    def _resolve_settings() -> Settings:
        """Load settings resolved for the default database."""
        from quarry.config import Settings  # noqa: PLC0415

        return Settings.load().resolve_db_paths(None)
