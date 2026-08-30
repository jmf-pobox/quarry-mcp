"""Memory-corpus doctor checks: per-handle counts and identity activation.

Reports the shape of the agent-memory corpus (rows per ``agent_handle``, per
``memory_type``, per ``collection``) and warns when an ethos identity is active
in the current repo but has zero rows in the database — the "my ethos config
resolves but PreCompact never fired" failure mode.
"""

from __future__ import annotations

from collections import Counter
from functools import partial
from pathlib import Path
from typing import final

from quarry.ethos_handle import EthosConfig
from quarry.results import CheckResult

# The four memory_type values RrfFusion decays; the same set names the types
# the corpus check counts (see quarry.retrieval.fusion._DECAYABLE_TYPES).
_MEMORY_TYPES: frozenset[str] = frozenset(
    {"fact", "observation", "opinion", "procedure"}
)


@final
class MemoryDiagnostics:
    """Doctor checks for the agent-memory corpus and identity activation."""

    __slots__ = ()

    @staticmethod
    def corpus(db_path: Path) -> CheckResult:
        """Report per-handle, per-type, and per-collection row counts.

        Informational only (``required=False``). Rows with empty ``agent_handle``
        are excluded from the handle and type tallies but every collection is
        reported so the operator sees the split between ``memory-*`` and
        capture buckets.
        """
        result = partial(CheckResult, name="Memory corpus", required=False)
        if not db_path.exists():
            return result(passed=True, message="no data yet")
        try:
            summary = MemoryDiagnostics._summarize(db_path)
        except (RuntimeError, OSError, ValueError) as exc:
            return result(passed=False, message=f"check failed: {exc}")
        return result(passed=True, message=summary)

    @staticmethod
    def identity_active(cwd: str, db_path: Path) -> CheckResult:
        """Warn when the resident ethos handle exists but owns zero memory rows.

        Warning-only (``required=False``). Passes silently when no identity is
        configured for *cwd* or when the corpus holds no memory rows (knowledge
        chunks with empty ``agent_handle`` do not count); warns when the handle
        is set and other agents own memory rows but this handle owns none.
        """
        result = partial(CheckResult, name="Memory identity", required=False)
        handle = EthosConfig.agent_handle_at(cwd)
        if not handle:
            return result(passed=True, message="no ethos identity active")
        if not db_path.exists():
            return result(passed=True, message=f"identity '{handle}' active")
        try:
            rows_for_handle, total_rows = MemoryDiagnostics._handle_counts(
                db_path, handle
            )
        except (RuntimeError, OSError, ValueError) as exc:
            return result(passed=False, message=f"check failed: {exc}")
        if total_rows == 0:
            return result(passed=True, message=f"identity '{handle}' active")
        if rows_for_handle == 0:
            return result(
                passed=False,
                message=(
                    f"identity '{handle}' active in this repo but has zero "
                    "memory rows; check that ethos config resolves and "
                    "PreCompact fires"
                ),
            )
        return result(
            passed=True,
            message=f"identity '{handle}' has {rows_for_handle} memory rows",
        )

    @staticmethod
    def _summarize(db_path: Path) -> str:
        """Return the one-line summary printed as the ``corpus`` message."""
        rows = MemoryDiagnostics._scan_columns(
            db_path, ["agent_handle", "memory_type", "collection"]
        )
        if not rows:
            return "no chunks yet"
        handles, types, collections = MemoryDiagnostics._tally(rows)
        parts = (
            MemoryDiagnostics._render(label, counts)
            for label, counts in (
                ("memory", handles),
                ("types", types),
                ("collections", collections),
            )
        )
        return "; ".join(part for part in parts if part) or "no agent memory yet"

    @staticmethod
    def _tally(
        rows: list[dict[str, object]],
    ) -> tuple[Counter[str], Counter[str], Counter[str]]:
        """Return ``(handles, types, collections)`` counters over *rows*.

        Handle and type tallies count agent-owned rows only; a knowledge chunk
        (empty handle) may carry a ``memory_type`` tag from ingestion but is
        not a memory row and must not inflate the type count. Collections are
        tallied for every non-empty value so the operator sees the full split.
        """
        handles: Counter[str] = Counter()
        types: Counter[str] = Counter()
        collections: Counter[str] = Counter()
        for row in rows:
            handle = str(row.get("agent_handle") or "")
            collection = str(row.get("collection") or "")
            if handle:
                handles[handle] += 1
                mtype = str(row.get("memory_type") or "")
                if mtype in _MEMORY_TYPES:
                    types[mtype] += 1
            if collection:
                collections[collection] += 1
        return handles, types, collections

    @staticmethod
    def _render(label: str, counts: Counter[str]) -> str:
        """Render one group as ``label: k1=v1 k2=v2`` in descending count order."""
        if not counts:
            return ""
        return f"{label}: " + " ".join(f"{k}={v}" for k, v in counts.most_common())

    @staticmethod
    def _handle_counts(db_path: Path, handle: str) -> tuple[int, int]:
        """Return ``(rows_for_handle, total_memory_rows)`` for identity_active.

        ``total_memory_rows`` counts only rows with a non-empty ``agent_handle``
        — knowledge chunks are corpus, not memory, and must not falsify the
        "corpus has memory for someone else" signal.
        """
        rows = MemoryDiagnostics._scan_columns(db_path, ["agent_handle"])
        handles = [str(r.get("agent_handle") or "") for r in rows]
        total = sum(1 for h in handles if h)
        matches = sum(1 for h in handles if h == handle)
        return (matches, total)

    @staticmethod
    def _scan_columns(db_path: Path, columns: list[str]) -> list[dict[str, object]]:
        """Scan the chunks table for *columns*, returning ``[]`` when empty.

        The single point that opens the LanceDB facade — both checks funnel
        through here so the "no table yet" signal is a single empty list, not
        two independent conditionals. The import stays lazy so this
        client-reachable module never pulls the engine onto the hot path
        (see the `.importlinter` exception for `quarry.doctor_memory`).
        """
        from quarry.db.facade import Database  # noqa: PLC0415
        from quarry.db.schema import TABLE_NAME  # noqa: PLC0415

        database = Database.connect(db_path)
        if TABLE_NAME not in database.db.list_tables().tables:
            return []
        table = database.db.open_table(TABLE_NAME)
        return list(table.search().limit(1_000_000).select(columns).to_list())
