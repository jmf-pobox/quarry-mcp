"""File discovery for directory sync: walk, filter, hash."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Final, Self, final

import pathspec

from quarry.scratch_paths import ScratchGuard

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

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

_HASH_CHUNK_SIZE: Final[int] = 1 << 20  # 1 MiB


@final
class FileDiscovery:
    """Discover indexable files under a directory, respecting ignore rules."""

    __slots__ = (
        "_directory",
        "_excluded",
        "_guard",
        "_root_resolved",
        "_walk_complete",
    )

    _directory: Path
    _root_resolved: Path | None
    _guard: ScratchGuard
    _excluded: bool
    _walk_complete: bool

    def __new__(cls, directory: Path) -> Self:
        self = super().__new__(cls)
        self._directory = directory
        self._guard = ScratchGuard()
        try:
            self._root_resolved = directory.resolve(strict=True)
        except (OSError, RuntimeError):
            logger.warning("Cannot resolve registered root: %s", directory)
            self._root_resolved = None
        # A temp/scratch root (OS temp like ``/private/tmp`` OR a repo's own
        # ``.tmp``) is never a document tree: watching it OCR-storms everything
        # dropped there.  Refused up front so both the bulk scan and the live
        # path treat it as empty.
        self._excluded = self._root_resolved is not None and self._guard.refuses_root(
            self._root_resolved
        )
        if self._excluded:
            logger.debug("Skipping scratch/temp root: %s", self._root_resolved)
        self._walk_complete = True
        return self

    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def root_available(self) -> bool:
        """Whether the registered root resolved and is not a refused scratch root.

        When ``False``, :meth:`discover` returns empty for a reason OTHER than
        "every file was deleted" (the root could not be resolved, or is a
        refused temp/scratch tree). Callers that compute deletions from an empty
        discovery MUST fail closed on this — otherwise a transient root blip
        reads as a full collection wipe.
        """
        return self._root_resolved is not None and not self._excluded

    @property
    def discovery_reliable(self) -> bool:
        """Whether the last :meth:`discover` saw a complete, resolvable tree.

        ``False`` when the root could not be resolved / is a refused scratch tree
        (:attr:`root_available`) OR the ``os.walk`` enumeration hit an error
        (permission loss, ``ESTALE``, or the directory vanishing mid-walk) — any
        of which yields an empty or partial discovery for a reason OTHER than
        deletion. Callers computing deletions MUST fail closed on this: an
        incomplete disk view is not evidence that files were removed. Valid only
        after :meth:`discover` has run.
        """
        return self.root_available and self._walk_complete

    def _note_walk_error(self, exc: OSError) -> None:
        """``os.walk`` onerror hook: a dir could not be listed → walk incomplete."""
        logger.warning("Directory walk error under %s: %s", self._directory, exc)
        self._walk_complete = False

    def discover(self, extensions: frozenset[str]) -> list[Path]:
        """Recursively find files matching *extensions* under the directory.

        Respects ``.gitignore`` (at every level), ``.quarryignore``, the
        :class:`ScratchGuard` always-skip names (``venv``, ``node_modules``,
        ``htmlcov``…), and the glob patterns in ``_DEFAULT_IGNORE_PATTERNS``.
        Skips dotfiles, macOS resource forks (``._*``), and files inside
        hidden directories (``.Trash``, ``.git``, etc.).

        Symlinks whose target resolves outside the directory are dropped and
        logged as a warning.

        Returns absolute paths, sorted for deterministic order.
        """
        if self._root_resolved is None or self._excluded:
            return []

        self._walk_complete = True
        root_spec = self.load_ignore_spec()
        result: list[Path] = []
        for dirpath_str, dirnames, filenames in os.walk(
            self._directory, onerror=self._note_walk_error
        ):
            dirpath = Path(dirpath_str)
            local_spec = (
                self._read_local_ignore(dirpath) if dirpath != self._directory else None
            )
            dirnames[:] = self._keep_dirs(dirpath, dirnames, root_spec, local_spec)
            result.extend(
                self._keep_files(dirpath, filenames, extensions, root_spec, local_spec)
            )
        return result

    def _keep_dirs(
        self,
        dirpath: Path,
        dirnames: list[str],
        root_spec: pathspec.PathSpec[pathspec.pattern.Pattern],
        local_spec: pathspec.PathSpec[pathspec.pattern.Pattern] | None,
    ) -> list[str]:
        """Return the child dirs to descend: not hidden, scratch, or ignored."""
        rel_dir = dirpath.relative_to(self._directory)
        return sorted(
            d
            for d in dirnames
            if not d.startswith(".")
            and not self._guard.is_skip_name(d)
            and not root_spec.match_file(str(rel_dir / d) + "/")
            and (local_spec is None or not local_spec.match_file(d + "/"))
        )

    def _keep_files(
        self,
        dirpath: Path,
        filenames: list[str],
        extensions: frozenset[str],
        root_spec: pathspec.PathSpec[pathspec.pattern.Pattern],
        local_spec: pathspec.PathSpec[pathspec.pattern.Pattern] | None,
    ) -> Iterator[Path]:
        """Yield the absolute path of each indexable file directly in *dirpath*."""
        for filename in sorted(filenames):
            filepath = dirpath / filename
            if filename.startswith((".", "._")):
                continue
            if filepath.suffix.lower() not in extensions:
                continue
            rel_path = str(filepath.relative_to(self._directory))
            if root_spec.match_file(rel_path):
                continue
            if local_spec is not None and local_spec.match_file(filename):
                continue
            if filepath.is_symlink() and not self._symlink_inside_root(filepath):
                continue
            yield filepath.absolute()

    def is_indexable(self, path: Path, extensions: frozenset[str]) -> bool:
        """Return whether *path* would be indexed by :meth:`discover` (live == bulk).

        Applies discover's rules to ONE path so a live watch edit and a bulk scan
        agree: the file's real path must resolve *inside* the real root (a symlink
        whose target escapes the tree is rejected — never indexed, closing the
        path-escape leak), the suffix must be supported, no path segment may be
        hidden, and neither the root nor any per-directory ignore spec may match.
        """
        if self._root_resolved is None or self._excluded:
            return False
        if not self._resolves_inside(path, self._root_resolved):
            return False
        if path.suffix.lower() not in extensions:
            return False
        try:
            rel = path.relative_to(self._directory)
        except ValueError:
            return False
        parts = rel.parts
        if any(part.startswith((".", "._")) for part in parts):
            return False
        if self._guard.skips_below_root(rel):
            return False
        if self.load_ignore_spec().match_file(str(rel)):
            return False
        return not self._nested_ignored(parts)

    @staticmethod
    def _resolves_inside(path: Path, root: Path) -> bool:
        """Whether *path* resolves inside *root* (symlink-escape guard)."""
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError):
            return False
        try:
            resolved.relative_to(root)
        except ValueError:
            return False
        return True

    def _nested_ignored(self, parts: tuple[str, ...]) -> bool:
        """Whether a per-directory ``.gitignore`` along *parts* excludes the file.

        Mirrors :meth:`discover`'s walk: each intermediate directory's own
        ``.gitignore`` governs its direct child (a trailing ``/`` for a
        subdirectory, none for the final file).  The root is covered by
        :meth:`load_ignore_spec`, so it is skipped here.
        """
        current = self._directory
        last = len(parts) - 1
        for index, segment in enumerate(parts):
            if current != self._directory:
                local = self._read_local_ignore(current)
                marker = "" if index == last else "/"
                if local is not None and local.match_file(segment + marker):
                    return True
            current = current / segment
        return False

    def is_deletable(self, path: Path, extensions: frozenset[str]) -> bool:
        """Return whether a REMOVED *path* names a document worth a delete job.

        A delete reads no content (no symlink-escape risk) and
        ``delete_document`` is idempotent, so this is a purely lexical check —
        the file is already gone and cannot be resolved.  A false accept is a
        harmless no-op; the disk-vs-registry reconcile is the robust backstop.
        """
        if (
            self._root_resolved is None
            or self._excluded
            or path.suffix.lower() not in extensions
        ):
            return False
        try:
            rel = path.relative_to(self._directory)
        except ValueError:
            return False
        if self._guard.skips_below_root(rel):
            return False
        return not any(part.startswith((".", "._")) for part in rel.parts)

    @staticmethod
    def content_hash(path: Path) -> str:
        """Return a fast content hash of *path* for change detection.

        Uses ``blake2b`` with a 16-byte digest (128 bits).
        """
        h = hashlib.blake2b(digest_size=16)
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
                h.update(chunk)
        return h.hexdigest()

    def load_ignore_spec(self) -> pathspec.PathSpec[pathspec.pattern.Pattern]:
        """Build a PathSpec from ``.gitignore``, ``.quarryignore``, and defaults."""
        lines: list[str] = list(_DEFAULT_IGNORE_PATTERNS)
        for name in (".gitignore", ".quarryignore"):
            lines.extend(self._read_ignore_lines(self._directory / name))
        return pathspec.PathSpec.from_lines("gitignore", lines)

    @staticmethod
    def _read_ignore_lines(path: Path) -> list[str]:
        """Return an ignore file's lines, or ``[]`` when absent/non-regular/unreadable.

        ``is_file()`` inside the ``try`` (not before it) keeps a FIFO or a symlink
        to a character device named ``.gitignore`` from blocking ``read_text()``
        forever, while the ``OSError`` guard keeps a raced deletion — present at
        the check, gone at the read — from aborting the whole ``discover()`` walk
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

    @staticmethod
    def _read_local_ignore(
        dirpath: Path,
    ) -> pathspec.PathSpec[pathspec.pattern.Pattern] | None:
        """Read ``.gitignore`` from *dirpath*, returning a PathSpec or None."""
        lines = FileDiscovery._read_ignore_lines(dirpath / ".gitignore")
        if not lines:
            return None
        return pathspec.PathSpec.from_lines("gitignore", lines)

    def _symlink_inside_root(self, link: Path) -> bool:
        """Return True iff *link*'s target resolves inside the root."""
        if self._root_resolved is None:
            return False
        try:
            target = link.resolve(strict=True)
        except (OSError, RuntimeError):
            logger.warning("Skipping unresolvable symlink: %s", link)
            return False
        try:
            target.relative_to(self._root_resolved)
        except ValueError:
            logger.warning(
                "Skipping symlink %s that escapes registered root: %s",
                link,
                target,
            )
            return False
        return True
