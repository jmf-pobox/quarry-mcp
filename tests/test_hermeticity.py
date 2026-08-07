"""The suite writes nothing under the operator's real ``~/.punt-labs/quarry``.

Two mechanisms, tested separately: the ``HOME`` redirect that makes production
unreachable, and the three-file guard that proves the redirect is in force.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from quarry.config import Settings
from quarry.database_selection import SELECTION
from quarry.logging_config import LoggingConfig
from tests.hermetic_env import ENV, ProductionTreeGuard


class TestHomeRedirect:
    """All three home-resolution routes land inside the session temp home."""

    def test_path_home(self) -> None:
        assert Path.home().is_relative_to(ENV.home)

    def test_path_expanduser_method(self) -> None:
        assert Path("~").expanduser().is_relative_to(ENV.home)

    def test_expanduser_ignores_a_patched_path_home(self) -> None:
        """Why the redirect must be the env var and not a ``Path.home`` patch.

        ``expanduser`` resolves through ``$HOME`` and never consults
        ``Path.home``, so patching the classmethod would leave this route — and
        the ``os.path.expanduser`` one behind it — pointed at production.
        """
        elsewhere = Path("/nonexistent-patched-home")
        with patch.object(Path, "home", classmethod(lambda _cls: elsewhere)):
            assert Path.home() == elsewhere, "the patch must actually be in force"
            assert Path("~").expanduser().is_relative_to(ENV.home)

    def test_quarry_root_is_redirected(self) -> None:
        assert Settings.load().quarry_root.is_relative_to(ENV.home)

    def test_config_path_is_redirected(self) -> None:
        assert SELECTION.path.is_relative_to(ENV.home)

    def test_log_dir_is_redirected(self) -> None:
        assert LoggingConfig.log_dir().is_relative_to(ENV.home)

    def test_configure_writes_inside_the_session_home(self) -> None:
        """The breach this whole design exists to close: CLI logging is contained."""
        LoggingConfig.configure()
        log = LoggingConfig.log_dir() / "quarry.log"
        assert log.parent.is_dir()
        assert log.is_relative_to(ENV.home)


class TestProductionTreeGuard:
    """The guard fires on a change to any watched file, and stays quiet otherwise."""

    def test_quiet_when_nothing_moves(self, tmp_path: Path) -> None:
        watched = tmp_path / "quarry.log"
        watched.write_text("x")
        assert ProductionTreeGuard((watched,)).changed() == []

    def test_quiet_for_a_file_that_never_existed(self, tmp_path: Path) -> None:
        assert ProductionTreeGuard((tmp_path / "absent",)).changed() == []

    def test_fires_on_append(self, tmp_path: Path) -> None:
        """The log breach: an appended line moves both size and mtime."""
        watched = tmp_path / "quarry.log"
        watched.write_text("first\n")
        guard = ProductionTreeGuard((watched,))
        with watched.open("a") as handle:
            handle.write("second\n")
        assert len(guard.changed()) == 1

    def test_fires_on_creation(self, tmp_path: Path) -> None:
        """A config.toml written where none existed breaches in the other direction."""
        watched = tmp_path / "config.toml"
        guard = ProductionTreeGuard((watched,))
        watched.write_text('[default]\ndatabase = "work"\n')
        assert len(guard.changed()) == 1

    def test_fires_on_deletion(self, tmp_path: Path) -> None:
        watched = tmp_path / "registry.db"
        watched.write_text("db")
        guard = ProductionTreeGuard((watched,))
        watched.unlink()
        assert len(guard.changed()) == 1

    def test_names_every_breached_path(self, tmp_path: Path) -> None:
        """The message identifies which file moved, not merely that one did."""
        first, second = tmp_path / "a.log", tmp_path / "b.toml"
        guard = ProductionTreeGuard((first, second))
        first.write_text("x")
        second.write_text("y")
        breaches = guard.changed()
        assert len(breaches) == 2
        assert str(first) in breaches[0]
        assert str(second) in breaches[1]

    def test_watches_exactly_the_three_production_files(self) -> None:
        """Files only -- a directory stat does not move when a file below it does."""
        names = [p.name for p in ENV.real_tree]
        assert names == ["quarry.log", "config.toml", "registry.db"]
        assert all(not p.is_dir() for p in ENV.real_tree)


class TestAmbientGitConfig:
    """The shell's git-signing injection does not follow the suite in."""

    def test_signing_config_is_dropped(self) -> None:
        """The redirected home has no keyring, so a sandbox repo must not sign."""
        assert "GIT_CONFIG_COUNT" not in os.environ

    def test_signing_key_and_program_are_dropped_with_it(self) -> None:
        """The count is the index; leaving the pairs behind would be half a job."""
        leftovers = [k for k in os.environ if k.startswith("GIT_CONFIG_")]
        assert leftovers == []


class TestThreadPins:
    """The per-run thread budget is pinned before lance builds its runtime."""

    def test_pool_sizes_are_bounded(self) -> None:
        """A ceiling, not an exact value.

        ``ThreadConfig._cap_env`` may lower any of these mid-session (GPU caps
        OMP at 1), so the invariant the pin establishes is the upper bound --
        asserting equality would make this test depend on which other test
        constructed a ``ThreadConfig`` first.
        """
        for name in ("OMP_NUM_THREADS", "LANCE_CPU_THREADS", "LANCE_IO_THREADS"):
            assert int(os.environ[name]) <= 2, name
