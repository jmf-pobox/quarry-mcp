"""Compose the repo-scoped CLAUDE.md enable/disable steps behind one object."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from quarry.claude_import import ClaudeMdImport
from quarry.enabled_marker import EnabledMarker
from quarry.guidance import REPO_IMPORT_LINE, Guidance

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["DisablementResult", "Enablement", "EnablementResult"]


@dataclass(frozen=True, slots=True)
class EnablementResult:
    """What the § 2.3 enable steps did to a repo's CLAUDE.md."""

    guide_deposited: bool
    enabled_marker_written: bool
    import_registered: bool


@dataclass(frozen=True, slots=True)
class DisablementResult:
    """What the § 2.3 disable steps did — the guide is left dormant (§ 2.9)."""

    import_pruned: bool
    enabled_marker_removed: bool


@final
class Enablement:
    """Turn quarry's repo-scoped CLAUDE.md guidance composition on and off.

    Owns the ordering of the tool-enable-disable.md § 2.3 steps so ``enable`` /
    ``disable`` stay a single call rather than loose orchestration inside the
    capture flow: deposit the vendored guide, write the ``enabled`` marker, and
    register the one bare ``@``-import line — and the symmetric teardown. The
    marker ⟺ import-line biconditional (§ 2.11) is this object's invariant:
    ``enable`` writes both, ``disable`` removes both.
    """

    __slots__ = ("_guidance", "_import", "_marker")

    _guidance: Guidance
    _marker: EnabledMarker
    _import: ClaudeMdImport

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._guidance = Guidance(root)
        self._marker = EnabledMarker(root)
        self._import = ClaudeMdImport(root / "CLAUDE.md")
        return self

    def enable(self) -> EnablementResult:
        """Deposit the guide, write the marker, register the import.

        The deposit and the marker are unconditional (wholesale-overwrite
        determinism, § 2.2); the register reports whether it changed the host
        CLAUDE.md.
        """
        self._guidance.deposit()
        self._marker.write()
        import_registered = self._import.register(REPO_IMPORT_LINE)
        return EnablementResult(
            guide_deposited=True,
            enabled_marker_written=True,
            import_registered=import_registered,
        )

    def disable(self) -> DisablementResult:
        """Prune the import line and delete the marker; leave the guide dormant."""
        import_pruned = self._import.prune(REPO_IMPORT_LINE)
        enabled_marker_removed = self._marker.remove()
        return DisablementResult(
            import_pruned=import_pruned,
            enabled_marker_removed=enabled_marker_removed,
        )
