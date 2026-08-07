"""The database this process works against: override over persisted default."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from quarry.config import Settings
from quarry.db_pointer import SELECTION, DatabaseSelection


def _root_at(monkeypatch: pytest.MonkeyPatch, base: Path) -> Path:
    """Point QUARRY_ROOT at ``base/data``; return the pointer path it implies."""
    monkeypatch.setenv("QUARRY_ROOT", str(base / "data"))
    return base / "config.toml"


class TestPointerLocation:
    """The pointer file follows the data root rather than a fixed home."""

    def test_path_is_a_sibling_of_the_data_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        expected = _root_at(monkeypatch, tmp_path)
        assert DatabaseSelection().path == expected

    def test_path_follows_a_later_root_change(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Resolved per access, so an env set after construction still counts."""
        selection = DatabaseSelection()
        expected = _root_at(monkeypatch, tmp_path / "moved")
        assert selection.path == expected

    def test_dotenv_root_moves_the_pointer_too(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The pointer and the data must never disagree about where the root is.

        ``Settings`` reads ``.env`` as well as the process environment, so a
        root configured only there moves the data. Resolving the pointer from a
        separate environment read would leave it behind — beside the operator's
        real, guarded ``config.toml`` — while the data relocated.
        """
        monkeypatch.delenv("QUARRY_ROOT", raising=False)
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "relocated" / "data"
        (tmp_path / ".env").write_text(f"QUARRY_ROOT={root}\n")

        assert Settings.load().quarry_root == root, "the .env route must set the field"
        assert DatabaseSelection().path == root.parent / "config.toml"


class TestPersistedDefault:
    """Round-tripping the on-disk default, and what counts as absent."""

    def test_write_then_read(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _root_at(monkeypatch, tmp_path)
        selection = DatabaseSelection()
        selection.persist("work")
        assert selection.persisted() == "work"

    def test_missing_file_is_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _root_at(monkeypatch, tmp_path / "nonexistent")
        assert DatabaseSelection().persisted() is None

    def test_malformed_file_is_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A corrupt pointer must not crash a CLI command that merely reads it."""
        path = _root_at(monkeypatch, tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("this is not [ valid toml")
        assert DatabaseSelection().persisted() is None

    def test_a_file_naming_the_default_reads_as_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Pointing at ``default`` carries no information, so it reads as unset.

        Written here directly because ``persist`` refuses the name; the read
        contract still has to hold for a file that arrived some other way.
        """
        path = _root_at(monkeypatch, tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[default]\ndatabase = "default"\n')
        assert DatabaseSelection().persisted() is None

    def test_write_creates_missing_parents(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = _root_at(monkeypatch, tmp_path / "nested" / "dir")
        DatabaseSelection().persist("coding")
        assert path.exists()


class TestHostileNames:
    """A name that cannot round-trip is refused, never written."""

    @pytest.mark.parametrize(
        "name",
        [
            'ev"il',
            "back\\slash",
            "line\nbreak",
            "with space",
            "",
            ".",
            "..",
            "../escape",
            "sub/dir",
        ],
    )
    def test_unpersistable_name_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
    ) -> None:
        path = _root_at(monkeypatch, tmp_path)
        selection = DatabaseSelection()
        with pytest.raises(ValueError, match="cannot be persisted"):
            selection.persist(name)
        assert not path.exists(), "a refused name must not leave a file behind"

    def test_a_quoted_name_would_have_been_silently_lost(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Why this is refused rather than escaped: the failure was invisible.

        Written unescaped, the file no longer parses, so the selection reads
        back as absence -- the operator's choice gone with no error anywhere.
        """
        path = _root_at(monkeypatch, tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[default]\ndatabase = "ev"il"\n')
        assert DatabaseSelection().persisted() is None

    def test_persisting_the_default_name_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """It names absence; writing it would read back as nothing selected."""
        _root_at(monkeypatch, tmp_path)
        with pytest.raises(ValueError, match="clear"):
            DatabaseSelection().persist("default")


class TestWriteSafety:
    """The pointer survives a failed write."""

    def test_a_failed_write_leaves_the_previous_pointer(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _root_at(monkeypatch, tmp_path)
        selection = DatabaseSelection()
        selection.persist("work")

        with (
            patch.object(Path, "replace", side_effect=OSError("no space")),
            pytest.raises(OSError, match="no space"),
        ):
            selection.persist("newer")

        assert selection.persisted() == "work", "the old pointer must survive"

    def test_a_failed_write_leaves_no_temporary_behind(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pointer = _root_at(monkeypatch, tmp_path)
        selection = DatabaseSelection()
        with (
            patch.object(Path, "replace", side_effect=OSError("no space")),
            pytest.raises(OSError),
        ):
            selection.persist("work")
        assert list(pointer.parent.glob("*.tmp")) == []


class TestUnreadablePointer:
    """An unreadable pointer is not the same fact as an unset one."""

    def test_permission_error_propagates(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Absence is None; failure raises. Conflating them picks a wrong db."""
        _root_at(monkeypatch, tmp_path)
        selection = DatabaseSelection()
        selection.persist("work")

        with (
            patch.object(Path, "read_text", side_effect=PermissionError("denied")),
            pytest.raises(PermissionError),
        ):
            selection.persisted()


class TestClear:
    """Forgetting the persisted default."""

    def test_clear_removes_the_pointer(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = _root_at(monkeypatch, tmp_path)
        selection = DatabaseSelection()
        selection.persist("work")
        selection.clear()
        assert selection.persisted() is None
        assert not path.exists()

    def test_clear_is_idempotent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _root_at(monkeypatch, tmp_path)
        DatabaseSelection().clear()

    def test_clear_leaves_the_process_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The two layers are independent; clearing one must not touch the other."""
        _root_at(monkeypatch, tmp_path)
        selection = DatabaseSelection()
        selection.persist("work")
        selection.override("scratch")
        selection.clear()
        assert selection.active() == "scratch"


class TestPrecedence:
    """The override wins while it is set; the persisted default answers otherwise."""

    def test_nothing_set_is_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _root_at(monkeypatch, tmp_path)
        assert DatabaseSelection().active() is None

    def test_persisted_answers_without_an_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _root_at(monkeypatch, tmp_path)
        selection = DatabaseSelection()
        selection.persist("persisted")
        assert selection.active() == "persisted"

    def test_override_beats_persisted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _root_at(monkeypatch, tmp_path)
        selection = DatabaseSelection()
        selection.persist("persisted")
        selection.override("work")
        assert selection.active() == "work"

    def test_clearing_the_override_restores_persisted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """An empty name clears rather than selecting a database called ''."""
        _root_at(monkeypatch, tmp_path)
        selection = DatabaseSelection()
        selection.persist("persisted")
        selection.override("work")
        selection.override("")
        assert selection.active() == "persisted"


class TestOverrideIsolation:
    """An override belongs to its instance, never to the class."""

    def test_instances_do_not_share_an_override(self) -> None:
        """Each instance owns its override, so a test cannot leak into SELECTION."""
        one, two = DatabaseSelection(), DatabaseSelection()
        one.override("work")
        assert two.active() != "work"

    def test_module_singleton_starts_without_an_override(self) -> None:
        assert SELECTION.active() is None
