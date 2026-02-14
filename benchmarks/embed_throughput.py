"""Embedding throughput benchmark.

Measures chunks/second for the ONNX embedding backend under controlled
conditions.  Requires the model to be installed (``quarry install``).

Usage::

    uv run python benchmarks/embed_throughput.py

Reports:
    - Warmup cost (first-batch latency)
    - Single-thread throughput at varying input sizes
    - Per-batch overhead (session.run call cost)
    - Concurrent throughput with 2 workers (matching sync defaults)
"""

from __future__ import annotations

import platform
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# Synthetic text generation
# ---------------------------------------------------------------------------

# Vocabulary drawn from real chunk content across formats.  Not random bytes —
# realistic token density matters because tokenization time is proportional.
_VOCABULARY = (
    "the of and to a in is that for it was on are as with his they be at one "
    "have this from or had by not but what all were when we there can an your "
    "which their said if do will each about how up out them then she many some "
    "so these would other into has her two like him see time could no make than "
    "first been its who now people my made over did down way only little after "
    "long great just where those came come right used take three states through "
    "data analysis results model system performance method approach figure table "
    "function return value class import type error output input parameter index "
    "revenue quarterly growth margin operating income fiscal year period ended "
).split()


def _generate_text(target_chars: int, rng: random.Random) -> str:
    """Generate synthetic text of approximately *target_chars* characters."""
    words: list[str] = []
    length = 0
    while length < target_chars:
        word = rng.choice(_VOCABULARY)
        words.append(word)
        length += len(word) + 1  # +1 for space
    return " ".join(words)[:target_chars]


def _generate_corpus(
    n: int,
    min_chars: int = 200,
    max_chars: int = 1800,
    seed: int = 42,
) -> list[str]:
    """Generate *n* synthetic texts with lengths uniformly distributed."""
    rng = random.Random(seed)
    return [_generate_text(rng.randint(min_chars, max_chars), rng) for _ in range(n)]


# ---------------------------------------------------------------------------
# Benchmark harness
# ---------------------------------------------------------------------------


def _print_header(label: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")


def _print_row(label: str, value: str) -> None:
    print(f"  {label:<36} {value}")


def main() -> None:
    # Late import so missing model gives a clear error
    try:
        from quarry.embeddings import OnnxEmbeddingBackend
    except Exception as exc:
        print(f"Cannot load embedding backend: {exc}", file=sys.stderr)
        print("Run 'quarry install' first.", file=sys.stderr)
        sys.exit(1)

    _print_header("Environment")
    _print_row("Platform", platform.platform())
    _print_row("Processor", platform.processor())
    _print_row("Python", platform.python_version())

    print("\nLoading model...", end=" ", flush=True)
    t0 = time.perf_counter()
    backend = OnnxEmbeddingBackend()
    model_load = time.perf_counter() - t0
    print(f"done ({model_load:.2f}s)")
    _print_row("Model", backend.model_name)
    _print_row("Dimension", str(backend.dimension))

    # ── Warmup ────────────────────────────────────────────────────────────
    _print_header("Warmup (first inference)")
    warmup_texts = _generate_corpus(1)
    t0 = time.perf_counter()
    backend.embed_texts(warmup_texts)
    warmup_time = time.perf_counter() - t0
    _print_row("First-call latency", f"{warmup_time:.3f}s")

    # ── Single-thread throughput ──────────────────────────────────────────
    _print_header("Single-thread throughput")
    sizes = [32, 64, 128, 256, 512, 1024]
    results: list[tuple[int, float, float]] = []

    for n in sizes:
        corpus = _generate_corpus(n)
        # Run 3 trials, take the median
        times: list[float] = []
        for _ in range(3):
            t0 = time.perf_counter()
            backend.embed_texts(corpus)
            elapsed = time.perf_counter() - t0
            times.append(elapsed)
        median = statistics.median(times)
        throughput = n / median
        results.append((n, median, throughput))
        _print_row(
            f"{n:>5} chunks",
            f"{median:>6.2f}s  ({throughput:>6.1f} chunks/s)",
        )

    # ── Concurrent throughput (2 workers) ─────────────────────────────────
    _print_header("Concurrent throughput (2 workers)")
    for n in [256, 512]:
        corpus = _generate_corpus(n)
        # Split into 2 equal halves
        half = n // 2
        batch_a = corpus[:half]
        batch_b = corpus[half:]

        times_concurrent: list[float] = []
        for _ in range(3):
            t0 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=2) as executor:
                fa = executor.submit(backend.embed_texts, batch_a)
                fb = executor.submit(backend.embed_texts, batch_b)
                fa.result()
                fb.result()
            elapsed = time.perf_counter() - t0
            times_concurrent.append(elapsed)
        median = statistics.median(times_concurrent)
        throughput = n / median
        _print_row(
            f"{n:>5} chunks (2x{half})",
            f"{median:>6.2f}s  ({throughput:>6.1f} chunks/s)",
        )

    # ── Summary ───────────────────────────────────────────────────────────
    _print_header("Summary")
    # Use the 512-chunk single-thread result as the canonical number
    canonical = next((r for r in results if r[0] == 512), results[-1])
    _print_row("Canonical throughput (512 chunks)", f"{canonical[2]:.1f} chunks/s")
    _print_row(
        "10K files (~70K chunks) estimate",
        f"{70_000 / canonical[2] / 60:.0f} minutes (single-thread)",
    )
    _print_row("Model load time", f"{model_load:.2f}s")
    _print_row("First-call warmup", f"{warmup_time:.3f}s")


if __name__ == "__main__":
    main()
