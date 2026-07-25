"""Tests for CollectionNamer: leaf, parent, hash, and counter disambiguation."""

from __future__ import annotations

import hashlib
from pathlib import Path

from quarry.collection_namer import CollectionNamer


def test_prefers_leaf_when_free() -> None:
    name = CollectionNamer(Path("/work/proj"), frozenset()).unique()
    assert name == "proj"


def test_disambiguates_with_parent_then_hash() -> None:
    directory = Path("/work/proj")
    digest = hashlib.sha256(str(directory).encode()).hexdigest()
    taken = frozenset({"proj", "proj-work"})
    name = CollectionNamer(directory, taken).unique()
    assert name == f"proj-{digest[:8]}"


def test_counter_fallback_when_leaf_parent_all_hashes_and_full_digest_taken() -> None:
    # Exhaust every tier: the leaf, leaf-parent, every digest prefix (8..64), AND
    # the full digest.  The counter fallback must still return a name not in taken,
    # making the "never returns a taken name" guarantee absolute (not probabilistic).
    directory = Path("/work/proj")
    digest = hashlib.sha256(str(directory).encode()).hexdigest()
    taken = frozenset(
        {"proj", "proj-work"}
        | {f"proj-{digest[:length]}" for length in range(8, len(digest) + 1)}
    )
    # Sanity: the full digest is one of the prefixes (length == len(digest)).
    assert f"proj-{digest}" in taken

    name = CollectionNamer(directory, taken).unique()

    assert name not in taken
    assert name == f"proj-{digest}-2"  # first free counter value


def test_counter_skips_taken_counter_values() -> None:
    # The counter itself must skip already-taken counter names, not just start at 2.
    directory = Path("/work/proj")
    digest = hashlib.sha256(str(directory).encode()).hexdigest()
    taken = frozenset(
        {"proj", "proj-work", f"proj-{digest}-2", f"proj-{digest}-3"}
        | {f"proj-{digest[:length]}" for length in range(8, len(digest) + 1)}
    )
    name = CollectionNamer(directory, taken).unique()
    assert name == f"proj-{digest}-4"
    assert name not in taken


def test_root_directory_never_empty_leaf() -> None:
    # A filesystem-root directory has an empty ``.name``; the leaf must fall back
    # to "root" so a collection is never named the empty string.
    assert CollectionNamer(Path("/"), frozenset()).unique() == "root"
