"""Registry-backed doctor checks: sync recency, directory health, enable status."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self, final

from quarry.results import CheckResult

_STALE_SECONDS = 24 * 3600


@final
@dataclass(frozen=True, slots=True)
class SyncRecency:
    """The freshest sync across collections — an ingest-pipeline liveness signal.

    Reports the NEWEST sync (the minimum age), not the oldest.  A quiet
    reference collection that never changes must not headline the check, so the
    check fails only when even the freshest collection is over 24h stale —
    nothing has ingested in a day, so the pipeline is dead.  A registry with no
    sync yet is surfaced as info, never a hard failure.
    """

    count: int
    newest_age: float | None

    @classmethod
    def from_registry(cls, registry_path: Path) -> Self:
        """Snapshot the freshest sync across every registered collection."""
        from quarry.sync_registry import SyncRegistry  # noqa: PLC0415

        with contextlib.closing(SyncRegistry(registry_path)) as conn:
            regs = conn.list_registrations()
            now = datetime.now(UTC)
            newest_age: float | None = None
            for reg in regs:
                row = conn.execute(
                    "SELECT MAX(ingested_at) FROM files WHERE collection = ?",
                    (reg.collection,),
                ).fetchone()
                last = row[0] if row else None
                if last is None:
                    continue
                age = (now - datetime.fromisoformat(last)).total_seconds()
                if newest_age is None or age < newest_age:
                    newest_age = age
        return cls(len(regs), newest_age)

    def result(self) -> CheckResult:
        """Return the doctor CheckResult for this recency snapshot."""
        if self.count == 0:
            return self._passed("no registrations")
        if self.newest_age is None:
            return self._passed(f"{self.count} collections, none synced yet")
        phrase = self._phrase(self.newest_age)
        headline = f"{self.count} collections, newest sync {phrase}"
        if self.newest_age > _STALE_SECONDS:
            return CheckResult(
                name="Sync",
                passed=False,
                message=f"{headline} (>24h stale)",
                required=False,
            )
        return self._passed(headline)

    @staticmethod
    def _passed(message: str) -> CheckResult:
        return CheckResult(name="Sync", passed=True, message=message, required=False)

    @staticmethod
    def _phrase(age: float) -> str:
        """Return *age* seconds as a coarse ``Xh ago`` / ``Ym ago`` phrase."""
        hours = int(age // 3600)
        return f"{hours}h ago" if hours > 0 else f"{int(age // 60)}m ago"


@final
class SyncDiagnostics:
    """Doctor checks over the sync registry: recency, directory health, enable state.

    Each check reads the registry, tolerates a missing or broken one with a
    fail-closed ``CheckResult`` rather than an exception, and never leaks a
    connection.  These moved out of ``doctor.py`` so the diagnostics god module
    no longer owns registry access directly.
    """

    __slots__ = ()

    @staticmethod
    def recency(registry_path: Path) -> CheckResult:
        """Report whether the ingest pipeline has synced anything recently."""
        if not registry_path.exists():
            return CheckResult(
                name="Sync", passed=True, message="no registrations", required=False
            )
        try:
            return SyncRecency.from_registry(registry_path).result()
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                name="Sync",
                passed=False,
                message=f"registry error: {exc}",
                required=False,
            )

    @staticmethod
    def directories(registry_path: Path) -> CheckResult:
        """Verify registered sync directories still exist on disk."""
        from quarry.sync_registry import SyncRegistry  # noqa: PLC0415

        name = "Sync directories"
        if not registry_path.exists():
            return CheckResult(
                name=name, passed=True, message="no registrations", required=False
            )
        try:
            with contextlib.closing(SyncRegistry(registry_path)) as conn:
                regs = conn.list_registrations()
                if not regs:
                    return CheckResult(
                        name=name,
                        passed=True,
                        message="no registrations",
                        required=False,
                    )
                missing = [
                    reg.collection for reg in regs if not Path(reg.directory).is_dir()
                ]
                if missing:
                    names = ", ".join(missing[:3])
                    return CheckResult(
                        name=name,
                        passed=False,
                        message=f"{len(missing)} missing: {names}",
                        required=False,
                    )
                return CheckResult(
                    name=name,
                    passed=True,
                    message=f"{len(regs)} directories OK",
                    required=False,
                )
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                name=name,
                passed=False,
                message=f"registry error: {exc}",
                required=False,
            )

    @staticmethod
    def enable_status(registry_path: Path, cwd: str) -> CheckResult:
        """Report whether *cwd* has quarry enabled and its config is present."""
        from quarry.collection_resolver import CollectionResolver  # noqa: PLC0415
        from quarry.sync_registry import SyncRegistry  # noqa: PLC0415

        conn = SyncRegistry(registry_path)
        try:
            collection = (
                CollectionResolver(conn).covering_collection(cwd) if cwd else None
            )
        finally:
            conn.close()
        if collection is None:
            return CheckResult(
                name="Enable status",
                passed=False,
                message="not enabled -- run 'quarry enable'",
                required=False,
            )
        captures = f"{collection}-captures"
        config_path = Path(cwd) / ".punt-labs" / "quarry" / "config.md"
        config_exists = config_path.is_file()
        parts = [f"collection: {collection}, captures: {captures}"]
        if not config_exists:
            parts.append("config.md missing (run 'quarry enable')")
        return CheckResult(
            name="Enable status",
            passed=config_exists,
            message=", ".join(parts),
            required=False,
        )
