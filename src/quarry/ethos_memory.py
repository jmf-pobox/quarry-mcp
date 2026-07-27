"""Bootstrap per-identity quarry memory in the global ethos identities tree."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Self, final

from yaml import YAMLError

__all__ = ["EthosMemoryBootstrap", "EthosMemoryResult"]

_GLOBAL_IDENTITIES = Path.home() / ".punt-labs" / "ethos" / "identities"


@dataclass(frozen=True, slots=True)
class EthosMemoryResult:
    """Outcome of an ethos-memory bootstrap, per identity handle.

    Replaces the anonymous 5-tuple the bootstrap used to return, so callers read
    named fields rather than positional slots. ``skipped`` is True when the
    global identities directory is absent (ethos not installed).
    """

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    already_set: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: bool = False

    @property
    def memory_collections(self) -> list[str]:
        """Return the memory-collection name created for each new handle."""
        return [f"memory-{handle}" for handle in self.created]


@final
class EthosMemoryBootstrap:
    """Create each identity's ``quarry.yaml`` ext file and its session_context.

    Reads only the global identities directory (repo-level identities are
    read-only). A handle lands in ``failed`` when its session_context write
    raised an I/O or YAML error — the useful part never landed, so the caller
    must not report unqualified success for it. Non-OSError/YAMLError exceptions
    are real bugs and propagate.
    """

    __slots__ = ("_identities",)

    _identities: Path

    def __new__(cls, identities: Path | None = None) -> Self:
        # None means "use the configured global identities dir" — read at call
        # time (not bound as a default) so a test can patch the module global.
        self = super().__new__(cls)
        self._identities = identities if identities is not None else _GLOBAL_IDENTITIES
        return self

    def run(self) -> EthosMemoryResult:
        """Bootstrap every identity's memory ext; return the per-handle outcome."""
        if not self._identities.is_dir():
            return EthosMemoryResult(skipped=True)

        created: list[str] = []
        updated: list[str] = []
        already_set: list[str] = []
        failed: list[str] = []
        for identity_file in sorted(self._identities.glob("*.yaml")):
            handle = identity_file.stem
            quarry_yaml = self._ensure_ext(handle, created)
            self._write_context(quarry_yaml, handle, updated, already_set, failed)

        return EthosMemoryResult(
            created=created,
            updated=updated,
            already_set=already_set,
            failed=failed,
            skipped=False,
        )

    def _ensure_ext(self, handle: str, created: list[str]) -> Path:
        """Create the identity's ``quarry.yaml`` ext with a memory collection."""
        ext_dir = self._identities / f"{handle}.ext"
        ext_dir.mkdir(exist_ok=True)
        quarry_yaml = ext_dir / "quarry.yaml"
        if not quarry_yaml.exists():
            quarry_yaml.write_text(
                f"memory_collection: memory-{handle}\n", encoding="utf-8"
            )
            created.append(handle)
        return quarry_yaml

    @staticmethod
    def _write_context(
        quarry_yaml: Path,
        handle: str,
        updated: list[str],
        already_set: list[str],
        failed: list[str],
    ) -> None:
        """Write session_context, sorting the handle into the right bucket."""
        from quarry.doctor import (  # noqa: PLC0415
            _write_ethos_ext_session_context,  # pyright: ignore[reportPrivateUsage]
        )

        try:
            result = _write_ethos_ext_session_context(quarry_yaml, handle)
        except (OSError, YAMLError, UnicodeDecodeError):
            # UnicodeDecodeError (a ValueError, not an OSError) fires on a
            # non-UTF8/corrupt identity file — record the handle and continue
            # rather than crash enable; a real bug still propagates.
            failed.append(handle)
            return
        if result == "updated":
            updated.append(handle)
        elif result == "already_set":
            already_set.append(handle)
