"""The ``.punt-labs/quarry/enabled`` marker that signals repo enablement."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["EnabledMarker"]


@final
class EnabledMarker:
    """The presence marker for quarry being enabled in a repo.

    quarry is enabled in a repo when ``<repo>/.punt-labs/quarry/enabled``
    exists (tool-enable-disable.md § 2.7). ``enable`` writes it; ``disable``
    deletes it. This is a distinct signal from directory presence — the
    vendored guide persists after ``disable`` (the dormant state, § 2.9), so
    directory presence cannot mean "enabled." Both hook gates and ``punt
    audit`` read this one file. Per § 2.11 the marker is a commit point:
    :class:`quarry.enablement.Enablement` writes it only after the repo
    ``@.punt-labs/quarry/CLAUDE.md`` import is effective, so marker present ⇒
    import present. The reverse can differ mid-operation (import written, marker
    not) — the recoverable state a re-run reconciles.
    """

    __slots__ = ("_path",)

    _path: Path

    _RELATIVE = (".punt-labs", "quarry", "enabled")

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._path = root.joinpath(*cls._RELATIVE)
        return self

    @property
    def path(self) -> Path:
        """Return the marker file path."""
        return self._path

    def is_present(self) -> bool:
        """Return whether the marker exists (quarry is enabled here)."""
        return self._path.is_file()

    def write(self) -> bool:
        """Create the marker at mode ``0644``; return whether it was created.

        A present marker is left untouched — no mtime bump — and ``False`` is
        returned, so re-enabling is a true idempotent no-op the caller can
        report as such. On the creation path the mode is set by an explicit
        ``chmod``: ``touch``'s create mode is masked by the process umask, so a
        restrictive umask would otherwise yield ``0600`` instead of the ``0644``
        both the hook gates and ``punt audit`` expect; that path returns
        ``True``.
        """
        if self._path.is_file():
            return False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch()
        self._path.chmod(0o644)
        return True

    def remove(self) -> bool:
        """Delete the marker; return whether a marker was present to remove.

        Leaves the rest of ``.punt-labs/quarry/`` in place — ``disable`` removes
        only the signal it wrote, never the dormant vendored guide (§ 2.9).
        """
        if not self._path.is_file():
            return False
        self._path.unlink()
        return True
