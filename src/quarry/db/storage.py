"""The LanceDB connection helper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

from quarry.types import LanceDB

logger = logging.getLogger(__name__)


def get_db(db_path: Path) -> LanceDB:
    """Connect to a LanceDB database, creating it if needed."""
    import lancedb  # noqa: PLC0415

    db_path.mkdir(parents=True, exist_ok=True)
    return cast("LanceDB", lancedb.connect(str(db_path)))  # type: ignore[attr-defined]
