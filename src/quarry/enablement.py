"""Compose the repo-scoped CLAUDE.md enable/disable steps behind one object."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from quarry.claude_import import ClaudeMdImport
from quarry.enabled_marker import EnabledMarker
from quarry.enablement_result import DisablementResult, EnablementResult
from quarry.file_lock import FileLock
from quarry.gitignore import CapturesGitignore
from quarry.guidance import REPO_IMPORT_LINE, Guidance

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["DisablementResult", "Enablement", "EnablementResult"]


@final
class Enablement:
    """Turn quarry's repo-scoped CLAUDE.md guidance composition on and off.

    Owns the ordering of the tool-enable-disable.md § 2.3 steps: deposit the
    vendored guide, register the one bare ``@``-import line, write the
    ``enabled`` marker, and ensure the repo's ``.gitignore`` excludes
    quarry's captures path. ``disable`` reverses the first three; the
    ``.gitignore`` line is additive-only, since an ignore rule the user may
    keep for other reasons is not ours to prune, and its absence plays no
    part in the § 2.11 invariant below.

    The enforced invariant (§ 2.11) is one-directional: marker present ⇒
    import present. Both operations make the near-infallible marker their
    commit point — ``enable`` registers the import before touching the
    marker, ``disable`` removes the marker before pruning the import — so a
    mid-operation failure can only leave import-present + marker-absent, the
    recoverable state a re-run reconciles, never marker-present +
    import-absent (a marker advertising guidance that is not wired in).

    A single :class:`FileLock` on the CLAUDE.md path wraps the whole
    register+marker (and marker+prune) sequence so the marker change and the
    import edit commit atomically w.r.t. a concurrent op — without it, a
    concurrent ``enable``/``disable`` could interleave and strand the
    marker. The lock is reentrant, so ``register``/``prune`` re-acquiring it
    for the edit itself share the one hold.
    """

    __slots__ = ("_gitignore", "_guidance", "_import", "_marker")

    _guidance: Guidance
    _marker: EnabledMarker
    _import: ClaudeMdImport
    _gitignore: CapturesGitignore

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._guidance = Guidance(root)
        self._marker = EnabledMarker(root)
        self._import = ClaudeMdImport(root / "CLAUDE.md")
        self._gitignore = CapturesGitignore(root)
        return self

    def enable(self) -> EnablementResult:
        """Deposit the guide, register the import, write the marker, ensure the ignore.

        Register, marker, and the ``.gitignore`` ensure each report whether
        they changed anything, so an idempotent re-enable returns all three
        booleans ``False``. Register runs before the near-infallible marker
        write so a register failure leaves neither present, never the
        marker-without-import state § 2.11 forbids — the marker is the
        commit point. Register and marker share one :class:`FileLock` so a
        concurrent ``disable`` cannot strand the marker without its import.

        The ``.gitignore`` ensure locks its own sibling file
        (:class:`~quarry.gitignore.CapturesGitignore`), unrelated to that
        invariant, and runs last so an idempotent re-enable still backfills a
        missing exclusion on a repo enabled before this step existed.
        """
        self._guidance.deposit()
        with FileLock(self._import.path):
            import_registered = self._import.register(REPO_IMPORT_LINE)
            enabled_marker_written = self._marker.write()
        gitignore_ensured = self._gitignore.ensure()
        return EnablementResult(
            guide_deposited=True,
            enabled_marker_written=enabled_marker_written,
            import_registered=import_registered,
            gitignore_ensured=gitignore_ensured,
        )

    def disable(self) -> DisablementResult:
        """Remove the marker and prune the import atomically; leave the guide dormant.

        The remove runs before the fallible prune (read + atomic temp+rename) so
        a prune failure leaves marker-absent + import-present — the recoverable
        state — never the marker-present + import-absent state the § 2.11
        biconditional forbids. This mirrors ``enable``, where the near-infallible
        marker is likewise the commit point.

        Both run under one :class:`FileLock` so a concurrent ``enable`` cannot
        interleave its marker write with this prune and strand the marker.

        A :class:`~quarry.safe_paths.SafeRepoPath` refusal (a hostile symlinked
        ancestor) is caught so it cannot abort before the prune and strand the
        ``@``-import a prior deregister already acted on. The refused marker is
        not a real in-repo marker (``is_present()`` is ``False``), so treating it
        as absent and pruning anyway keeps the recoverable invariant. A genuine
        unlink error still propagates, leaving the recoverable marker-present +
        import-present enabled state, never marker-present + import-absent.
        """
        with FileLock(self._import.path):
            try:
                enabled_marker_removed = self._marker.remove()
            except ValueError:
                enabled_marker_removed = False
            import_pruned = self._import.prune(REPO_IMPORT_LINE)
        return DisablementResult(
            import_pruned=import_pruned,
            enabled_marker_removed=enabled_marker_removed,
        )
