"""The gitignore-dialect ignore/prune rules shared by discovery and watch scheduling.

Both a bulk directory scan (:class:`~quarry.sync_discovery.FileDiscovery`) and
the live watch scheduler (:mod:`~quarry.daemon.fs_watchdog`, by way of
``FileDiscovery.iter_watchable_dirs``/``is_watchable_dir``) must agree on
which directories and files are ignored — ``.gitignore`` at every level,
``.quarryignore`` at the root, the built-in scratch defaults, and hidden-dir
skipping.  :class:`FileDiscovery` composes ONE :class:`IgnoreRules` per
registered root rather than re-reading ignore files and re-matching glob
patterns itself, so there is exactly one place that owns "is this name
ignored" — pulled out of :mod:`~quarry.sync_discovery` (Extract Class) once
that module's own concerns (walking, hashing, per-file live checks) started
crowding the ignore-spec bookkeeping out.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final, Self, final

import pathspec

from quarry.scratch_paths import ScratchGuard

logger = logging.getLogger(__name__)

type IgnoreSpec = pathspec.PathSpec[pathspec.pattern.Pattern]

# Glob-style ignores the pathspec engine handles.  Scratch/VCS/build/cache
# *directory names* (``node_modules``, ``.venv``, ``dist``, ``*.egg-info``…) are
# NOT listed here: :class:`~quarry.scratch_paths.ScratchGuard` prunes them by
# name in the walk, so keeping them here too would be duplicated bookkeeping.
_DEFAULT_IGNORE_PATTERNS: Final[list[str]] = [
    "*.pyc",
    ".DS_Store",
    # Defense-in-depth for the captures dir.  The walk already prunes every
    # dot-prefixed directory (``.punt-labs``) before patterns are matched, so
    # this entry is redundant belt-and-braces — it records the intent that
    # scrubbed captures (the daemon's <repo>-captures) must never be folded into
    # the project's MAIN collection by directory sync.
    ".punt-labs/quarry/captures/",
]


@final
class IgnoreRules:
    """Load and apply one directory tree's ignore spec (gitignore dialect)."""

    __slots__ = ("_directory", "_guard")

    _directory: Path
    _guard: ScratchGuard

    def __new__(cls, directory: Path, guard: ScratchGuard) -> Self:
        self = super().__new__(cls)
        self._directory = directory
        self._guard = guard
        return self

    def root_spec(self) -> IgnoreSpec:
        """Build a PathSpec from ``.gitignore``, ``.quarryignore``, and defaults."""
        lines: list[str] = list(_DEFAULT_IGNORE_PATTERNS)
        for name in (".gitignore", ".quarryignore"):
            lines.extend(self._read_ignore_lines(self._directory / name))
        return pathspec.PathSpec.from_lines("gitignore", lines)

    def local_spec(self, dirpath: Path) -> IgnoreSpec | None:
        """Return *dirpath*'s own ``.gitignore`` as a spec, or ``None``.

        ``None`` covers both "the tree root itself" (its ``.gitignore``
        already folds into :meth:`root_spec`) and "no per-directory override
        file present" — a caller need not distinguish the two.
        """
        if dirpath == self._directory:
            return None
        lines = self._read_ignore_lines(dirpath / ".gitignore")
        if not lines:
            return None
        return pathspec.PathSpec.from_lines("gitignore", lines)

    def keeps_dir(
        self,
        rel_dir: Path,
        name: str,
        root_spec: IgnoreSpec,
        local_spec: IgnoreSpec | None,
    ) -> bool:
        """Return whether child directory *name* of *rel_dir* survives pruning.

        The single predicate every consumer of the ignore rules applies to a
        directory — the bulk walk's directory filter and the watch
        scheduler's single-directory check both call this, never their own
        copy of the same four conditions.
        """
        return (
            not name.startswith(".")
            and not self._guard.is_skip_name(name)
            and not root_spec.match_file(str(rel_dir / name) + "/")
            and (local_spec is None or not local_spec.match_file(name + "/"))
        )

    @staticmethod
    def _read_ignore_lines(path: Path) -> list[str]:
        """Return an ignore file's lines, or ``[]`` when absent/non-regular/unreadable.

        ``is_file()`` inside the ``try`` (not before it) keeps a FIFO or a symlink
        to a character device named ``.gitignore`` from blocking ``read_text()``
        forever, while the ``OSError`` guard keeps a raced deletion — present at
        the check, gone at the read — from aborting the whole caller's walk
        (bug class 1/2).
        """
        try:
            if not path.is_file():
                return []
            return path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        except OSError as exc:
            logger.warning("Skipping unreadable ignore file %s: %s", path, exc)
            return []
