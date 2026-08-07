"""The database this process works against: override over persisted default."""

from __future__ import annotations

from typing import TYPE_CHECKING

from quarry.config import Settings
from quarry.db_pointer import SELECTION, DatabaseSelection

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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

    def test_explicit_default_is_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Pointing at ``default`` carries no information, so it reads as unset."""
        _root_at(monkeypatch, tmp_path)
        selection = DatabaseSelection()
        selection.persist("default")
        assert selection.persisted() is None

    def test_write_creates_missing_parents(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = _root_at(monkeypatch, tmp_path / "nested" / "dir")
        DatabaseSelection().persist("coding")
        assert path.exists()


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
