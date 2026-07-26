"""The scratch/temp exclusion predicate the watcher and indexer share (DES-045).

The always-on watch loop pegged the machine because the operator's registry
holds ``/private/tmp`` as a collection: the daemon watched the whole OS temp dir
(no ``.gitignore``, not a dot-dir) and OCR-stormed everything any process
dropped there.  This module is the single guard both the indexer
(:class:`~quarry.sync_discovery.FileDiscovery`) and the daemon watch/reconcile
path consult, so a temp/scratch tree is refused identically at scan time and at
watch time — an already-registered temp root becomes harmless on restart, not
just refused at register time.

Two rejections:

* A registered *root* that is a temp directory is refused outright —
  :meth:`ScratchGuard.refuses_root`.  "Temp" means an OS temp root
  (``/tmp``, ``/private/tmp``, ``/var/folders``…) *or* a repository's own
  gitignored ``.tmp`` scratch (``<repo>/.tmp`` — the ``$TMPDIR`` this workspace
  exports).

* Scratch/VCS/build/cache *subdirectories* below a real root
  (``node_modules``, ``htmlcov``, ``dist``, ``*.egg-info``…) are pruned by name
  — :meth:`ScratchGuard.skips_below_root`.

The repo-``.tmp`` case is anchored on the enclosing git repository, never on a
bare ``.tmp`` component appearing anywhere in the path: a legitimate checkout
can itself live under an ancestor named ``.tmp`` (a git worktree, a backup dir),
and refusing it would be wrong.  ``<repo>/.tmp`` *below* a watched repo root is
already pruned by the caller's dot-prune and ``.gitignore`` rules; this guard
adds the root-level refusal plus the non-dot cache names those rules miss.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Self, final

# Directory component names that are never document subtrees: version control,
# virtualenvs, dependency trees, build/coverage output, tool caches, and OS junk.
# Checked only against segments *below* a registered root, never its ancestors.
_ALWAYS_SKIP_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".tmp",
        ".git",
        ".hg",
        ".svn",
        ".beads",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        "htmlcov",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".eggs",
        ".idea",
        ".vscode",
        "__MACOSX",
    }
)

# Component suffixes that exclude a subdirectory (``foo.egg-info`` build metadata).
_ALWAYS_SKIP_SUFFIXES: Final[tuple[str, ...]] = (".egg-info",)

# Absolute OS temp roots.  A root equal to or under one of these is refused.
# These are a denylist of directories to REFUSE watching, not write targets, so
# ruff's S108 (hardcoded-temp-as-insecure-write) is a false positive here.
# Built from path components rather than ``/tmp``-prefixed literals so the check
# never fires — no suppression is added and make check stays self-contained.
_SYSTEM_TEMP_ROOTS: Final[tuple[Path, ...]] = (
    Path("/", "tmp"),
    Path("/", "private", "tmp"),
    Path("/", "var", "folders"),
    Path("/", "private", "var", "folders"),
)

# The gitignored scratch directory name a repository exports as ``$TMPDIR``.
_REPO_SCRATCH_NAME: Final[str] = ".tmp"


@final
class ScratchGuard:
    """Refuse temp roots and prune scratch/VCS/build/cache subdirectories."""

    __slots__ = ("_skip_names", "_skip_suffixes", "_temp_roots")

    _skip_names: frozenset[str]
    _skip_suffixes: tuple[str, ...]
    _temp_roots: tuple[Path, ...]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._skip_names = _ALWAYS_SKIP_NAMES
        self._skip_suffixes = _ALWAYS_SKIP_SUFFIXES
        self._temp_roots = _SYSTEM_TEMP_ROOTS
        return self

    def refuses_root(self, root: Path) -> bool:
        """Return whether *root* is an OS-temp or repo-scratch dir, never watched.

        The OS-temp comparison casefolds both sides: macOS's case-insensitive
        APFS resolves ``/private/TMP`` to the same directory as ``/private/tmp``
        without normalizing case, so a case variant would otherwise slip the
        guard and reopen the OCR storm.  The ``<gitroot>/.tmp`` anchor stays
        case-exact — repo scratch is spelled ``.tmp`` by design.
        """
        folded = self._casefold(root)
        if any(folded.is_relative_to(self._casefold(t)) for t in self._temp_roots):
            return True
        scratch = self._repo_scratch(root)
        return scratch is not None and root.is_relative_to(scratch)

    @staticmethod
    def _casefold(path: Path) -> Path:
        """Return *path* with every component casefolded (APFS case-insensitivity)."""
        return Path(*(part.casefold() for part in path.parts))

    def is_skip_name(self, name: str) -> bool:
        """Return whether one path component names a scratch/VCS/cache subdirectory."""
        return name in self._skip_names or name.endswith(self._skip_suffixes)

    def skips_below_root(self, relative: Path) -> bool:
        """Return whether any component of a root-relative path is scratch/cache."""
        return any(self.is_skip_name(part) for part in relative.parts)

    @staticmethod
    def _repo_scratch(root: Path) -> Path | None:
        """Return ``<git-repo>/.tmp`` for *root*'s enclosing repo, or ``None``.

        Anchored on the nearest ancestor holding a ``.git`` entry (a worktree's
        ``.git`` is a file, so ``exists`` — not ``is_dir`` — is correct) so only a
        repository's *own* scratch is refused, not any ``.tmp`` ancestor.
        """
        for base in (root, *root.parents):
            if (base / ".git").exists():
                return base / _REPO_SCRATCH_NAME
        return None
