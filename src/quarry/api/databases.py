"""The databases contract: the single database the daemon is fixed to."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DatabaseInfo(BaseModel):
    """One named database's summary.

    The daemon is fixed to a single database, so the list returns exactly one
    entry.  No size field: producing it meant walking the whole tree per
    request (10-19 s here), and LanceDB's O(1) statistic measures the dataset
    rather than the directory, so it cannot stand in.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    document_count: int


class DatabaseList(BaseModel):
    """The database-list response envelope."""

    total_databases: int
    databases: list[DatabaseInfo]
