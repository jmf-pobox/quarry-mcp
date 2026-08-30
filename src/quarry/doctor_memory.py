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
        configured for *cwd* or when the database is empty; warns when the
        handle is set and the corpus has any rows AND the handle has none.
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
        handles: Counter[str] = Counter()
        types: Counter[str] = Counter()
        collections: Counter[str] = Counter()
        for row in rows:
            handle = str(row.get("agent_handle", ""))
            mtype = str(row.get("memory_type", ""))
            collection = str(row.get("collection", ""))
            if handle:
                handles[handle] += 1
            if mtype in _MEMORY_TYPES:
                types[mtype] += 1
            if collection:
                collections[collection] += 1
        return (
            "; ".join(
                part
                for part in (
                    MemoryDiagnostics._render("memory", handles),
                    MemoryDiagnostics._render("types", types),
                    MemoryDiagnostics._render("collections", collections),
                )
                if part
            )
            or "no agent memory yet"
        )

    @staticmethod
    def _render(label: str, counts: Counter[str]) -> str:
        """Render one group as ``label: k1=v1 k2=v2`` in descending count order."""
        if not counts:
            return ""
        ordered = counts.most_common()
        return f"{label}: " + " ".join(f"{k}={v}" for k, v in ordered)

    @staticmethod
    def _handle_counts(db_path: Path, handle: str) -> tuple[int, int]:
        """Return ``(rows_for_handle, total_rows)`` for the identity_active check."""
        rows = MemoryDiagnostics._scan_columns(db_path, ["agent_handle"])
        total = len(rows)
        matches = sum(1 for r in rows if str(r.get("agent_handle", "")) == handle)
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
