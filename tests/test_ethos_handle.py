"""Behavior of :func:`quarry.ethos_handle.read_agent_handle`.

Fresh module without a caller yet — hooks.py still carries its own inline
walker under a temporary duplication that the follow-up bead resolves. Until
then this suite is the sole exercise of the shared helper.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from quarry.ethos_handle import read_agent_handle

if TYPE_CHECKING:
    import pytest


def _write_config(root: Path, body: str) -> None:
    """Deposit an ethos config at ``root/.punt-labs/ethos/config.yaml``."""
    config_dir = root / ".punt-labs" / "ethos"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text(body)


class TestReadAgentHandle:
    def test_returns_agent_from_direct_config(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "agent: rmh\n")
        assert read_agent_handle(str(tmp_path)) == "rmh"

    def test_walks_up_to_ancestor_config(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "agent: kpz\n")
        deep = tmp_path / "src" / "quarry" / "retrieval"
        deep.mkdir(parents=True)
        assert read_agent_handle(str(deep)) == "kpz"

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        # No config anywhere on the walk — the walker must not raise, since
        # the empty string is the documented "no identity here" signal.
        assert read_agent_handle(str(tmp_path)) == ""

    def test_missing_agent_field_returns_empty(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "other: value\n")
        assert read_agent_handle(str(tmp_path)) == ""

    def test_non_string_agent_returns_empty(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "agent: 42\n")
        assert read_agent_handle(str(tmp_path)) == ""

    def test_blank_agent_returns_empty(self, tmp_path: Path) -> None:
        _write_config(tmp_path, 'agent: ""\n')
        assert read_agent_handle(str(tmp_path)) == ""

    def test_malformed_yaml_returns_empty(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _write_config(tmp_path, "agent: [unclosed\n")
        with caplog.at_level("WARNING", logger="quarry.ethos_handle"):
            assert read_agent_handle(str(tmp_path)) == ""
        assert any("could not parse" in rec.message for rec in caplog.records)
