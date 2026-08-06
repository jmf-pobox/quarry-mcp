# Test-Suite Resource Governance

Design for bounding the resource footprint of quarry's test suite, and for
making tests hermetic with respect to the operator's real `~/.punt-labs/quarry/`
tree. Written after the 2026-08-05 incident in which an 8-core machine whose
normal load average is under 5 reached roughly 200.

The mission that commissioned this document stated a root cause. Measurement
contradicts most of it. Section 1 records what was measured, because the
mechanism determines the fix and the originally-proposed fix would have
addressed a problem that does not exist.

## 1. What was actually measured

All figures below come from this machine (8 cores, macOS, Python 3.13) on
2026-08-05. Thread counts are OS threads via `ps -M`, not
`threading.active_count()`, which sees only Python-level threads and reports 2
for a process holding 13.

### 1.1 The suite does not load ONNX models

The premise under investigation was "parallel pytest workers each load a full
ONNX engine stack; 12 model loads in the same second, 114 in one log file."

The log lines counted as model loads are not model loads. They are
`quarry.thread_config` INFO records, emitted by `ThreadConfig.apply_env_limits`.
That method is called on every `ThreadConfig` construction, and
`tests/test_thread_config.py` constructs 29 of them in a single process. The
recurring 18-to-19-per-second bursts in the log are that one unit test file, not
an engine stack. Of 240 such lines in the current log, 36 carry `ncpu=1`,
`ncpu=4`, or `ncpu=2` — core counts this machine does not have — which is the
signature of a test patching `os.cpu_count`.

Direct measurement: running the six heaviest ingest, HTTP, and doctor test files
(`test_pipeline`, `test_index_jobs`, `test_url_ingestion`,
`test_watch_reconcile`, `test_http_resources`, `test_doctor`) added **zero**
lines to the production log and performed **zero** model loads.

The reason is that the fast suite already substitutes a fake embedder
everywhere it matters. There are roughly forty separate
`patch("quarry.ingestion.streaming.get_embedding_backend", ...)` call sites
across the test files. That is the real finding, and it is a latent problem
rather than the observed one — see section 3.

### 1.2 The suite is single-process

`pytest-xdist` is not a dependency, and `addopts` is
`-ra -q -m 'not slow'` with no `-n`. There are no parallel pytest workers in
this repository. Nothing in the suite forks a second engine stack.

### 1.3 LanceDB threads are process-global, not per-connection

Each `Database.connect` was assumed to cost its own tokio runtime. It does not.
Measured, in one process:

| Stage | OS threads | Peak RSS |
|---|---|---|
| Interpreter baseline | 1 | 16 MB |
| After first `lancedb.connect` | 13 | ~30 MB |
| After 8 `Database.connect` + inserts | 20 | 171 MB |
| After 16 forced `optimize` cycles | 25 | 175 MB |
| ONNX session loaded (if it happens) | +4 | +410 MB |

Eight LanceDB connections cost 20 threads, not eight times nine. The
`test_resource_invariants.py` tier — the heaviest thing in the suite, building
eight persistent connections and rebuilding FTS indexes in a loop — completes 16
optimize cycles in 2.3 seconds and stays at 25 threads and 175 MB. It is not a
CPU storm.

### 1.4 The hermeticity breach is real, and it is the only confirmed defect

Reproduced deliberately, twice. Running the five test files that drive
`CliRunner` (`test_cli`, `test_enable_cli`, `test_cli_captures`, `test_hooks`,
`test_backfill`) plus `test_thread_config` wrote **170 lines into
`~/.punt-labs/quarry/logs/quarry.log`**, including `[ERROR]` records from
deliberately-failing CLI cases and `quarry.enable` records describing edits to
fixture `CLAUDE.md` files. A full suite run writes **7,034 lines, roughly
639 KB** — see section 9, which is where this stops being cosmetic.

The mechanism is precise. The Typer root callback in `__main__.py` calls
`LoggingConfig.configure()`, and `LoggingConfig` pins its destination in a
class-level constant evaluated at import time:

```python
_LOG_DIR: Path = Path.home() / ".punt-labs" / "quarry" / "logs"
_LOG_FILE: Path = _LOG_DIR / "quarry.log"
```

No fixture can redirect that. `monkeypatch.setenv("HOME", ...)` is too late —
the constant is already bound — and there is no environment variable consulted
at `configure()` time. Every `CliRunner.invoke` in the suite therefore appends
to the operator's real log, and `configure()` also calls
`mkdir(parents=True, mode=0o700)` on the real directory.

A second, quieter breach sits in `Settings`. `quarry_root` defaults to
`Path.home() / ".punt-labs" / "quarry" / "data"`, and `Settings.load()` reads
`~/.punt-labs/quarry/config.toml`. The autouse `_isolate_from_env` fixture
deletes `QUARRY_ROOT` from the environment, which makes tests fall back to the
real home path rather than away from it. Tests such as
`test_resource_invariants._fabricate_backfill_corpus` call
`Settings.load().resolve_db_paths(None)` and then override only `lancedb_path`
and `registry_path`; `quarry_root` stays pointed at the operator's data
directory, so any code reading it during those tests reads production.

### 1.5 The multiplier is cross-repo, not intra-suite

While this document was being written, with no quarry test running, the machine
reported a load average of 20. `ps` showed `uv run pytest` executing in two
sibling repositories — biff and vox — at 23.5% and 9.5% CPU. Multiple agent
sessions across sibling repositories, each running its own full suite, is the
normal operating mode of this workspace.

This is where load 200 comes from. Quarry's suite is one bounded contributor
among several unbounded ones. Nothing anywhere — in this repo or the workspace —
limits how many test suites run at once. Every per-run cap this document could
propose would be defeated by that, because a per-run cap multiplies by N when N
runs overlap.

There is also a known, separately-tracked contributor: stuck PreCompact
`ingest-background` hook processes accumulating against the captures database.
That is bead quarry-lnog and is out of scope here, but it shares the same
shape — unbounded concurrency of a bounded unit.

### 1.6 Summary of the correction

| Claim under investigation | Verdict |
|---|---|
| Parallel pytest workers each load an engine stack | False — no xdist, single process |
| 12 model loads per second, 114 per log file | False — `ThreadConfig` INFO lines from one unit test |
| Each worker's LanceDB gets 8 tokio threads | False — process-global runtime, 13 threads once |
| The daemon is correctly bounded, tests are not | True, but tests are also bounded per-run |
| Tests write to the production log | **True — 7,034 lines per full run** |
| Tests read the production `quarry_root` / `config.toml` | **True** |
| Nothing bounds N overlapping suite runs | **True — the actual cause** |

Two real defects, then: hermeticity, and the absence of any cross-run
concurrency bound. Plus one latent defect — the ONNX exclusion is an accident of
forty ad-hoc patches, not an enforced invariant.

## 2. Budget

One suite run must fit inside this envelope, and the envelope must hold when N
runs overlap.

| Quantity | Per run | Enforcement |
|---|---|---|
| Processes | 1 | No `pytest-xdist` (section 5, ADR) |
| OS threads | ≤ 32 | `ThreadConfig` env pin + session invariant |
| Peak RSS | ≤ 512 MB | Session invariant; ONNX exclusion keeps it at ~180 MB |
| Real ONNX model loads | 0 | Factory-level fake + import guard |
| Writes under `~/.punt-labs/quarry/` | 0 | Redirection + filesystem guard |
| Concurrent runs, workspace-wide | ≤ `max(1, ncpu // 4)` | Cross-repo advisory lock |

On this machine that is 2 concurrent runs, so the workspace-wide ceiling is
2 × 32 = 64 threads and ~1 GB of test load, against 8 cores. That leaves the
daemon (measured at 37 threads) and the operator's interactive work with the
majority of the machine.

## 3. Question 1 — model and engine sharing

### The problem is enforcement, not sharing

Since the suite is single-process and already avoids real models, there is no
sharing problem to solve. `get_embedding_backend` caches per process, so even a
test that did load a model would load it once. The problem is that the avoidance
is unenforced: roughly forty independent `patch(...)` context managers, each
naming one import site, `quarry.ingestion.streaming.get_embedding_backend`.

A test that reaches the model through any other door escapes every one of them:

- `quarry.http_resources.new_embedding_backend` — the per-query session DES-032
  mandates. `test_http_resources` patches this one by hand; nothing makes the
  next test do so.
- `quarry.ingestion.backends.get_embedding_backend` imported directly by a new
  module.
- The daemon's index worker, reached through the in-process ASGI daemon fixture.

The cost of one escape is 410 MB and a model-load stall in a suite whose entire
current footprint is 180 MB. The cost is paid silently — the test still passes.

### Options

**Option A — share one ONNX session across workers.** Rejected. There are no
workers. Cross-process session sharing requires a resident server, which is
precisely the daemon, and DES-032 deliberately gives each query path its own
session to avoid the arena contention that shared sessions caused. Re-sharing
inside tests would test a topology production does not use. Budget: not
applicable.

**Option B — enforce the fake at the factory choke point, with an opt-in real
partition.** Recommended.

`quarry.ingestion.backends` is the single factory for both the cached
(`get_embedding_backend`) and the fresh (`new_embedding_backend`) paths. A
session-scoped autouse fixture in the root `conftest.py` replaces both with a
deterministic `FakeEmbeddingBackend` returning seeded 768-wide vectors. Tests
that assert on real vector semantics opt back in with a new `embedding` marker,
which the fixture honours by leaving the real factory in place.

Because the choke point is the factory rather than any import site, a new test
reaching the model through a new module is covered without being edited.

The forty ad-hoc `patch(...)` sites then become redundant. Tests that need
specific vectors keep a local patch (they are asserting on values, not avoiding
a load); tests that patch only to dodge the model delete the patch. That
deletion is the OO paydown this design funds — see section 7.

Budget per run: 0 model loads, 0 extra threads, 0 extra MB. Unchanged from today
in the common case; the difference is that it is now guaranteed.

**Option C — process-level or on-disk model cache.** Rejected. It already
exists (`_embedding_cache` in `backends.py`), it is per-process, and making it
cross-process means shared memory or a server. Same objection as A, with more
machinery. Budget: 410 MB once instead of 410 MB per process — a saving only in
a multi-process world that does not exist here.

**Option D — a guard that fails the test instead of faking it.** Complementary,
not alternative, and recommended alongside B. A fixture patches
`onnxruntime.InferenceSession` with a callable that raises unless the running
test carries the `embedding` marker. This turns "a test silently loaded 410 MB"
into a named failure at the moment of the load. Option B prevents; option D
proves the prevention holds, and catches a future refactor that moves the
factory.

### Recommendation

Options B and D together. Real-model tests carry `@pytest.mark.embedding`, are
excluded from the default run alongside `slow`, and run serially in the
integration tier that already needs the model.

## 4. Question 2 — the concurrency budget and its enforcement

### Per-run enforcement (necessary, not sufficient)

The per-run knobs are already correct in production code and merely need to be
pinned for tests. `ThreadConfig._cap_env` clamps `OMP_NUM_THREADS`,
`LANCE_CPU_THREADS`, and `LANCE_IO_THREADS` into `[floor, cap]` fail-closed, but
it only runs when something constructs a `ThreadConfig` — which, per section
1.1, the fast suite mostly does not. A LanceDB connection made before any
`ThreadConfig` exists inherits whatever the shell exported. The root
`conftest.py` sets the three variables in `pytest_configure`, before any test
imports lancedb, so the cap applies unconditionally. This must be
`pytest_configure` and not a fixture: lance reads `LANCE_CPU_THREADS` once, when
it builds its compute runtime, and ignores every later assignment.

A session-scoped invariant then asserts the envelope held: peak OS thread count
≤ 32 and peak RSS ≤ 512 MB at session end. This belongs with the existing
resource-invariant tier, which already establishes the precedent of testing
process-level properties rather than function outputs.

### Cross-run enforcement (the part that actually matters)

Per-run caps multiply by N. Since N is unbounded and the observed incident was
caused by N, the budget can only hold if N is bounded.

The mechanism is an advisory lock at a workspace-level path, taken by `make
test` for the duration of the run:

- Lock file at `~/.punt-labs/test-concurrency.lock`, outside any repo, so
  sibling repositories contend on the same object.
- Capacity `K = max(1, os.cpu_count() // 4)` — 2 on this machine.
- A run that cannot acquire a slot waits rather than failing. Waiting is
  correct: the run is not wrong, it is early.
- A held slot carries the holder's PID; a slot whose PID is gone is reclaimed,
  so a killed agent session does not wedge the workspace.
- CI sets an environment variable that disables the lock entirely. A GitHub
  runner is a dedicated 2-core box running exactly one suite; the lock would
  only add startup cost.

This is the one mechanism in this document that holds under overlap, and it is
the only one that would have prevented the incident. It is deliberately a small,
boring file lock rather than a daemon: the failure mode of a lock daemon is
worse than the problem.

Scope note: the lock is quarry-side in this design, so it bounds quarry against
itself. Bounding quarry against biff and vox requires the same target in those
repositories' Makefiles. That is a workspace-level change and is called out as a
follow-on in section 8 rather than being smuggled into a quarry PR.

### Rejected alternatives

**Add `pytest-xdist` and cap the worker count.** Rejected, and worth recording
as a standing decision. The suite is dominated by filesystem and LanceDB I/O,
not CPU; xdist would multiply the 180 MB base footprint and the LanceDB tokio
runtime by the worker count for a modest wall-clock gain, and it would create
exactly the per-worker engine multiplication the mission believed was already
happening. The correct response to a slow suite here is to fix the slow tests.

**Cap CPU with `taskset` / `cpulimit`.** Rejected. Not portable to macOS in the
form needed, and it caps utilisation rather than concurrency — N runs each
capped at 25% still thrash the scheduler and the page cache.

**`nice` the test process.** Rejected as a primary mechanism. It improves
interactive responsiveness under contention but does nothing about memory
pressure or total thread count, and it makes the overload less visible rather
than less real. Reasonable as a supplement once the lock exists.

## 5. Question 3 — hermeticity

Both mechanisms, because they answer different questions. Redirection stops the
writes; the guard proves no path was missed.

### 5.1 Redirection requires a source change

This cannot be done from `conftest.py` alone. `LoggingConfig._LOG_DIR` is bound
at import time from `Path.home()`, so by the time any fixture runs, the
destination is already decided.

The source change: `LoggingConfig.configure` resolves its directory at call
time, from a `QUARRY_LOG_DIR` environment variable when set and from
`Path.home() / ".punt-labs" / "quarry" / "logs"` otherwise. This is a
one-variable read in a method that already reads `QUARRY_LOG_LEVEL` from the
environment for exactly this kind of per-invocation control, so it introduces no
new concept.

`Settings.quarry_root` needs the parallel treatment. The root `conftest.py` sets
`QUARRY_ROOT` and `QUARRY_LOG_DIR` to session-scoped temporary directories in
`pytest_configure`, and `_isolate_from_env` stops stripping `QUARRY_ROOT` —
stripping it is what sends tests to the real home. `Settings._CONFIG_PATH` must
likewise derive from `quarry_root` rather than from `Path.home()` directly, or
tests keep reading the operator's `config.toml`.

Note that this is not "migration or fallback code," which the project forbids.
It is the target behaviour: the log destination is configuration, and it was
hardcoded.

### 5.2 The guard

An autouse function-scoped fixture records a fingerprint of
`~/.punt-labs/quarry/` before and after each test and fails the test on any
change. The fingerprint must be cheap, because it runs about 1,200 times:
`os.stat` on the log file and on the data directory, comparing `st_mtime_ns` and
`st_size`. That is two `stat` calls per test, on the order of ten microseconds —
invisible against a suite measured in minutes.

The failure message names the test and the path that changed, so the diagnosis
is immediate rather than archaeological. Deliberately not a recursive tree walk:
that would cost milliseconds per test and, at 1,200 tests, minutes per run — the
guard would become the resource problem.

The guard runs unconditionally, including in CI, where `HOME` differs but the
path still resolves and still must be untouched.

## 6. Question 4 — leak prevention beyond the drain fix

The change on `fix/test-isolation-background-thread-leak` moves teardown from
cancelling background jobs to draining them, and fails closed on drain timeout.
That is correct and necessary. It is not sufficient, for a specific reason: it
proves the drain completed, not that no thread survived it. A background thread
started outside the `TaskRegistry` — a watcher, an httpx pool, a lance
compaction thread — is invisible to it.

Recommended: a session-scoped thread invariant, in the resource tier, following
the shape `FdTrajectory` already established for descriptors. Record the set of
non-daemon thread names at session start; assert at session end that the set has
not grown. Names, not counts, so the failure message identifies the leaker.

Rejected: a per-test thread-count assertion. LanceDB starts its tokio pool
lazily and on demand, so the first test to touch lance legitimately adds
thirteen threads while its neighbours add none. A per-test check would fail on
correct code, and the standing rule here is that the response to a
non-deterministic test is to name the mechanism, not to add slack until it
passes. A session-scoped check has no such ambiguity: by session end every pool
that will start has started.

The threshold is a delta of zero on non-daemon threads, not a slack window.
Daemon threads are excluded because the interpreter reclaims them at exit and
lance's pools are daemonised.

## 7. Before and after

Per run, measured before and projected after:

| Quantity | Before (measured) | After | N = 3 before | N = 3 after |
|---|---|---|---|---|
| Processes | 1 | 1 | 3 | 2 (third waits) |
| OS threads | 25 peak | ≤ 32, asserted | 75 | ≤ 64 |
| Peak RSS | 175 MB | ≤ 512 MB, asserted | 525 MB | ≤ 1 GB |
| Model loads | 0, by accident | 0, enforced | 0 or 1.2 GB if one escapes | 0, enforced |
| Prod-log lines written | **7,034 per run** | 0, guarded | ~21,000 | 0 |
| Avg cores consumed | 0.69 | 0.69 | 2.1 | ≤ 1.4 |
| Concurrent runs | unbounded | ≤ `ncpu // 4` | 3 | 2 |

The "before" model-load row is the latent risk rather than an observed cost: the
suite currently loads nothing, but one new test reaching an unpatched import
site adds 410 MB per run, and three overlapping runs make that 1.2 GB.

### Expected wall-clock impact

- **Fake-at-the-factory (option B):** no change. The suite already substitutes
  fakes on every path it exercises; this moves where the substitution is
  installed, not whether it happens.
- **ONNX import guard (option D):** no change. One `isinstance` check per
  session on a patched symbol.
- **Filesystem guard (5.2):** two `stat` calls per test. At roughly 1,200 tests
  that is under 30 ms across the whole run — below measurement noise.
- **Thread-count invariant (6):** one `threading.enumerate()` at session start
  and end. Microseconds.
- **Thread env pin (4):** no change to wall clock; it constrains pool sizes that
  are already capped in practice.
- **Cross-run lock (4):** no change to a single run. When runs overlap beyond
  capacity, the excess runs queue, so the *last* run's wall clock grows by up to
  the duration of the run ahead of it. This is the intended trade: total
  time-to-all-green improves, because two suites running at full speed finish
  sooner than three thrashing an 8-core machine, and the operator's interactive
  session stops stalling.

Net for the common case — one suite, one machine — the change is within noise:
the measured additions total well under a second against a 446.7 s baseline,
under 0.2%. The baseline itself is recorded in section 9.

### OO paydown

The implementation mission should not stop at adding fixtures. Deleting the
roughly forty redundant `patch("...get_embedding_backend", ...)` context
managers is the real improvement this design funds: it removes a duplicated
four-line block repeated across a dozen files, replaces it with one named
fixture, and eliminates the class of bug where a test patches the wrong import
site and silently loads a model. The fake backend itself is a class with
`dimension`, `model_name`, `embed_texts`, and `embed_query` — the same shape as
the several ad-hoc `_FakeEmbedder` / `_ConstantEmbedder` / `_FdSamplingEmbedder`
classes already scattered through the test tree, which should collapse into one
reusable base.

## 8. Write-set for the implementation mission

Source changes (small, and unavoidable — the hermeticity fix cannot be done from
test code):

- `src/quarry/logging_config.py` — resolve the log directory at `configure()`
  time from `QUARRY_LOG_DIR`, falling back to the home path. Removes the
  import-time `Path.home()` binding.
- `src/quarry/config.py` — derive `_CONFIG_PATH` from `quarry_root` so a
  redirected root also redirects config reads.

Test infrastructure:

- `tests/conftest.py` — `pytest_configure` sets `QUARRY_ROOT`, `QUARRY_LOG_DIR`,
  `OMP_NUM_THREADS`, `LANCE_CPU_THREADS`, `LANCE_IO_THREADS` before any import
  of lancedb; stop stripping `QUARRY_ROOT` in `_isolate_from_env`; autouse
  fixtures for the fake embedding factory, the ONNX import guard, and the
  filesystem guard.
- `tests/fakes.py` (new) — the shared `FakeEmbeddingBackend`, absorbing
  `_FakeEmbedder`, `_ConstantEmbedder`, and the embedder half of
  `_FdSamplingEmbedder`.
- `tests/test_resource_invariants.py` — session-scoped thread-name invariant;
  adopt the shared fake.
- Every test file currently patching `get_embedding_backend` purely to dodge a
  model load — delete the patch. Files that assert on specific vectors keep a
  local override.
- `tests/test_hermeticity.py` (new) — asserts the guard fires: a test that
  deliberately writes under the redirected root is caught, and
  `LoggingConfig.configure` honours `QUARRY_LOG_DIR`.
- `tests/test_logging_config.py` — cover the new resolution, including the
  fallback when the variable is absent.

Build and process:

- `Makefile` — `test` acquires the workspace concurrency slot; a bypass variable
  for CI.
- `tools/test_lock.py` (new) — the PID-aware advisory slot lock.
- `pyproject.toml` — register the `embedding` marker; add it to the default
  deselection alongside `slow`.
- `DESIGN.md` — an ADR recording the standing decision against `pytest-xdist`
  and the hermeticity contract.
- `CHANGELOG.md`, and the Testing section of `CLAUDE.md`.

Explicitly **not** in the write-set: any change to `thread_config.py`. Its caps
are correct; the defect was that tests bypassed them, which the conftest pin
fixes.

Out of scope, for the backlog rather than this mission: applying the same
concurrency slot in the biff and vox Makefiles, which is what actually bounds
the workspace, and bead quarry-lnog for the stuck ingest hooks.

## 9. Baseline measurements

Recorded so the wall-clock claims in section 7 are checkable rather than
asserted.

Full fast suite (`uv run pytest`, the `make test` target), one run, this
machine, with two sibling repositories' suites running concurrently:

| Measurement | Value |
|---|---|
| Wall clock | 446.7 s |
| CPU time | 228.4 s user + 81.3 s sys = 309.7 s |
| Average cores consumed | 0.69 |
| Lines written to the production log | **7,034** |
| Bytes written to the production log | ~639 KB |

Two things follow. First, the hermeticity breach is an order of magnitude larger
than the 170-line sample in section 1.4 suggested: a single suite run appends
seven thousand lines to the operator's log, which is a substantial fraction of
the 5 MB rotation size. Roughly one rotation every seven or eight suite runs,
discarding real daemon history each time. That reframes the breach from an
annoyance into active destruction of production diagnostics — and explains why
the incident log appeared to contain "114 model loads": it was largely test
output in the first place.

Second, 0.69 cores averaged over the run is the decisive number for section 4.
The suite is I/O-bound, not CPU-bound. One quarry suite cannot drive an 8-core
machine to load 200 no matter what it does internally; only N of them, alongside
sibling repositories' suites and the daemon, can. This is the measurement that
rejects `pytest-xdist` — there is no CPU idleness for extra workers to fill —
and the one that makes the cross-run lock the load-bearing part of this design.

## 10. Open question for the leader

The mission contract's stated root cause does not survive measurement, and two
of its four questions therefore have much smaller answers than anticipated:
there is no engine multiplication to fix, and the per-run budget is already met.
The findings that remain are the hermeticity breach — reproduced, 7,034 log
lines per run, enough to rotate away real daemon history every seven or eight
runs — and the absence of any bound on concurrent suite runs across sibling
repositories. The first of those is worse than the incident that prompted the
mission, and it is the reason this document still recommends real work.

The consequence worth a ruling: the cross-run lock only bounds the workspace if
biff and vox adopt it too, and those are separate repositories with their own
agents. This design implements the quarry half and files the rest. Confirm that
split, or direct the cross-repo coordination as part of this work.
