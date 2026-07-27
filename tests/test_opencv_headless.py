"""Tests for the headless-OpenCV enforcer used by ``quarry install``."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from quarry.opencv_headless import HeadlessOpenCv

if TYPE_CHECKING:
    import pytest


def test_command_prefers_uv_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("quarry.opencv_headless.shutil.which", lambda _: "/usr/bin/uv")
    cmd = HeadlessOpenCv("/venv/bin/python")._reinstall_command()
    assert cmd[:5] == ["/usr/bin/uv", "pip", "install", "--python", "/venv/bin/python"]
    assert cmd[-3:] == ["--force-reinstall", "--no-deps", "opencv-python-headless"]


def test_command_falls_back_to_pip_when_no_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("quarry.opencv_headless.shutil.which", lambda _: None)
    cmd = HeadlessOpenCv("/venv/bin/python")._reinstall_command()
    assert cmd == [
        "/venv/bin/python",
        "-m",
        "pip",
        "install",
        "--force-reinstall",
        "--no-deps",
        "opencv-python-headless",
    ]


def test_remediation_is_the_reinstall_command_as_a_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The operator hint printed by `quarry install` must be the actual command.
    monkeypatch.setattr("quarry.opencv_headless.shutil.which", lambda _: None)
    hint = HeadlessOpenCv("/venv/bin/python").remediation()
    assert hint == (
        "/venv/bin/python -m pip install "
        "--force-reinstall --no-deps opencv-python-headless"
    )


def test_enforce_runs_the_command(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> object:
        recorded.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("quarry.opencv_headless.shutil.which", lambda _: None)
    monkeypatch.setattr(subprocess, "run", fake_run)
    msg = HeadlessOpenCv("/venv/bin/python").enforce()
    assert recorded and recorded[0][-1] == "opencv-python-headless"
    assert "opencv-python-headless" in msg


def test_enforce_propagates_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **_kwargs: object) -> object:
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr("quarry.opencv_headless.shutil.which", lambda _: None)
    monkeypatch.setattr(subprocess, "run", fake_run)
    try:
        HeadlessOpenCv("/venv/bin/python").enforce()
    except subprocess.CalledProcessError:
        return
    msg = "enforce did not propagate the reinstall failure"
    raise AssertionError(msg)
