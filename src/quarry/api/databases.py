"""The databases contract: the single database the daemon is fixed to."""

from __future__ import annotations

from pydantic import BaseModel


class DatabaseInfo(BaseModel):
    """One named database's summary.

    The daemon is fixed to a single database, so the list returns exactly one
    entry.  No size field: producing it meant walking the whole tree per
    request (10-19 s here), and LanceDB's O(1) statistic measures the live
    dataset rather than the directory, so it cannot stand in.

    The model is CLOSED, unlike its siblings here.  Those mirror an engine
    catalog or registry row and stay open so a new upstream field is not a
    validation error; this one is built from a literal two-key dict in the
    route, so there is no upstream to track.  Closed also means a daemon that
    re-grew ``size_bytes`` fails client validation instead of quietly serving
    it again.
    """

    name: str
    document_count: int


class DatabaseList(BaseModel):
    """The database-list response envelope."""

    total_databases: int
    databases: list[DatabaseInfo]
