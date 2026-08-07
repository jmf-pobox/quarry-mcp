from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from quarry.logging_config import LoggingConfig

if TYPE_CHECKING:
    import pytest


def test_env_var_overrides_stderr_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """QUARRY_LOG_LEVEL overrides the stderr_level parameter."""
    monkeypatch.setenv("QUARRY_LOG_LEVEL", "DEBUG")
    with patch("quarry.logging_config.logging.config.dictConfig") as mock_dc:
        LoggingConfig.configure(stderr_level="WARNING")
    config = mock_dc.call_args[0][0]
    assert config["handlers"]["stderr"]["level"] == "DEBUG"


def test_invalid_env_var_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid QUARRY_LOG_LEVEL is ignored; parameter value is used."""
    monkeypatch.setenv("QUARRY_LOG_LEVEL", "NONSENSE")
    with patch("quarry.logging_config.logging.config.dictConfig") as mock_dc:
        LoggingConfig.configure(stderr_level="WARNING")
    config = mock_dc.call_args[0][0]
    assert config["handlers"]["stderr"]["level"] == "WARNING"


def test_no_env_var_uses_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without QUARRY_LOG_LEVEL, the parameter controls stderr level."""
    monkeypatch.delenv("QUARRY_LOG_LEVEL", raising=False)
    with patch("quarry.logging_config.logging.config.dictConfig") as mock_dc:
        LoggingConfig.configure(stderr_level="INFO")
    config = mock_dc.call_args[0][0]
    assert config["handlers"]["stderr"]["level"] == "INFO"


def test_third_party_loggers_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Third-party loggers are pinned at WARNING to prevent DEBUG floods."""
    monkeypatch.delenv("QUARRY_LOG_LEVEL", raising=False)
    with patch("quarry.logging_config.logging.config.dictConfig") as mock_dc:
        LoggingConfig.configure()
    config = mock_dc.call_args[0][0]
    for name in ("lancedb", "onnxruntime", "httpx"):
        assert config["loggers"][name]["level"] == "WARNING"


class TestLogDirResolution:
    """The destination is resolved per call, so a caller can move it."""

    def test_env_var_selects_the_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("QUARRY_LOG_DIR", str(tmp_path / "logs"))
        assert LoggingConfig.log_dir() == tmp_path / "logs"

    def test_absent_env_var_falls_back_to_home(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("QUARRY_LOG_DIR", raising=False)
        expected = Path.home() / ".punt-labs" / "quarry" / "logs"
        assert LoggingConfig.log_dir() == expected

    def test_empty_env_var_falls_back_to_home(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An exported-but-blank variable must not resolve the log to ``.``."""
        monkeypatch.setenv("QUARRY_LOG_DIR", "")
        expected = Path.home() / ".punt-labs" / "quarry" / "logs"
        assert LoggingConfig.log_dir() == expected

    def test_configure_writes_the_handler_under_the_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        target = tmp_path / "redirected"
        monkeypatch.setenv("QUARRY_LOG_DIR", str(target))
        with patch("quarry.logging_config.logging.config.dictConfig") as mock_dc:
            LoggingConfig.configure()
        config = mock_dc.call_args[0][0]
        assert config["handlers"]["file"]["filename"] == str(target / "quarry.log")
        assert target.is_dir(), "configure must create the directory it names"
