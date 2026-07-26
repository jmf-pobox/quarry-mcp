"""Tests for ThreadConfig — ONNX/OMP thread budget derivation (DES-032).

Verifies the hardware/provider-to-thread-count mapping and the environment-cap
side effects directly, without constructing the full ONNX backend.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from quarry.thread_config import ThreadConfig

if TYPE_CHECKING:
    import pytest


class TestIntraOpThreads:
    def test_gpu_uses_one_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # GPU offloads GEMMs to CUDA; one CPU feeder thread suffices.
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        assert ThreadConfig(is_gpu=True).intra_op_threads == 1

    def test_cpu_caps_at_two(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        assert ThreadConfig(is_gpu=False).intra_op_threads == 2

    def test_cpu_below_cap_uses_ncpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("os.cpu_count", lambda: 1)
        assert ThreadConfig(is_gpu=False).intra_op_threads == 1

    def test_unknown_cpu_count_falls_back_to_four(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # os.cpu_count() can return None; ThreadConfig must not crash.
        monkeypatch.setattr("os.cpu_count", lambda: None)
        assert ThreadConfig(is_gpu=False).intra_op_threads == 2

    def test_unknown_cpu_count_warns(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The None->4 fallback must not be silent: an operator needs to know the
        # thread budget was guessed, not measured.
        monkeypatch.setattr("os.cpu_count", lambda: None)
        with caplog.at_level(logging.WARNING, logger="quarry.thread_config"):
            ThreadConfig(is_gpu=False)
        assert any(
            "os.cpu_count() returned None" in rec.getMessage() for rec in caplog.records
        )

    def test_known_cpu_count_does_not_warn(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        with caplog.at_level(logging.WARNING, logger="quarry.thread_config"):
            ThreadConfig(is_gpu=False)
        assert not any("returned None" in rec.getMessage() for rec in caplog.records)


class TestApplyEnvLimits:
    def test_sets_tokenizers_parallelism_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.delenv("TOKENIZERS_PARALLELISM", raising=False)
        ThreadConfig(is_gpu=False).apply_env_limits()
        assert os.environ.get("TOKENIZERS_PARALLELISM") == "false"

    def test_sets_omp_to_min_two_ncpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
        ThreadConfig(is_gpu=False).apply_env_limits()
        assert os.environ.get("OMP_NUM_THREADS") == "2"

    def test_omp_is_one_on_single_core(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("os.cpu_count", lambda: 1)
        monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
        ThreadConfig(is_gpu=False).apply_env_limits()
        assert os.environ.get("OMP_NUM_THREADS") == "1"

    def test_clamps_operator_override_above_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A HIGHER inherited value (stale export, dev shell) must clamp DOWN to the
        # cap — setdefault would have let 7 survive and defeat the ceiling.
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.setenv("OMP_NUM_THREADS", "7")
        ThreadConfig(is_gpu=False).apply_env_limits()
        assert os.environ.get("OMP_NUM_THREADS") == "2"

    def test_inherited_thirtytwo_clamps_to_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The exact scenario djb named: a shell exports 32, the daemon must not
        # inherit it. Clamp to the DES-032 cap of 2.
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.setenv("OMP_NUM_THREADS", "32")
        monkeypatch.setenv("LANCE_CPU_THREADS", "32")
        ThreadConfig(is_gpu=False).apply_env_limits()
        assert os.environ.get("OMP_NUM_THREADS") == "2"
        assert os.environ.get("LANCE_CPU_THREADS") == "2"

    def test_honors_operator_override_below_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A LOWER inherited value is an intentional tightening — honor it.
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.setenv("OMP_NUM_THREADS", "1")
        monkeypatch.setenv("LANCE_CPU_THREADS", "1")
        ThreadConfig(is_gpu=False).apply_env_limits()
        assert os.environ.get("OMP_NUM_THREADS") == "1"
        assert os.environ.get("LANCE_CPU_THREADS") == "1"

    def test_non_numeric_preset_clamps_to_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A junk preset must fail closed to the cap, not survive as-is.
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.setenv("LANCE_CPU_THREADS", "garbage")
        ThreadConfig(is_gpu=False).apply_env_limits()
        assert os.environ.get("LANCE_CPU_THREADS") == "2"

    def test_zero_preset_clamps_to_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 0 means "auto/unbounded" to lance — never honor it as a lower value.
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.setenv("LANCE_CPU_THREADS", "0")
        ThreadConfig(is_gpu=False).apply_env_limits()
        assert os.environ.get("LANCE_CPU_THREADS") == "2"

    def test_downward_clamp_warns(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A too-high preset means the ceiling was almost defeated; the logs must
        # record the clamp rather than silently accept the inherited value.
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.setenv("OMP_NUM_THREADS", "7")
        with caplog.at_level(logging.WARNING, logger="quarry.thread_config"):
            ThreadConfig(is_gpu=False).apply_env_limits()
        warnings = [
            r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("clamping to 2" in m for m in warnings)
        assert any("'7'" in m for m in warnings)

    def test_logs_effective_clamped_omp(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The info line reports the value actually in force (the clamped 2), not
        # the rejected preset.
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.setenv("OMP_NUM_THREADS", "7")
        with caplog.at_level(logging.INFO, logger="quarry.thread_config"):
            ThreadConfig(is_gpu=False).apply_env_limits()
        rendered = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert any("OMP=2" in line for line in rendered)
        assert not any("OMP=7" in line for line in rendered)

    def test_honored_lower_override_does_not_warn(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.setenv("OMP_NUM_THREADS", "1")
        with caplog.at_level(logging.WARNING, logger="quarry.thread_config"):
            ThreadConfig(is_gpu=False).apply_env_limits()
        assert not any("clamping" in r.getMessage() for r in caplog.records)

    def test_no_warning_when_cap_applied(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
        with caplog.at_level(logging.WARNING, logger="quarry.thread_config"):
            ThreadConfig(is_gpu=False).apply_env_limits()
        assert not any("clamping" in r.getMessage() for r in caplog.records)

    def test_apply_returns_self(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        config = ThreadConfig(is_gpu=False)
        assert config.apply_env_limits() is config


class TestLanceThreadCap:
    """The LanceDB compute-pool ceiling — the daemon's structural CPU bound."""

    def test_caps_lance_cpu_threads_at_two(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # On 8 cores lance would otherwise size its compute pool to 8 and flood
        # every core during compaction; the cap holds it at 2 (300-400% -> ~2x).
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.delenv("LANCE_CPU_THREADS", raising=False)
        ThreadConfig(is_gpu=False).apply_env_limits()
        assert os.environ.get("LANCE_CPU_THREADS") == "2"

    def test_caps_lance_io_threads_at_two(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.delenv("LANCE_IO_THREADS", raising=False)
        ThreadConfig(is_gpu=False).apply_env_limits()
        assert os.environ.get("LANCE_IO_THREADS") == "2"

    def test_lance_cap_is_provider_independent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The daemon holds the LanceDB connection regardless of GPU embedding, so
        # the compute cap must apply on GPU too (unlike ONNX intra_op).
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.delenv("LANCE_CPU_THREADS", raising=False)
        ThreadConfig(is_gpu=True).apply_env_limits()
        assert os.environ.get("LANCE_CPU_THREADS") == "2"

    def test_clamps_lance_override_above_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A higher inherited LANCE_CPU_THREADS must clamp down — the daemon must
        # not seize 4 cores because a shell exported 4.
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.setenv("LANCE_CPU_THREADS", "4")
        ThreadConfig(is_gpu=False).apply_env_limits()
        assert os.environ.get("LANCE_CPU_THREADS") == "2"

    def test_divergent_lance_preset_warns(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.setenv("LANCE_CPU_THREADS", "6")
        with caplog.at_level(logging.WARNING, logger="quarry.thread_config"):
            ThreadConfig(is_gpu=False).apply_env_limits()
        warnings = [
            r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("LANCE_CPU_THREADS preset to '6'" in m for m in warnings)
        assert any("clamping to 2" in m for m in warnings)

    def test_info_line_reports_lance_cap(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        monkeypatch.delenv("LANCE_CPU_THREADS", raising=False)
        with caplog.at_level(logging.INFO, logger="quarry.thread_config"):
            ThreadConfig(is_gpu=False).apply_env_limits()
        assert any("LANCE_CPU=2" in r.getMessage() for r in caplog.records)
