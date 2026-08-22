"""Doctor check: propagate quarry memory instructions into ethos identity exts."""

from __future__ import annotations

from pathlib import Path
from typing import final

from quarry.results import CheckResult

_SESSION_CONTEXT_TEMPLATE = """\
## Memory

You have persistent memory stored in quarry, a local semantic
search engine. Your memories survive across sessions and machines.

### Working Memory

Collection: "{memory_collection}"

To recall prior knowledge:
  /find <query> — or use the quarry find tool with
  collection="{memory_collection}", agent_handle="{handle}"

To persist something you learned:
  /remember <content> — or use the quarry remember tool with
  collection="{memory_collection}", agent_handle="{handle}",
  memory_type=fact|observation|procedure|opinion

Memory types:
- fact: objective, verifiable information ("the API rate limit is 100 req/s")
- observation: neutral summary of an entity or system
- procedure: how-to knowledge ("when deploying, run migrations first")
- opinion: subjective assessment with confidence
"""


@final
class EthosExtDiagnostics:
    """Write ``session_context`` into each identity's ``quarry.yaml`` ext.

    Idempotent: leaves an existing ``session_context`` key unchanged. Skips
    identity directories that have no ``quarry.yaml`` (quarry not configured
    for that identity). Moved out of ``doctor.py`` so the diagnostics god
    module no longer owns the ethos ext write path directly; ``ethos_memory``
    reuses :meth:`write_session_context` for the ``quarry enable`` path.
    """

    __slots__ = ()

    @staticmethod
    def configure(identities_dir: Path | None = None) -> CheckResult:
        """Best-effort install step: write session_context for every identity."""
        if identities_dir is None:
            identities_dir = Path.home() / ".punt-labs" / "ethos" / "identities"

        if not identities_dir.exists():
            return CheckResult(
                name="Ethos ext session_context",
                passed=True,
                message="ethos not installed, skipping",
                required=False,
            )

        updated, already_set, no_collection, failed = EthosExtDiagnostics._scan(
            identities_dir
        )

        if not updated and not already_set and not no_collection and not failed:
            return CheckResult(
                name="Ethos ext session_context",
                passed=True,
                message="no identities with quarry configured",
                required=False,
            )

        return CheckResult(
            name="Ethos ext session_context",
            passed=not failed,
            message=EthosExtDiagnostics._message(
                updated, already_set, no_collection, failed
            ),
            required=False,
        )

    @staticmethod
    def write_session_context(quarry_yaml: Path, handle: str) -> str:
        """Write session_context into one quarry.yaml if missing.

        Returns:
            "updated"      — session_context was appended
            "already_set"  — session_context key already present, file unchanged
            "no_collection"— memory_collection absent, nothing to do
        """
        import yaml  # noqa: PLC0415

        raw = quarry_yaml.read_text(encoding="utf-8")

        data = yaml.safe_load(raw) or {}
        if not isinstance(data, dict):
            return "no_collection"
        if "session_context" in data:
            return "already_set"

        memory_collection = data.get("memory_collection")
        if not memory_collection:
            return "no_collection"

        fragment = EthosExtDiagnostics._literal_block(handle, str(memory_collection))
        with quarry_yaml.open("a", encoding="utf-8") as fh:
            fh.write(fragment)
        return "updated"

    @staticmethod
    def _literal_block(handle: str, memory_collection: str) -> str:
        """Return a YAML literal block scalar fragment for session_context.

        The fragment starts with a newline so it appends cleanly to an existing
        file that may or may not end with a newline. Each body line is indented
        two spaces as required for a YAML literal block scalar.
        """
        body = _SESSION_CONTEXT_TEMPLATE.format(
            handle=handle,
            memory_collection=memory_collection,
        )
        indented = "\n".join(f"  {line}" for line in body.splitlines())
        return f"\nsession_context: |\n{indented}\n"

    @staticmethod
    def _scan(
        identities_dir: Path,
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        """Iterate identity ext dirs and classify each quarry.yaml.

        Returns (updated, already_set, no_collection, failed).
        """
        updated: list[str] = []
        already_set: list[str] = []
        no_collection: list[str] = []
        failed: list[str] = []

        for ext_dir in sorted(identities_dir.iterdir()):
            if not ext_dir.is_dir() or not ext_dir.name.endswith(".ext"):
                continue
            handle = ext_dir.name[: -len(".ext")]
            quarry_yaml = ext_dir / "quarry.yaml"
            if not quarry_yaml.exists():
                continue
            try:
                result = EthosExtDiagnostics.write_session_context(quarry_yaml, handle)
                if result == "updated":
                    updated.append(handle)
                elif result == "already_set":
                    already_set.append(handle)
                elif result == "no_collection":
                    no_collection.append(handle)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{handle}: {exc}")

        return updated, already_set, no_collection, failed

    @staticmethod
    def _message(
        updated: list[str],
        already_set: list[str],
        no_collection: list[str],
        failed: list[str],
    ) -> str:
        """Build the result message for configure()."""

        def _plural(lst: list[str]) -> str:
            return "identity" if len(lst) == 1 else "identities"

        parts: list[str] = []
        if updated:
            parts.append(
                f"updated {len(updated)} {_plural(updated)}: {', '.join(updated)}"
            )
        if already_set:
            if not updated:
                parts.append(f"session_context already set: {', '.join(already_set)}")
            else:
                parts.append(f"already set: {', '.join(already_set)}")
        if no_collection:
            parts.append(
                f"no memory_collection (check config): {', '.join(no_collection)}"
            )
        if failed:
            parts.append(f"errors: {'; '.join(failed)}")
        return "; ".join(parts)
