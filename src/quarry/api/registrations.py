"""The registrations contract: register a directory and list registrations."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    """Body for tracking a directory for sync.

    ``directory`` must resolve inside the daemon's home directory; the daemon
    rejects traversal and out-of-tree paths before registering.
    """

    directory: str
    collection: str


class RegistrationInfo(BaseModel):
    """One directory registration.

    ``extra="allow"`` keeps the model a superset of the registry row shape.
    """

    model_config = ConfigDict(extra="allow")

    collection: str
    directory: str
    registered_at: str


class RetainedCollection(BaseModel):
    """A collection whose chunks were kept on a keep-data disable (archived).

    ``original_directory`` is the directory it was registered under, so the
    client can tell whether THIS directory owns the archive: the same directory
    re-adopts it (reuses the name + kept chunks); a different directory must not
    (it would inherit another project's chunks).  Empty when a legacy marker
    recorded no origin — it then matches no directory and is never re-adopted.
    """

    model_config = ConfigDict(extra="allow")

    collection: str
    original_directory: str = ""


class RegistrationList(BaseModel):
    """The registration-list response envelope.

    ``retained`` carries the archived (keep-data) collections with the directory
    each was registered under.  The name-picker avoids their names so a new,
    unrelated directory never collides with an archive; the enable path re-adopts
    an archive whose ``original_directory`` matches the directory being enabled.
    Defaulted so a response from an older daemon that omits the field still
    parses (wire-compat at the boundary).
    """

    total_registrations: int
    registrations: list[RegistrationInfo]
    retained: list[RetainedCollection] = Field(default_factory=list)
