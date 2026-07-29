"""Unit tests for the daemon's file-descriptor envelope and its config target.

Cross-platform: the ``resource`` module is replaced with a fake, so the raise,
clamp, never-lower, and every fail-safe degrade path are exercised without
touching the real process ``RLIMIT_NOFILE`` on any host.
"""

from __future__ import annotations

import logging
from typing import ClassVar, Self, final

import pytest

from quarry import fd_config
from quarry.config import Settings
from quarry.fd_config import FdEnvelope


@final
class _FakeResource:
    """A ``resource`` stand-in that records setrlimit and can be told to raise."""

    RLIMIT_NOFILE: ClassVar[int] = 7
    RLIM_INFINITY: ClassVar[int] = 2**63 - 1

    __slots__ = ("_get_exc", "_limits", "_set_args", "_set_exc")

    _limits: tuple[int, int]
    _get_exc: OSError | None
    _set_exc: OSError | ValueError | None
    _set_args: tuple[int, tuple[int, int]] | None

    def __new__(
        cls,
        *,
        soft: int,
        hard: int,
        get_exc: OSError | None = None,
        set_exc: OSError | ValueError | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._limits = (soft, hard)
        self._get_exc = get_exc
        self._set_exc = set_exc
        self._set_args = None
        return self

    def getrlimit(self, _which: int) -> tuple[int, int]:
        """Return the current (soft, hard), or raise the configured error."""
        if self._get_exc is not None:
            raise self._get_exc
        return self._limits

    def setrlimit(self, which: int, limits: tuple[int, int]) -> None:
        """Record and apply (soft, hard), or raise the configured error."""
        if self._set_exc is not None:
            raise self._set_exc
        self._set_args = (which, limits)
        self._limits = limits

    @property
    def set_args(self) -> tuple[int, tuple[int, int]] | None:
        """The (which, (soft, hard)) of the last setrlimit call, or ``None``."""
        return self._set_args


def test_raise_below_target(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeResource(soft=256, hard=1_000_000)
    monkeypatch.setattr(fd_config, "resource", fake)
    state = FdEnvelope(target=8192).apply()
    assert fake.set_args == (_FakeResource.RLIMIT_NOFILE, (8192, 1_000_000))
    assert "raised" in state


def test_clamp_to_hard(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeResource(soft=256, hard=4096)
    monkeypatch.setattr(fd_config, "resource", fake)
    FdEnvelope(target=8192).apply()
    # Effective clamps to the hard limit — never a value above it.
    assert fake.set_args == (_FakeResource.RLIMIT_NOFILE, (4096, 4096))


def test_never_lower_inherited_higher_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeResource(soft=65536, hard=1_000_000)
    monkeypatch.setattr(fd_config, "resource", fake)
    state = FdEnvelope(target=8192).apply()
    assert fake.set_args is None  # a higher inherited soft (systemd) is honored
    assert "unchanged" in state


def test_rlim_infinity_hard_sets_target(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeResource(soft=256, hard=_FakeResource.RLIM_INFINITY)
    monkeypatch.setattr(fd_config, "resource", fake)
    FdEnvelope(target=8192).apply()
    # Unbounded hard: the target is set as-is, no clamp.
    infinity = _FakeResource.RLIM_INFINITY
    assert fake.set_args == (_FakeResource.RLIMIT_NOFILE, (8192, infinity))


@pytest.mark.parametrize("exc", [OSError("boom"), ValueError("bad limit")])
def test_degrade_when_setrlimit_raises(
    monkeypatch: pytest.MonkeyPatch, exc: OSError | ValueError
) -> None:
    fake = _FakeResource(soft=256, hard=1_000_000, set_exc=exc)
    monkeypatch.setattr(fd_config, "resource", fake)
    state = FdEnvelope(target=8192).apply()  # must not propagate (Bug-class-2)
    assert "unchanged" in state
    assert "failed" in state


def test_degrade_when_getrlimit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeResource(soft=256, hard=1_000_000, get_exc=OSError("nope"))
    monkeypatch.setattr(fd_config, "resource", fake)
    state = FdEnvelope(target=8192).apply()  # must not propagate
    assert fake.set_args is None
    assert "getrlimit failed" in state


def test_degrade_when_resource_module_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fd_config, "resource", None)
    state = FdEnvelope(target=8192).apply()  # must not call setrlimit, must not raise
    assert "unavailable" in state


def test_fd_limit_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUARRY_FD_LIMIT", raising=False)
    assert Settings().fd_limit == 8192


def test_fd_limit_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUARRY_FD_LIMIT", "65536")
    assert Settings().fd_limit == 65536


def test_fd_limit_malformed_degrades(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("QUARRY_FD_LIMIT", "not-a-number")
    with caplog.at_level(logging.WARNING):
        settings = Settings()  # must not raise a ValidationError (Bug-class-2)
    assert settings.fd_limit == 8192
    assert "QUARRY_FD_LIMIT" in caplog.text


def test_fd_limit_nonpositive_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUARRY_FD_LIMIT", "0")
    assert Settings().fd_limit == 8192
