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
    capture flow: deposit the vendored guide, register the one bare ``@``-import
    line, and write the ``enabled`` marker — and the symmetric teardown.

    The enforced invariant (§ 2.11) is one-directional: marker present ⇒ import
    present. Both operations make the near-infallible marker their commit point —
    ``enable`` registers the import before touching the marker, ``disable``
    removes the marker before pruning the import — so a mid-operation failure can
    only leave import-present + marker-absent, the recoverable state a re-run
    reconciles, never marker-present + import-absent (a marker advertising
    guidance that is not wired in).
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
        """Deposit the guide, register the import, then write the marker.

        The deposit is unconditional (wholesale-overwrite determinism, § 2.2);
        register and marker each report whether they changed anything, so an
        idempotent re-enable returns both booleans ``False``. Register (flock +
        read + atomic temp+rename) runs before the near-infallible marker touch
        so a register failure leaves neither present, never the
        marker-without-import state the § 2.11 biconditional forbids — the
        marker is the commit point.
        """
        self._guidance.deposit()
        import_registered = self._import.register(REPO_IMPORT_LINE)
        enabled_marker_written = self._marker.write()
        return EnablementResult(
            guide_deposited=True,
            enabled_marker_written=enabled_marker_written,
            import_registered=import_registered,
        )

    def disable(self) -> DisablementResult:
        """Remove the marker, then prune the import; leave the guide dormant.

        The remove runs before the fallible prune (flock + read + atomic
        temp+rename) so a prune failure leaves marker-absent + import-present —
        the recoverable state — never the marker-present + import-absent state
        the § 2.11 biconditional forbids. This mirrors ``enable``, where the
        near-infallible marker is likewise the commit point.
        """
        enabled_marker_removed = self._marker.remove()
        import_pruned = self._import.prune(REPO_IMPORT_LINE)
        return DisablementResult(
            import_pruned=import_pruned,
            enabled_marker_removed=enabled_marker_removed,
        )
