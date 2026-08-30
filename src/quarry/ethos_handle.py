"""Resolve the agent handle from the ethos sidecar config at a given directory.

Two callers today: ``PreCompact`` tags captures with the resident agent's
handle, and the ``memory`` doctor check asks whether the current repo has an
ethos identity active. Both walk the same tree looking for the same file, so
the walker lives in one place — anything else invites drift between the write
path and the diagnostic.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_ETHOS_CONFIG = Path(".punt-labs") / "ethos" / "config.yaml"


def read_agent_handle(cwd: str) -> str:
    """Return the ``agent`` field from the nearest ancestor ethos config.

    Walks from *cwd* to the filesystem root looking for
    ``.punt-labs/ethos/config.yaml``. Returns the ``agent`` field's value when
    found and non-empty; returns the empty string when the file is absent, the
    YAML is unparsable, or the field is missing/blank/non-string.

    The empty string is the documented "no identity here" signal — callers use
    it as a gate, not as a value.
    """
    current = Path(cwd).resolve()
    while True:
        config_path = current / _ETHOS_CONFIG
        if config_path.is_file():
            try:
                data = yaml.safe_load(config_path.read_text())
            except (OSError, yaml.YAMLError):
                logger.warning(
                    "ethos_handle: could not parse %s", config_path, exc_info=True
                )
                return ""
            if isinstance(data, dict):
                agent = data.get("agent", "")
                if isinstance(agent, str) and agent:
                    return agent
            return ""
        parent = current.parent
        if parent == current:
            return ""
        current = parent
