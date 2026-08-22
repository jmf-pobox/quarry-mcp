"""Tests for the ethos-memory bootstrap."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from quarry.ethos_memory import EthosMemoryBootstrap, EthosMemoryResult

if TYPE_CHECKING:
    import pytest


def test_result_memory_collections_derived_from_created() -> None:
    result = EthosMemoryResult(created=["claude", "rmh"])
    assert result.memory_collections == ["memory-claude", "memory-rmh"]


def test_skips_when_identities_dir_missing(tmp_path: Path) -> None:
    result = EthosMemoryBootstrap(tmp_path / "nonexistent").run()
    assert result.skipped is True
    assert result.created == []


def test_creates_quarry_yaml_files(tmp_path: Path) -> None:
    identities = tmp_path / "identities"
    identities.mkdir()
    (identities / "claude.yaml").write_text("agent: claude\n")
    (identities / "rmh.yaml").write_text("agent: rmh\n")

    result = EthosMemoryBootstrap(identities).run()

    assert result.skipped is False
    assert result.failed == []
    assert "claude" in result.created
    assert "rmh" in result.created
    assert set(result.updated) == {"claude", "rmh"}
    assert result.already_set == []

    claude_yaml = identities / "claude.ext" / "quarry.yaml"
    rmh_yaml = identities / "rmh.ext" / "quarry.yaml"
    assert "memory_collection: memory-claude" in claude_yaml.read_text()
    assert "memory_collection: memory-rmh" in rmh_yaml.read_text()


def test_existing_quarry_yaml_not_modified(tmp_path: Path) -> None:
    identities = tmp_path / "identities"
    identities.mkdir()
    (identities / "claude.yaml").write_text("agent: claude\n")
    ext_dir = identities / "claude.ext"
    ext_dir.mkdir()
    quarry_yaml = ext_dir / "quarry.yaml"
    quarry_yaml.write_text("memory_collection: wrong-name\n")

    result = EthosMemoryBootstrap(identities).run()

    assert result.skipped is False
    assert "claude" not in result.created
    assert "memory_collection: wrong-name" in quarry_yaml.read_text()


def test_bad_yaml_is_recorded_and_bootstrap_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identities = tmp_path / "identities"
    identities.mkdir()
    (identities / "alice.yaml").write_text("agent: alice\n")
    (identities / "bad.yaml").write_text("agent: bad\n")

    from yaml import YAMLError

    from quarry.doctor_ethos import EthosExtDiagnostics

    original_write = EthosExtDiagnostics.write_session_context

    def selective_raise(quarry_yaml: Path, handle: str) -> str:
        if handle == "bad":
            msg = "simulated YAML parse failure"
            raise YAMLError(msg)
        return original_write(quarry_yaml, handle)

    monkeypatch.setattr(
        "quarry.doctor_ethos.EthosExtDiagnostics.write_session_context",
        selective_raise,
    )

    result = EthosMemoryBootstrap(identities).run()

    assert result.skipped is False
    assert "alice" in result.created
    # bad's quarry.yaml file was written (so it's "created"), but the
    # session_context write raised — it lands in failed, never updated.
    assert "bad" in result.created
    assert "bad" in result.failed
    assert "bad" not in result.updated
    assert "bad" not in result.already_set
    assert (identities / "alice.ext" / "quarry.yaml").exists()
    assert (identities / "bad.ext" / "quarry.yaml").exists()


def test_non_utf8_identity_file_recorded_not_fatal(tmp_path: Path) -> None:
    # A non-UTF8/corrupt ext quarry.yaml makes the reader raise UnicodeDecodeError
    # (a ValueError, not OSError). The bootstrap records the handle and continues.
    identities = tmp_path / "identities"
    identities.mkdir()
    (identities / "alice.yaml").write_text("agent: alice\n")
    ext_dir = identities / "alice.ext"
    ext_dir.mkdir()
    (ext_dir / "quarry.yaml").write_bytes(b"memory_collection: \xff\xfe bad\n")

    result = EthosMemoryBootstrap(identities).run()

    assert result.skipped is False
    assert "alice" in result.failed
    assert "alice" not in result.updated
    assert "alice" not in result.already_set
