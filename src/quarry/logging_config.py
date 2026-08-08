"""Logging configuration for punt-quarry, and the level policy that governs it.

THE LEVEL POLICY, which binds every ``logger.*`` call in this codebase:

    INFO is one line per user-visible operation or coarser.
    Sub-operation detail is DEBUG.

A "user-visible operation" is something the operator asked for or would
recognise having happened: a document indexed, a collection swept, a database
optimized, the daemon started. Anything that fires more often than that —
per flush window, per request, per row — is DEBUG, however interesting it looked
when it was written.

The rule exists because the daemon spent its whole life logging nowhere: it
never configured logging at all, so INFO was discarded before reaching a
handler and nobody ever saw the volume. Switching the file on without a policy
would have replaced silence with a firehose, and a log too noisy to read fails
the same way a log that does not exist does. Two lines were demoted on the day
the file appeared — ``ChunkStore``'s per-flush insert and the search route's
per-request result count — and the next person tempted to log per-row should
read this instead of rediscovering it from a flooded file.
"""

from __future__ import annotations

import logging
import logging.config
import os
from pathlib import Path
from typing import final


@final
class LoggingConfig:
    """Configure logging with rotating file and stderr handlers.

    Two processes configure logging into the same directory under two names.
    ``quarry.log`` is the client tier: many short-lived CLI and MCP processes.
    ``quarryd.log`` is the daemon: one long-lived writer.  They are kept apart
    because interleaving them makes attribution hard exactly when it matters --
    reading a single file, you cannot tell which of a dozen processes emitted a
    line, and a daemon incident is diagnosed by reading the daemon's own
    sequence.  Same directory, same format, same rotation policy; two files.
    """

    CLIENT_LOG: str = "quarry.log"
    DAEMON_LOG: str = "quarryd.log"

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
    def configure(
        cls, *, stderr_level: str = "WARNING", log_file: str = CLIENT_LOG
    ) -> None:
        """Configure logging with rotating file and stderr handlers.

        File handler is always active at INFO level.
        Stderr handler level is controlled by the caller, unless overridden
        by the ``QUARRY_LOG_LEVEL`` environment variable.

        *log_file* selects which file in the resolved directory receives the
        output -- :attr:`CLIENT_LOG` for CLI and MCP processes,
        :attr:`DAEMON_LOG` for ``quarryd``.
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
                        "filename": str(log_dir / log_file),
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
