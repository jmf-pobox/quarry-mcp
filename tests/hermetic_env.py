"""Redirect ``HOME`` away from the operator's tree before quarry is imported.

Imported by the **rootdir** ``conftest.py``, whose body pytest runs before it
imports ``tests/conftest.py``.  That ordering is the whole point: ``tests/
conftest.py`` imports quarry at module scope, and ``Settings.quarry_root`` and
the log destination are both decided from ``Path.home()`` the moment their
modules are imported.  A redirect installed after that is a redirect installed
too late.

Two earlier hooks look plausible and are not.  ``pytest_configure`` runs only
after every conftest has been imported, so quarry's paths are already bound by
then.  Registering this module as a plugin with ``-p tests.hermetic_env`` in
``addopts`` fails outright — pytest consumes plugin arguments during preparse,
before the rootdir is on ``sys.path``, so the import raises ``No module named
'tests'``.  The rootdir conftest is the earliest hook that both exists and
works.

Setting ``$HOME`` rather than patching ``Path.home`` is also deliberate.
``os.path.expanduser`` reads the environment variable and ignores the patched
classmethod, so a ``Path.home``-only patch leaves ``expanduser("~")`` and
``Path("~").expanduser()`` still pointing at production — two of the three
routes.  The variable covers all three.

The session home lives under the real ``~/.cache`` rather than under the repo,
because a repo's ``.tmp`` scratch (and, for a worktree checked out below one,
the whole worktree) is refused by :class:`~quarry.scratch_paths.ScratchGuard` —
a home inside it would leave the suite with nowhere indexable to build project
roots.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Final, Self, final

if TYPE_CHECKING:
    import pytest

# LanceDB reads ``LANCE_CPU_THREADS`` once, when it builds its compute runtime,
# and ignores every later assignment -- so the pin has to happen here, not in a
# fixture.  The values match ``ThreadConfig``'s CPU caps; pinning them means the
# bound applies even in the many tests that never construct a ``ThreadConfig``.
_THREAD_PINS: Final[dict[str, str]] = {
    "OMP_NUM_THREADS": "2",
    "LANCE_CPU_THREADS": "2",
    "LANCE_IO_THREADS": "2",
}

# Faking DNS in-process does nothing for a SUBPROCESS, which resolves and
# connects on its own.  The shadow tests bootstrap against a deliberately
# unreachable remote, so ``git fetch`` spawned a real ``ssh`` on every run; that
# passed only because the lookup usually failed fast, and turned into a 30-second
# hang per call the day it did not.  Restricting git to local transports refuses
# every remote protocol instantly, in git itself, before any resolver or socket.
# ``file`` stays allowed so a test may still use a local path as a remote.
#
# This is faithful rather than permissive: the fetch still FAILS, which is what
# those tests already assert -- it just fails locally.  ``GIT_TERMINAL_PROMPT``
# closes the other way a subprocess can wedge, blocking on a credential prompt
# with no terminal to answer it.
_NETWORK_PINS: Final[dict[str, str]] = {
    "GIT_ALLOW_PROTOCOL": "file",
    "GIT_TERMINAL_PROMPT": "0",
}


def _drop_ambient_git_config() -> None:
    """Remove the shell's ``GIT_CONFIG_*`` injection for this process.

    The workspace exports ``commit.gpgsign=true`` and a signing key through
    these variables, so every throwaway repository a test builds would try to
    sign -- and fail, because the redirected ``HOME`` moves ``GNUPGHOME`` away
    from the operator's keyring.  Signing a sandbox commit is meaningless in any
    case; dropping the injection makes the git-driven tests depend on the
    repository they create and nothing else.
    """
    count = os.environ.pop("GIT_CONFIG_COUNT", "")
    if not count.isdigit():
        return
    for index in range(int(count)):
        os.environ.pop(f"GIT_CONFIG_KEY_{index}", None)
        os.environ.pop(f"GIT_CONFIG_VALUE_{index}", None)


@final
class HermeticEnv:
    """The redirected session environment, and the real paths it protects."""

    __slots__ = ("_home", "_real_tree")

    _home: Path
    _real_tree: tuple[Path, ...]

    def __new__(cls, home: Path, real_tree: tuple[Path, ...]) -> Self:
        self = super().__new__(cls)
        self._home = home
        self._real_tree = real_tree
        return self

    @classmethod
    def install(cls) -> Self:
        """Redirect the environment and return the resulting hermetic session."""
        real_quarry = Path.home() / ".punt-labs" / "quarry"
        real_tree = (
            real_quarry / "logs" / "quarry.log",
            real_quarry / "config.toml",
            real_quarry / "data" / "default" / "registry.db",
        )

        cache = Path.home() / ".cache" / "quarry-pytest-homes"
        cache.mkdir(parents=True, exist_ok=True)
        home = Path(tempfile.mkdtemp(prefix=f"{os.getpid()}-", dir=cache))

        os.environ["HOME"] = str(home)
        quarry_dir = home / ".punt-labs" / "quarry"
        os.environ["QUARRY_ROOT"] = str(quarry_dir / "data")
        os.environ["QUARRY_LOG_DIR"] = str(quarry_dir / "logs")
        os.environ.update(_THREAD_PINS)
        os.environ.update(_NETWORK_PINS)
        _drop_ambient_git_config()

        return cls(home, real_tree)

    @property
    def home(self) -> Path:
        """Return the session's redirected home directory."""
        return self._home

    @property
    def real_tree(self) -> tuple[Path, ...]:
        """Return the production files no test may touch."""
        return self._real_tree

    def discard(self) -> None:
        """Remove the session home directory."""
        shutil.rmtree(self._home, ignore_errors=True)


@final
class ProductionTreeGuard:
    """Prove the redirect holds by watching the three files that would move.

    A smoke check, not a tree fingerprint.  Prevention is the ``HOME`` redirect,
    which is total; reaching production now requires an absolute path written
    into source, and these three files are where such a path would land.  Only
    files are watched: a directory's ``mtime`` moves when an entry is added to
    *that* directory and not when a file below it is written, so a directory
    stat would detect almost nothing.  A recursive walk is not an alternative --
    the operator's tree is 15 GB across ~1,600 files.

    It watches the files, not the writer, so it cannot attribute a change.  On a
    machine whose live daemon watches this repository, editing source during a
    run makes that daemon reindex and write ``registry.db``, and the guard
    reports it against whichever test happened to be in flight.  A firing that
    names a test which plainly touches nothing is likelier that write than a
    real breach -- confirm by rerunning with the tree quiet before hunting the
    named test.
    """

    __slots__ = ("_before", "_paths")

    _paths: tuple[Path, ...]
    _before: tuple[tuple[int, int] | None, ...]

    def __new__(cls, paths: tuple[Path, ...]) -> Self:
        self = super().__new__(cls)
        self._paths = paths
        self._before = tuple(cls._sample(p) for p in paths)
        return self

    @staticmethod
    def _sample(path: Path) -> tuple[int, int] | None:
        """Return (size, mtime_ns) for *path*, or None when it does not exist.

        ``None`` is the documented representation of absence: a file appearing
        or vanishing is itself a breach, and both directions must be visible.
        """
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        return (stat.st_size, stat.st_mtime_ns)

    def changed(self) -> list[str]:
        """Return one message per watched file whose state moved since setup."""
        return [
            f"{path} changed during the test ({before!r} -> {after!r})"
            for path, before in zip(self._paths, self._before, strict=True)
            if (after := self._sample(path)) != before
        ]


ENV: Final[HermeticEnv] = HermeticEnv.install()


def pytest_unconfigure(config: pytest.Config) -> None:
    """Remove the session's temporary home at the end of the run."""
    del config
    ENV.discard()
