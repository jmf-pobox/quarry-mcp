"""Thread-pool limits for ONNX inference and LanceDB compaction.

Concurrent quarry processes (serve daemon, ingest worker, CLI) each default to
ncpu rayon + ncpu ONNX threads — three on 8 cores reach load ~148 and starve the
query path.  ``ThreadConfig`` caps the budget per hardware/provider: GPU offloads
GEMMs to CUDA (1 feeder thread), CPU caps at 2 (DES-027 arena).  See DES-032.

LanceDB is the second, larger offender.  Its Rust core builds a tokio compute
runtime sized to ``num_cpus`` and floods every core during ``optimize()`` /
``create_fts_index`` — the daemon's watch loop fires these on ordinary file
churn, spiking to 300-400% CPU.  ``LANCE_CPU_THREADS`` is a hard ceiling on that
compute pool: lance builds the runtime with exactly that many workers and cannot
exceed it regardless of churn or core count.  Two is the floor — one stalls
lance's runtime (an internal operation needs a second worker to make progress).
"""

from __future__ import annotations

import logging
import os
from typing import Protocol, Self

logger = logging.getLogger(__name__)

_MAX_CPU_THREADS = 2
# LanceDB's compute pool floors at 2: LANCE_CPU_THREADS=1 stalls the runtime
# (observed 0% CPU / no progress on a compaction loop), so a one-core machine's
# lance work is not bounded below 2 — acceptable, one core cannot seize many.
_MAX_LANCE_THREADS = 2
_NCPU_NONE = 4  # fallback when os.cpu_count() returns None


class _SessionOptions(Protocol):
    """The ONNX ``SessionOptions`` thread knobs, typed without importing it."""

    intra_op_num_threads: int
    inter_op_num_threads: int


class ThreadConfig:
    """Hardware/provider-derived thread budget for one ONNX session."""

    _ncpu: int
    _intra_op_threads: int
    _omp_threads: int
    _lance_threads: int

    def __new__(cls, *, is_gpu: bool) -> Self:
        self = super().__new__(cls)
        if (detected := os.cpu_count()) is None:
            logger.warning("os.cpu_count() returned None; assuming %d CPUs", _NCPU_NONE)
        self._ncpu = detected or _NCPU_NONE
        self._omp_threads = min(_MAX_CPU_THREADS, self._ncpu)
        # GPU does the GEMMs (1 feeder thread); CPU caps at 2 (DES-027 arena).
        self._intra_op_threads = 1 if is_gpu else min(_MAX_CPU_THREADS, self._ncpu)
        # LanceDB's compute pool is provider-independent (the daemon holds the
        # connection whether or not the GPU embeds), so cap it the same way.
        self._lance_threads = min(_MAX_LANCE_THREADS, self._ncpu)
        return self

    @classmethod
    def for_provider(cls, provider: str) -> Self:
        """Build a budget for an ONNX provider name (e.g. CUDAExecutionProvider)."""
        return cls(is_gpu=provider == "CUDAExecutionProvider")

    @property
    def intra_op_threads(self) -> int:
        """ONNX intra-op thread count for this hardware/provider."""
        return self._intra_op_threads

    def apply_to_session(self, sess_options: _SessionOptions) -> None:
        """Set the ONNX intra/inter-op thread counts on *sess_options*."""
        sess_options.intra_op_num_threads = self._intra_op_threads
        # Inter-op stays 1: DES-027's narenas:1 means extra threads only contend.
        sess_options.inter_op_num_threads = 1

    def apply_env_limits(self) -> Self:
        """Cap the rayon/OMP and LanceDB thread pools for this whole process.

        Idempotent (``setdefault``), so a redundant call from the embedding
        backend after the daemon boot call is a no-op.  Must run before the first
        ``lancedb.connect`` — lance reads ``LANCE_CPU_THREADS`` once when it
        builds its compute runtime, so a later set is ignored.
        """
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        omp = self._cap_env("OMP_NUM_THREADS", self._omp_threads)
        # LanceDB's tokio compute pool (compaction, FTS rebuild) — the hard
        # ceiling that stops the daemon seizing every core on watch-loop churn.
        self._cap_env("LANCE_CPU_THREADS", self._lance_threads)
        self._cap_env("LANCE_IO_THREADS", self._lance_threads)
        logger.info(
            "Thread config: intra_op=%d, inter_op=1, OMP=%s, LANCE_CPU=%d (ncpu=%d)",
            self._intra_op_threads,
            omp,
            self._lance_threads,
            self._ncpu,
        )
        return self

    @staticmethod
    def _cap_env(name: str, cap: int) -> str:
        """Set ``name`` to ``cap`` unless preset; return the effective value.

        Warns when an operator preset diverges from the cap — the DES-032
        oversubscription mitigation is then only as tight as the preset.
        """
        os.environ.setdefault(name, str(cap))
        value = os.environ[name]
        if value != str(cap):
            logger.warning(
                "%s preset to %s, not the cap %d; DES-032 oversubscription "
                "mitigation may be defeated",
                name,
                value,
                cap,
            )
        return value
