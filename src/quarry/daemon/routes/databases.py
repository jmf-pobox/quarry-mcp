"""The databases and use routes: the daemon's single fixed database."""

from __future__ import annotations

from typing import final

from starlette.requests import Request
from starlette.responses import JSONResponse

from quarry.daemon.routes.base import RouteGroup


@final
class DatabaseRoutes(RouteGroup):
    """Serve database listing (single entry) and use (always 400)."""

    def databases(self, request: Request) -> JSONResponse:
        """Return a single-entry list describing the server's database.

        The server process is fixed to one database — selection is a
        client-side concern.

        No size is reported.  The only way to produce the database's on-disk
        size is to walk the tree, which cost 10 to 19 seconds per request here
        and which any client could trigger.  LanceDB's O(1) ``table.stats()``
        is not a substitute: it measures the LIVE DATASET, not the directory,
        so it misses whatever else the directory holds -- superseded data-file
        versions, index files -- which measured 43% and 81% of the total on two
        stores.  A varying shortfall is not one a caller can correct for.
        """
        auth_resp = self.reject_unauthorized(request)
        if auth_resp is not None:
            return auth_resp

        lance_dir = self.ctx.settings.lancedb_path
        summary = {
            "name": lance_dir.parent.name or "default",
            "document_count": self._document_count(),
        }
        return JSONResponse({"total_databases": 1, "databases": [summary]})

    def _document_count(self) -> int:
        """Return the catalog document count, treating a fresh DB as zero.

        A fresh database (no ``chunks`` table yet) already yields ``[]`` from
        ``list_documents``, so the count is naturally zero — a genuine catalog
        error is left to surface as a 500 rather than being masked as "zero".
        """
        if not self.ctx.settings.lancedb_path.exists():
            return 0
        return len(self.ctx.database.catalog.list_documents())

    def use(self, request: Request) -> JSONResponse:
        """Reject database selection: the server is fixed to its own database."""
        auth_resp = self.reject_unauthorized(request)
        if auth_resp is not None:
            return auth_resp

        return JSONResponse(
            {
                "error": (
                    "database selection is client-side only; "
                    "the remote server is fixed to its own database"
                )
            },
            status_code=400,
        )
