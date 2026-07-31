"""Server-meta contracts: liveness and aggregate status."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FdHealth(BaseModel):
    """The daemon's open file descriptors against its soft ``RLIMIT_NOFILE``.

    Sampled inside the daemon process, so it is the resident daemon's own fd
    state — the number a health check must report, never the short-lived CLI's.
    """

    open_fds: int = Field(ge=0)
    soft_limit: int = Field(gt=0)


class HealthResponse(BaseModel):
    """The daemon's liveness and readiness snapshot (unversioned; auth-exempt).

    Carries liveness (``status``), process uptime, warm/ready ``state``, the wire
    ``api_version`` a client negotiates against, the running ``quarry_version``,
    and the daemon's own file-descriptor headroom.
    """

    status: str
    uptime_seconds: float
    state: str
    api_version: str
    quarry_version: str
    # None when the daemon could not sample its own descriptors — the fd scan
    # itself needs a descriptor, so at real EMFILE exhaustion (or on a platform
    # with no fd directory) the sample raises and the daemon reports null rather
    # than 500 the health endpoint on the very condition this field surfaces.
    fd: FdHealth | None


class StatusResponse(BaseModel):
    """The aggregate status over the daemon's single database."""

    document_count: int
    collection_count: int
    chunk_count: int
    registered_directories: int
    database_path: str
    database_size_bytes: int
    embedding_model: str
    provider: str
    embedding_dimension: int
