"""Enable and disable quarry knowledge capture for project directories."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from quarry.api import (
        DeleteCollectionRequest,
        DeregisterAccepted,
        DeregisterRequest,
        RegisterRequest,
        RegistrationList,
        TaskAccepted,
    )

logger = logging.getLogger(__name__)


class RegistryClient(Protocol):
    """The daemon-registry surface enable/disable need — the client is the adapter.

    Depending on this port (not the concrete ``QuarryClient``) keeps enable/disable
    off the client package's import graph and lets a test supply an in-memory
    stand-in.
    """

    def list_registrations(self) -> RegistrationList: ...
    def register(self, req: RegisterRequest) -> TaskAccepted: ...
    def deregister(self, req: DeregisterRequest) -> DeregisterAccepted: ...
    def delete_collection(self, req: DeleteCollectionRequest) -> TaskAccepted: ...


@dataclass(frozen=True, slots=True)
class EnableResult:
    """Result of enabling quarry for a project directory.

    The four CLAUDE.md fields track the § 2.3 enable steps: the vendored guide
    deposit, the ``enabled`` marker, the one bare ``@``-import line, and the
    one-time strip of the retired ``quarry:begin``/``end`` legacy block.
    """

    directory: str
    collection: str
    captures_collection: str
    memory_collections: list[str] = field(default_factory=list)
    config_path: str = ""
    created_registration: bool = False
    guide_deposited: bool = False
    enabled_marker_written: bool = False
    import_registered: bool = False
    legacy_block_stripped: bool = False
    ethos_skipped: bool = False
    ethos_updated: list[str] = field(default_factory=list)
    ethos_already_set: list[str] = field(default_factory=list)
    ethos_created: list[str] = field(default_factory=list)
    ethos_failed: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DisableResult:
    """Result of disabling quarry.  ``removed`` is the registry file count the
    daemon reported synchronously; the chunk purge runs as a background task.

    ``disable`` is non-destructive of the vendored guide (§ 2.9): it prunes the
    ``@``-import line and deletes the ``enabled`` marker, leaving the deposited
    ``.punt-labs/quarry/CLAUDE.md`` dormant on disk.
    """

    directory: str
    collection: str
    captures_collection: str
    removed: int = 0
    config_removed: bool = False
    import_pruned: bool = False
    enabled_marker_removed: bool = False


_CONFIG_TEMPLATE = """\
---
auto_capture:
  session_sync: true
  web_fetch: true
  compaction: true
# shadow:                          # push redacted captures to a PRIVATE shadow repo
#   enabled: false                 # opt-in network+security action, off by default
#   remote: ""                     # empty -> derive <origin>-quarry from origin
#   acknowledge_unverified: false  # push even when gh cannot confirm private
---

# Quarry Project Configuration

Controls quarry's passive knowledge capture. Set any field to `false` to disable
that capture type; uncomment `shadow` to move redacted captures off the public
repo into a per-project private shadow (`<repo>` -> `<repo>-quarry`).

- `session_sync`: auto-index project files on session start
- `web_fetch`: auto-ingest URLs fetched during research
- `compaction`: capture session transcripts before context compaction
- `shadow`: pre-create the private repo, then set `enabled: true`
"""


def enable_project(
    directory: Path,
    client: RegistryClient,
    collection_override: str = "",
) -> EnableResult:
    """Enable quarry knowledge capture for a project directory.

    The registry is the daemon's (DES-031 I2): coverage is computed from its
    ``RegistrationList`` and a new registration is dispatched via ``client``, never
    a local ``SyncRegistry``.  The project files (config.md, CLAUDE.md, ethos ext)
    are the client's and are written locally.
    """
    from quarry.enablement import Enablement  # noqa: PLC0415
    from quarry.ethos_memory import EthosMemoryBootstrap  # noqa: PLC0415
    from quarry.registrar import Registrar  # noqa: PLC0415

    # expanduser BEFORE resolve: a bare "~/proj" otherwise resolves against cwd
    # ("./~/proj"), targeting the wrong directory.
    directory = directory.expanduser().resolve()
    if not directory.is_dir():
        msg = f"directory not found: {directory}"
        raise ValueError(msg)

    collection, created = Registrar(client).resolve(directory, collection_override)

    captures_collection = f"{collection}-captures"

    ethos = EthosMemoryBootstrap().run()

    config_path = _write_project_config(directory)
    claudemd = Enablement(directory).enable()
    if claudemd.import_registered:
        logger.info("Registered quarry @-import in CLAUDE.md")

    return EnableResult(
        directory=str(directory),
        collection=collection,
        captures_collection=captures_collection,
        memory_collections=ethos.memory_collections,
        config_path=config_path,
        created_registration=created,
        guide_deposited=claudemd.guide_deposited,
        enabled_marker_written=claudemd.enabled_marker_written,
        import_registered=claudemd.import_registered,
        legacy_block_stripped=claudemd.legacy_block_stripped,
        ethos_skipped=ethos.skipped,
        ethos_updated=ethos.updated,
        ethos_already_set=ethos.already_set,
        ethos_created=ethos.created,
        ethos_failed=ethos.failed,
    )


def disable_project(
    directory: Path,
    client: RegistryClient,
    *,
    keep_data: bool = False,
) -> DisableResult:
    """Disable quarry knowledge capture for a project directory.

    Idempotent and retry-safe.  Deregisters the covering collection via the daemon
    (dropping the registry row and purging its chunks server-side) and, unless
    ``keep_data``, dispatches a purge of the ``-captures`` sibling — both
    fire-and-forget; the registry is never mutated through a local ``SyncRegistry``.

    A directory with no covering registration is NOT an error: it was never
    enabled, or a prior partial disable already removed it.  The local project
    files are still cleaned and the call succeeds, so a retry after a mid-teardown
    failure always converges to fully-disabled.  Local file cleanup runs BEFORE
    the best-effort captures purge, so a rejected purge can never leave config.md
    or CLAUDE.md claiming enabled.
    """
    from quarry.api import DeleteCollectionRequest, DeregisterRequest  # noqa: PLC0415
    from quarry.client.errors import QuarryError  # noqa: PLC0415
    from quarry.enablement import Enablement  # noqa: PLC0415
    from quarry.registrations import Registrations  # noqa: PLC0415

    # expanduser BEFORE resolve: a bare "~/proj" otherwise resolves against cwd,
    # targeting (and deregistering) the wrong path.
    directory = directory.expanduser().resolve()
    view = Registrations.from_list(client.list_registrations())
    covering = view.covering(directory)

    # Disabling a CHILD of a registered parent is a real error — the parent covers
    # it; never silently deregister the parent. This guard alone stays fatal.
    if covering is not None and covering.directory != str(directory):
        msg = (
            f"no registration for {directory}; "
            f"it is covered by parent registration at {covering.directory}"
        )
        raise ValueError(msg)

    collection = covering.collection if covering is not None else ""
    removed = 0
    if covering is not None:
        removed = client.deregister(
            DeregisterRequest(collection=collection, keep_data=keep_data)
        ).removed

    # Clean local capture config whether or not a registration was present, and
    # BEFORE the best-effort captures purge below — a retry always reaches here.
    config_path = directory / ".punt-labs" / "quarry" / "config.md"
    config_removed = False
    if config_path.exists():
        config_path.unlink()
        config_removed = True

    # Prune the @-import line and delete the enabled marker (§ 2.3). The vendored
    # guide is left in place — disable is non-destructive of vendored content
    # (§ 2.9), so the .punt-labs/quarry/ subtree stays as dormant, git-recoverable
    # history rather than being erased on a toggle.
    claudemd = Enablement(directory).disable()
    if claudemd.import_pruned:
        logger.info("Removed quarry @-import from CLAUDE.md")

    # Best-effort captures purge, dispatched last. A rejection is caught and
    # warned, never propagated: the primary teardown (deregister + local file
    # cleanup) already succeeded and disable is idempotent, so a stranded
    # secondary purge must not fail the whole command. Once the registration is
    # gone a retry cannot re-derive the captures name, so this is the one attempt.
    captures_collection = f"{collection}-captures" if collection else ""
    if covering is not None and not keep_data:
        try:
            client.delete_collection(DeleteCollectionRequest(name=captures_collection))
        except QuarryError:
            logger.warning(
                "captures purge for %s was rejected; its chunks may remain, but "
                "the project is fully disabled (deregistered + local files removed)",
                captures_collection,
            )

    return DisableResult(
        directory=str(directory),
        collection=collection,
        captures_collection=captures_collection,
        removed=removed,
        config_removed=config_removed,
        import_pruned=claudemd.import_pruned,
        enabled_marker_removed=claudemd.enabled_marker_removed,
    )


def _write_project_config(directory: Path) -> str:
    """Write config.md atomically (O_CREAT|O_EXCL, no overwrite); return its path."""
    config_dir = directory / ".punt-labs" / "quarry"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.md"
    try:
        fd = os.open(str(config_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            with os.fdopen(fd, "w") as f:
                fd = -1  # fdopen took ownership before write
                f.write(_CONFIG_TEMPLATE)
        finally:
            if fd >= 0:
                os.close(fd)
    except FileExistsError:
        pass
    return str(config_path)
