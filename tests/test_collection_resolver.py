"""Tests for CollectionResolver: covering, re-adopt, and unique-name resolution."""

from __future__ import annotations

from pathlib import Path

from quarry.collection_resolver import CollectionResolver
from quarry.sync_registry import SyncRegistry


class TestUniqueCollectionName:
    def test_uses_leaf_name_when_available(self, tmp_path: Path) -> None:
        conn = SyncRegistry(tmp_path / "r.db")
        project = tmp_path / "myproject"
        project.mkdir()
        assert CollectionResolver(conn).unique_collection_name(project) == "myproject"
        conn.close()

    def test_disambiguates_with_parent(self, tmp_path: Path) -> None:
        conn = SyncRegistry(tmp_path / "r.db")
        # Register a different directory with the same leaf name.
        other = tmp_path / "other" / "myproject"
        other.mkdir(parents=True)
        conn.register_directory(other, "myproject")

        project = tmp_path / "mine" / "myproject"
        project.mkdir(parents=True)
        name = CollectionResolver(conn).unique_collection_name(project)
        assert name == "myproject-mine"
        conn.close()

    def test_falls_back_to_hash_on_double_collision(self, tmp_path: Path) -> None:
        conn = SyncRegistry(tmp_path / "r.db")
        # Occupy both "myproject" and "myproject-mine".
        d1 = tmp_path / "a" / "myproject"
        d1.mkdir(parents=True)
        conn.register_directory(d1, "myproject")

        d2 = tmp_path / "b" / "myproject"
        d2.mkdir(parents=True)
        conn.register_directory(d2, "myproject-mine")

        project = tmp_path / "mine" / "myproject"
        project.mkdir(parents=True)
        name = CollectionResolver(conn).unique_collection_name(project)
        assert name.startswith("myproject-")
        assert len(name) == len("myproject-") + 8  # 8-char hash
        conn.close()

    def test_root_dir_falls_back_to_nonempty_leaf(self, tmp_path: Path) -> None:
        # A filesystem-root directory has an empty .name; the collection must
        # never be registered with an empty name — the leaf falls back to "root".
        conn = SyncRegistry(tmp_path / "r.db")
        assert CollectionResolver(conn).unique_collection_name(Path("/")) == "root"
        conn.close()

    def test_root_dir_collision_disambiguates_off_root_leaf(
        self, tmp_path: Path
    ) -> None:
        # With "root" taken, the root dir disambiguates off the "root" leaf
        # (never off an empty string).
        conn = SyncRegistry(tmp_path / "r.db")
        conn.register_directory(tmp_path, "root")

        name = CollectionResolver(conn).unique_collection_name(Path("/"))
        assert name.startswith("root-")
        assert name != "root-"
        conn.close()


class TestArchivedCollectionFor:
    """A directory re-adopts an archive it owns, like `quarry enable` does."""

    def test_owning_directory_readopts_its_archive(self, tmp_path: Path) -> None:
        # A keep-data disable archives "myproject" under its original directory.
        # The SAME directory reuses that name — not a fresh disambiguated one —
        # so its kept chunks are re-adopted.
        conn = SyncRegistry(tmp_path / "r.db")
        project = tmp_path / "myproject"
        project.mkdir()
        conn.register_directory(project, "myproject")
        conn.deregister_directory("myproject", keep_data=True)

        assert CollectionResolver(conn).archived_collection_for(project) == "myproject"
        conn.close()

    def test_unrelated_directory_owns_no_archive(self, tmp_path: Path) -> None:
        # A DIFFERENT directory with the same leaf owns no archive → None, so it
        # falls through to a fresh unique name (I7: no cross-project adoption).
        conn = SyncRegistry(tmp_path / "r.db")
        owner = tmp_path / "work" / "myproject"
        owner.mkdir(parents=True)
        conn.register_directory(owner, "myproject")
        conn.deregister_directory("myproject", keep_data=True)

        other = tmp_path / "other" / "myproject"
        other.mkdir(parents=True)
        assert CollectionResolver(conn).archived_collection_for(other) is None
        conn.close()


class TestCoveringCollection:
    def test_returns_collection_for_exact_match(self, tmp_path: Path) -> None:
        project = tmp_path / "myproject"
        project.mkdir()
        conn = SyncRegistry(tmp_path / "registry.db")
        conn.register_directory(project, "myproject")
        assert CollectionResolver(conn).covering_collection(str(project)) == "myproject"
        conn.close()

    def test_returns_collection_for_subdirectory(self, tmp_path: Path) -> None:
        project = tmp_path / "myproject"
        project.mkdir()
        subdir = project / "src" / "lib"
        subdir.mkdir(parents=True)
        conn = SyncRegistry(tmp_path / "registry.db")
        conn.register_directory(project, "myproject")
        assert CollectionResolver(conn).covering_collection(str(subdir)) == "myproject"
        conn.close()

    def test_returns_none_for_unregistered_directory(self, tmp_path: Path) -> None:
        conn = SyncRegistry(tmp_path / "registry.db")
        resolver = CollectionResolver(conn)
        assert resolver.covering_collection(str(tmp_path / "unregistered")) is None
        conn.close()
