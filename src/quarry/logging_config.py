"""Logging configuration for punt-quarry."""

from __future__ import annotations

import logging
import logging.config
import os
from pathlib import Path
from typing import final


@final
class LoggingConfig:
    """Configure logging with rotating file and stderr handlers."""

    _LOG_FILE_NAME: str = "quarry.log"

    _FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    _DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    _MAX_BYTES: int = 5_242_880  # 5 MB
    _BACKUP_COUNT: int = 5

    @classmethod
    def log_dir(cls) -> Path:
        """Return the directory the file handler writes to.

        Resolved per call rather than bound as a class constant: an import-time
        ``Path.home()`` decides the destination before any caller can speak, so
        no environment a caller sets afterwards can move it. ``QUARRY_LOG_DIR``
        is read here for the same reason ``QUARRY_LOG_LEVEL`` is read in
        :meth:`configure` — the log's location is configuration.
        """
        override = os.environ.get("QUARRY_LOG_DIR", "")
        if override:
            return Path(override)
        return Path.home() / ".punt-labs" / "quarry" / "logs"

    @classmethod
    def configure(cls, *, stderr_level: str = "WARNING") -> None:
        """Configure logging with rotating file and stderr handlers.

        File handler is always active at INFO level.
        Stderr handler level is controlled by the caller, unless overridden
        by the ``QUARRY_LOG_LEVEL`` environment variable.
        """
        log_dir = cls.log_dir()
        log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        env_level = os.environ.get("QUARRY_LOG_LEVEL", "").upper()
        valid_levels = logging.getLevelNamesMapping()
        if env_level and env_level in valid_levels:
            effective_level = env_level
        else:
            effective_level = stderr_level

        logging.config.dictConfig(
            {
                "version": 1,
                "disable_existing_loggers": False,
                "formatters": {
                    "standard": {
                        "format": cls._FORMAT,
                        "datefmt": cls._DATE_FORMAT,
                    },
                },
                "handlers": {
                    "file": {
                        "class": "logging.handlers.RotatingFileHandler",
                        "filename": str(log_dir / cls._LOG_FILE_NAME),
                        "maxBytes": cls._MAX_BYTES,
                        "backupCount": cls._BACKUP_COUNT,
                        "encoding": "utf-8",
                        "formatter": "standard",
                        "level": "INFO",
                    },
                    "stderr": {
                        "class": "logging.StreamHandler",
                        "stream": "ext://sys.stderr",
                        "formatter": "standard",
                        "level": effective_level,
                    },
                },
                "loggers": {
                    "lancedb": {"level": "WARNING"},
                    "onnxruntime": {"level": "WARNING"},
                    "httpx": {"level": "WARNING"},
                },
                "root": {
                    "level": "DEBUG",
                    "handlers": ["file", "stderr"],
                },
            }
        )
