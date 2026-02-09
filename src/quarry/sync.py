from __future__ import annotations

from pathlib import Path


def discover_files(
    directory: Path,
    extensions: frozenset[str],
) -> list[Path]:
    """Recursively find files matching *extensions* under *directory*.

    Returns absolute resolved paths, sorted for deterministic order.
    """
    return sorted(
        child.resolve()
        for child in directory.rglob("*")
        if child.is_file() and child.suffix.lower() in extensions
    )
