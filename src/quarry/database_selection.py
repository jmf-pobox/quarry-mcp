"""Which database this process works against, and where that choice is stored."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Final, Self, final

from quarry.config import Settings

if TYPE_CHECKING:
    from pathlib import Path

_POINTER_FILE: Final[str] = "config.toml"

# The name that means "no persisted choice": a pointer at the default database
# carries no information, so it reads back as absent rather than as a selection.
_UNSET: Final[str] = "default"


@final
class DatabaseSelection:
    """A per-process override layered over a default persisted on disk.

    Two things travel together and so belong in one class: the ``--db`` flag the
    current process was started with, and the default recorded in
    ``config.toml``. The override wins when set; otherwise the persisted default
    answers. Callers ask for the effective choice and do not resolve the
    precedence themselves.

    Extracted from ``Settings``, which is a settings container and has no
    business owning a mutable process-scoped selection or a TOML file format.
    """

    __slots__ = ("_override",)

    _override: str

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._override = ""
        return self

    @property
    def path(self) -> Path:
        """Return the pointer file's location, resolved per access.

        A sibling of the data root, so relocating the root via ``QUARRY_ROOT``
        relocates the pointer with it. Resolved on every access rather than
        bound once: a path fixed at import time cannot follow an environment the
        caller sets afterwards.
        """
        return Settings.data_root().parent / _POINTER_FILE

    def persisted(self) -> str | None:
        """Return the database recorded on disk, or None when none is.

        ``None`` is the documented contract for absence here, not a swallowed
        failure: no file, a malformed file, and an explicit ``default`` all mean
        "nothing has been chosen", and every caller already treats them alike.
        """
        path = self.path
        if not path.exists():
            return None
        try:
            data = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError:
            return None
        name = str(data.get("default", {}).get("database", ""))
        return name if name and name != _UNSET else None

    def persist(self, name: str) -> None:
        """Record *name* as the default database for future processes."""
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'[default]\ndatabase = "{name}"\n')

    def override(self, name: str) -> None:
        """Record this process's ``--db`` choice; an empty name clears it."""
        self._override = name

    def active(self) -> str | None:
        """Return the effective database: the override, else the persisted default."""
        return self._override or self.persisted()


# The override is a property of the running process, so one instance stands for
# it. Tests build their own to keep an override out of the shared one.
SELECTION: Final[DatabaseSelection] = DatabaseSelection()
