"""Direct unit tests for the client-side ``Registrations`` coverage view.

These exercise ``covering`` (exact / parent / none / root-stop) and all three
tiers of ``unique_collection_name`` (leaf, leaf-parent on collision, hash suffix
on double collision) at the unit level — the daemon-view seam enable/disable
depend on.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from quarry.api import RegistrationInfo, RetainedCollection
from quarry.registrations import Registrations


def _reg(collection: str, directory: Path) -> RegistrationInfo:
    return RegistrationInfo(
        collection=collection,
        directory=str(directory.resolve()),
        registered_at="2026-01-01",
    )


def _retained(collection: str, directory: Path) -> RetainedCollection:
    return RetainedCollection(
        collection=collection, original_directory=str(directory.resolve())
    )


class TestCovering:
    def test_exact_match(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        view = Registrations([_reg("project", project)])

        found = view.covering(project)

        assert found is not None
        assert found.collection == "project"

    def test_parent_match(self, tmp_path: Path) -> None:
        parent = tmp_path / "project"
        parent.mkdir()
        child = parent / "src" / "pkg"
        child.mkdir(parents=True)
        view = Registrations([_reg("project", parent)])

        found = view.covering(child)

        assert found is not None
        assert found.collection == "project"
        assert found.directory == str(parent.resolve())

    def test_no_match_returns_none(self, tmp_path: Path) -> None:
        registered = tmp_path / "a"
        registered.mkdir()
        unrelated = tmp_path / "b"
        unrelated.mkdir()
        view = Registrations([_reg("a", registered)])

        assert view.covering(unrelated) is None

    def test_empty_view_returns_none(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()

        assert Registrations([]).covering(project) is None

    def test_root_stop_does_not_loop(self, tmp_path: Path) -> None:
        # A query at the filesystem root must terminate (parent == current) and
        # return None rather than spin — no registration covers "/".
        view = Registrations([_reg("project", tmp_path)])

        assert view.covering(Path(Path(tmp_path.anchor))) is None


class TestUniqueCollectionName:
    def test_leaf_when_no_collision(self, tmp_path: Path) -> None:
        project = tmp_path / "myproject"
        project.mkdir()
        view = Registrations([])

        assert view.unique_collection_name(project) == "myproject"

    def test_leaf_parent_on_leaf_collision(self, tmp_path: Path) -> None:
        # "myproject" is taken → disambiguate with the parent dir name.
        parent = tmp_path / "acme"
        project = parent / "myproject"
        project.mkdir(parents=True)
        view = Registrations([_reg("myproject", tmp_path / "other")])

        assert view.unique_collection_name(project) == "myproject-acme"

    def test_root_dir_falls_back_to_nonempty_leaf(self) -> None:
        # A filesystem-root directory has an empty .name; the collection must
        # never be registered with an empty name — the leaf falls back to "root".
        view = Registrations([])

        assert view.unique_collection_name(Path("/")) == "root"

    def test_root_dir_collision_disambiguates_off_root_leaf(self) -> None:
        # With "root" taken, the root dir disambiguates off the "root" leaf
        # (never off an empty string).
        view = Registrations([_reg("root", Path("/"))])

        name = view.unique_collection_name(Path("/"))
        assert name.startswith("root-")
        assert name != "root-"

    def test_hash_suffix_on_double_collision(self, tmp_path: Path) -> None:
        # Both "myproject" and "myproject-acme" are taken → sha256 path suffix.
        parent = tmp_path / "acme"
        project = parent / "myproject"
        project.mkdir(parents=True)
        view = Registrations(
            [
                _reg("myproject", tmp_path / "x"),
                _reg("myproject-acme", tmp_path / "y"),
            ]
        )

        expected_suffix = hashlib.sha256(str(project).encode()).hexdigest()[:8]
        assert view.unique_collection_name(project) == f"myproject-{expected_suffix}"

    def test_avoids_archived_retained_name(self, tmp_path: Path) -> None:
        # No LIVE registration named "backend", but it is archived (retained) by a
        # prior keep-data disable from a DIFFERENT directory. A new, unrelated
        # "backend" directory must NOT re-use the archived name (which would
        # inherit its chunks) — it disambiguates off the parent instead.
        parent = tmp_path / "acme"
        project = parent / "backend"
        project.mkdir(parents=True)
        view = Registrations(
            [], retained=[_retained("backend", tmp_path / "elsewhere")]
        )

        assert view.unique_collection_name(project) == "backend-acme"

    def test_from_list_carries_retained(self, tmp_path: Path) -> None:
        # from_list must thread the wire response's retained markers into the
        # picker so the remote path avoids archived names as a local view does.
        from quarry.api import RegistrationList

        parent = tmp_path / "acme"
        project = parent / "backend"
        project.mkdir(parents=True)
        listing = RegistrationList(
            total_registrations=0,
            registrations=[],
            retained=[_retained("backend", tmp_path / "elsewhere")],
        )
        view = Registrations.from_list(listing)

        assert view.unique_collection_name(project) == "backend-acme"

    def test_archived_collection_for_matches_owning_directory(
        self, tmp_path: Path
    ) -> None:
        # The SAME directory that owns an archive re-adopts it by name; an
        # unrelated directory owns no archive and gets None (→ a fresh name).
        owner = tmp_path / "acme" / "backend"
        owner.mkdir(parents=True)
        other = tmp_path / "other" / "backend"
        other.mkdir(parents=True)
        view = Registrations([], retained=[_retained("backend", owner)])

        assert view.archived_collection_for(owner) == "backend"
        assert view.archived_collection_for(other) is None

    def test_remote_readopt_equals_local(self, tmp_path: Path) -> None:
        """Re-adopt off the wire payload matches re-adopt off the local registry.

        Bridges the whole parity chain: a real registry archives a collection;
        its ``retained_markers()`` are mapped into the wire ``RetainedCollection``
        exactly as the HTTP ``/registrations`` route does; ``Registrations.from_list``
        over that payload re-adopts by the owning directory identically to a local
        view built from the same markers.
        """
        from quarry.api import RegistrationList
        from quarry.sync_registry import SyncRegistry

        owner = tmp_path / "acme" / "backend"
        owner.mkdir(parents=True)
        conn = SyncRegistry(tmp_path / "r.db")
        try:
            conn.register_directory(owner, "backend")
            conn.deregister_directory("backend", keep_data=True)
            markers = conn.markers.retained_markers()
        finally:
            conn.close()

        # Marshal registry markers into the wire shape, exactly as the HTTP route.
        wire = [
            RetainedCollection(
                collection=m.collection, original_directory=m.original_directory
            )
            for m in markers
        ]
        local = Registrations([], retained=wire)  # straight from the registry
        remote = Registrations.from_list(  # the same markers through the envelope
            RegistrationList(total_registrations=0, registrations=[], retained=wire)
        )

        assert local.archived_collection_for(owner) == "backend"
        assert remote.archived_collection_for(owner) == "backend"
        assert local.archived_collection_for(owner) == remote.archived_collection_for(
            owner
        )
