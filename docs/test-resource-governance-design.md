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
among several. Nothing anywhere — in this repo or the workspace — limits how
many test suites run at once, and a per-run cap multiplies by N when N runs
overlap.

That observation is why the incident happened; it is not a specification for
quarry. Section 4 takes it up and concludes that bounding N is outside this
suite's remit. The finding recorded here is the environment, not a defect.

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
| Nothing bounds N overlapping suite runs | **True — the incident's multiplier** |

One defect quarry fixes: hermeticity. One latent defect it also fixes: the ONNX
exclusion is an accident of forty ad-hoc patches rather than an enforced
invariant. And one true finding that is *not* quarry's to fix — the unbounded
N — which section 4 explains belongs to whoever runs the machine, not to this
test suite.

## 2. Budget

One suite run must fit inside this envelope, on any machine, without assuming
anything about what else that machine is running.

| Quantity | Per run | Enforcement |
|---|---|---|
| Processes | 1 | No `pytest-xdist` (section 4, ADR) |
| OS threads | ≤ 32 | `ThreadConfig` env pin + session invariant |
| Peak RSS | ≤ 512 MB | Session invariant; ONNX exclusion keeps it at ~180 MB |
| Real ONNX model loads | 0 | Factory-level fake + import guard |
| Writes under the real `~/.punt-labs/quarry/` | 0 | `HOME` redirect + three-file guard |

Every row is a property of one run, enforced from inside that run. There is
deliberately no workspace-wide row: section 4 records why quarry does not
govern how many suites an operator starts. Against 8 cores, one run at this
envelope leaves the daemon (measured at 37 threads) and interactive work the
large majority of the machine; the arithmetic for N of them is in section 7,
as a description of the environment rather than a commitment.

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

### As implemented — the choke point is one level lower than described above

Option B is stated as replacing `get_embedding_backend` and
`new_embedding_backend` in `quarry.ingestion.backends`. That is necessary and it
is not sufficient, for the same reason the forty ad-hoc patches were not.
`quarry.ingestion.streaming` and `quarry.http_resources` each bind their factory
with a module-scope `from quarry.ingestion.backends import ...`, so by the time
a fixture patches the factory module those names are already bound to the real
implementation. Patching only the factory module reproduces the exact
wrong-import-site failure this section exists to close.

The implemented fixture replaces all three of `get_embedding_backend`,
`new_embedding_backend`, and `quarry.embeddings.OnnxEmbeddingBackend`. The third
is the one that does the work: `new_embedding_backend` imports it *inside its
body*, so it resolves per call rather than per import, and every route — cached,
fresh, current, or added tomorrow — passes through it. The first two are kept
because they are the named factory contract and a future caller may reach them
by module attribute rather than by from-import.

The marker also split in two, because one marker conflated two concerns.
`@pytest.mark.embedding` means "may load the real 410 MB model" and is
deselected by default alongside `slow`, as recommended above. But
`test_backends`, `test_embeddings`, and doctor's install path assert on what the
factory *builds* while supplying their own ONNX-session mocks: they need the
real factory and must stay in the default CI run. Those use a separate
`real_embedding_factory` fixture, which opts out of the fake only — the
`InferenceSession` guard from option D stays armed, so they still cannot load a
real model.

Two environmental couplings surfaced during implementation that this document
did not predict, both fixed in `tests/hermetic_env.py`. Redirecting `HOME` moves
`GNUPGHOME`, and the workspace exports `commit.gpgsign=true` through
`GIT_CONFIG_*`, so every throwaway git repository a test builds failed to
commit; the ambient injection is dropped for the session, which those tests
needed regardless — they had been silently depending on the operator's unlocked
gpg agent. And the session home cannot live under the repository:
`ScratchGuard` refuses a repo's `.tmp` and any worktree checked out below one
(section 5.2's neighbour, DES-045), which would leave `_pytest_tmp_base` with no
guard-permitted fallback and the suite with nowhere indexable to build project
roots. It lives under the real `~/.cache`, outside the three watched files.

## 4. Question 2 — the concurrency budget and its enforcement

### Where quarry's obligation ends

The contract asked for a budget that holds when N suite runs overlap. It does
not hold, and quarry should not try to make it hold. The reason is a product
question rather than a technical one.

Quarry is a shipped product. We are its authors, not its only users. Any
mechanism that bounds concurrency across the punt-labs workspace — a lock file
under `~/.punt-labs/`, coordinated `make test` targets in sibling repositories —
encodes this development environment into the product's test suite. For every
other contributor, and for every CI environment, that machinery is meaningless
at best and an obstacle at worst. A contributor who clones quarry and runs
`make test` should not inherit assumptions about a workspace layout they do not
have.

So the suite's obligation is stated in terms of itself, not its neighbours:

> One quarry suite run is bounded and hermetic on any machine, and assumes
> nothing about what else that machine is running.

The N-overlap analysis stays in this document as measured fact, because it is
what explains the incident, but it resolves to an operations concern outside
any repository's test suite. The measurement that settles it: one full suite
consumes **0.69 average cores** over 446.7 s. A suite that bounded is not
capable of the observed failure by itself, and a suite cannot be made
responsible for how many copies of itself an operator chooses to start. Bounding
that is a scheduling decision belonging to whoever runs the machine.

What follows is therefore per-run enforcement only. It is sufficient for the
obligation above, and it is all quarry ships.

### Per-run enforcement

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

### Why there is no cross-run mechanism

Per-run caps multiply by N, and the incident was caused by N. An earlier draft
of this document therefore proposed a workspace-level advisory slot lock — a
PID-aware lock file at `~/.punt-labs/test-concurrency.lock` with capacity
`max(1, ncpu // 4)`, acquired by `make test`, adopted by sibling repositories so
they contended on one object.

That is rejected, on the reasoning in the preceding subsection. It is worth
being precise about why, because the mechanism would have worked on this
machine and the temptation to reinstate it will recur:

- **It bakes the workspace into the product.** The lock path, and the premise
  that sibling repositories cooperate, are facts about how punt-labs is checked
  out. They are not facts about quarry. Shipping them means shipping our desk.
- **It only functions if biff and vox adopt it.** A mechanism whose correctness
  depends on changes in two other repositories is not a property of quarry's
  test suite; it is a workspace protocol wearing a Makefile target.
- **It would be dead weight everywhere else.** An outside contributor, or a
  GitHub runner executing exactly one suite on a dedicated box, pays startup
  cost and a new failure mode for a contention that does not exist for them.
- **It treats a scheduling decision as a test-suite concern.** How many suites
  run at once is chosen by whoever runs the machine, and belongs with them.

The measured facts that motivated the lock stay on the record — per-run caps do
multiply by N, and biff and vox were observed running their own suites during
the incident — but they describe the operating environment, not a defect in this
suite. The correct response to N overlapping suites is to start fewer of them.

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

**`nice` the test process.** Rejected. It improves interactive responsiveness
under contention but does nothing about memory pressure or total thread count,
and it makes an overload less visible rather than less real. It is also the
wrong layer: how a run is prioritised against everything else on the machine is
the operator's call, and `nice make test` is available to them without quarry
deciding it for every user.

## 5. Question 3 — hermeticity

Both mechanisms, because they answer different questions. Redirection stops the
writes; the guard proves the redirection is in force.

The redirection has two layers: the explicit `QUARRY_ROOT` / `QUARRY_LOG_DIR`
variables (5.1), which need a source change, and a `HOME` redirect (5.2) that
covers every path the explicit variables do not. The guard (5.3) is a
three-file smoke check, not a tree fingerprint — 5.2 records why the tree
fingerprint an earlier draft proposed does not work and cannot be repaired.

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

### 5.2 Redirect `HOME` itself — the prevention that covers every path

An earlier draft of this section proposed detecting escapes by fingerprinting
`~/.punt-labs/quarry/` before and after each test with two `stat` calls, one on
the log file and one on the data directory. That design was wrong, and the way
it was wrong is worth recording so it is not reinvented.

A directory's `mtime` changes only when an entry is added to or removed from
*that* directory. It does not change when a file's contents change, and it does
not change when a file is created several levels below. Measured:

| Operation under `data/` | Root `mtime` changed? |
|---|---|
| Modify contents of an existing deep file | No |
| Add a new file three levels down | No |

So the `stat` on the data directory would have detected essentially nothing. The
`stat` on the log file was sound — that is a file, and both size and mtime move
when it is appended to — but it covered only the one breach already known.

The obvious repair, a recursive walk, is not available. The operator's real tree
is **15 GB across 1,586 files**, and `os.walk` with a `stat` per file did not
complete within a two-minute timeout. That rules the walk out at *any* scope,
per-test or once per session — it is not a matter of tuning the frequency.

The correct mechanism is to stop watching the filesystem and remove the ability
to name the path at all. `pytest_configure` sets `HOME` to a session-scoped
temporary directory before any quarry import. Every route to the real tree runs
through it:

| Expression | With `HOME` redirected |
|---|---|
| `Path.home()` | redirected |
| `os.path.expanduser("~")` | redirected |
| `Path("~").expanduser()` | redirected |

Verified: patching `Path.home` alone is *not* sufficient — `expanduser` reads
`$HOME` from the environment and ignores the patched classmethod, so a
`Path.home`-only patch leaves two of the three routes pointing at production.
Setting the environment variable covers all three, which is why it is the
environment variable and not the method that gets redirected.

This subsumes the `QUARRY_ROOT` and `QUARRY_LOG_DIR` redirection of section 5.1
rather than replacing it. The explicit variables remain the supported way to
point a real deployment elsewhere; the `HOME` redirect is the test-side
backstop that catches any path this design has not enumerated. The source change
in 5.1 is still required regardless, because `LoggingConfig._LOG_DIR` is bound
at import time — `HOME` must be set before that import, not after.

### 5.3 The residual guard

With `HOME` redirected, a write to the real tree requires an absolute path
hardcoded in source. Three files are the plausible targets and all three are
*files*, where `stat` is exact: the log file, `config.toml`, and the default
`registry.db`. An autouse fixture stats those three before and after each test
and fails on any change, naming the test and the path.

Measured cost: **25.9 ms** for three stats across 1,200 tests — 0.006% of the
446.7 s baseline.

This is a smoke check, and deliberately so. Prevention is now the `HOME`
redirect, which is total; the guard exists to prove the redirect is in force and
to catch a hardcoded absolute path, not to enumerate the tree. Section 7's
wall-clock accounting uses this figure.

The guard runs unconditionally, including in CI, where `HOME` differs but the
same three paths must remain untouched.

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

| Quantity | Before (measured) | After |
|---|---|---|
| Processes | 1 | 1 |
| OS threads | 25 peak | ≤ 32, asserted |
| Peak RSS | 175 MB | ≤ 512 MB, asserted |
| Model loads | 0, by accident | 0, enforced |
| Prod-log lines written | **7,034 per run** | 0, guarded |
| Avg cores consumed | 0.69 | 0.69 |

Because every quantity above is per-run and unconditional, N overlapping runs
cost N times each row and nothing worse — there is no shared resource for them
to contend on beyond the machine itself. At N = 3 that is 75 threads, ~525 MB,
2.1 cores, and — the row that matters — **zero** production-log lines and zero
model loads, against ~21,000 log lines and a possible 1.2 GB of models today.

That N = 3 column is a description of the environment, not a commitment this
suite enforces: per section 4, quarry does not govern how many copies of itself
an operator starts. What this design does guarantee is that each copy is small,
silent, and hermetic, so N of them degrade the machine linearly and gracefully
rather than destroying the operator's logs N times over.

The "before" model-load row is the latent risk rather than an observed cost: the
suite currently loads nothing, but one new test reaching an unpatched import
site adds 410 MB per run, and three overlapping runs make that 1.2 GB.

### Expected wall-clock impact

- **Fake-at-the-factory (option B):** no change. The suite already substitutes
  fakes on every path it exercises; this moves where the substitution is
  installed, not whether it happens.
- **ONNX import guard (option D):** no change. One `isinstance` check per
  session on a patched symbol.
- **`HOME` redirect (5.2):** one environment assignment at session start. Zero.
- **Filesystem guard (5.3):** three `stat` calls per test, measured at 25.9 ms
  across 1,200 tests — 0.006% of the baseline.
- **Thread-count invariant (6):** one `threading.enumerate()` at session start
  and end. Microseconds.
- **Thread env pin (4):** no change to wall clock; it constrains pool sizes that
  are already capped in practice.

Every item is either zero or measured in milliseconds, and nothing in this
design queues, blocks, or waits on another process. The additions total well
under a second against a 446.7 s baseline — **under 0.2%**, and the same figure
whether the suite runs alone or alongside others. The baseline is in section 9.

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

- `tests/conftest.py` — `pytest_configure` sets `HOME`, `QUARRY_ROOT`,
  `QUARRY_LOG_DIR`, `OMP_NUM_THREADS`, `LANCE_CPU_THREADS`, `LANCE_IO_THREADS`
  before any quarry or lancedb import; stop stripping `QUARRY_ROOT` in
  `_isolate_from_env`; autouse fixtures for the fake embedding factory, the ONNX
  import guard, and the three-file guard. Note that redirecting `HOME` moves
  `_pytest_tmp_base`'s home-cache fallback too, which is correct but must be
  checked against `ScratchGuard.refuses_root`.
- `tests/fakes.py` (new) — the shared `FakeEmbeddingBackend`, absorbing
  `_FakeEmbedder`, `_ConstantEmbedder`, and the embedder half of
  `_FdSamplingEmbedder`.
- `tests/test_resource_invariants.py` — session-scoped thread-name invariant;
  adopt the shared fake.
- Every test file currently patching `get_embedding_backend` purely to dodge a
  model load — delete the patch. Files that assert on specific vectors keep a
  local override.
- `tests/test_hermeticity.py` (new) — asserts the guard fires on a deliberate
  write to each of the three watched files; asserts `Path.home()`,
  `os.path.expanduser("~")`, and `Path("~").expanduser()` all resolve inside the
  session temp root; asserts `LoggingConfig.configure` honours `QUARRY_LOG_DIR`.
- `tests/test_logging_config.py` — cover the new resolution, including the
  fallback when the variable is absent.

Build and process:

- `pyproject.toml` — register the `embedding` marker; add it to the default
  deselection alongside `slow`.
- `DESIGN.md` — an ADR recording three standing decisions: no `pytest-xdist`,
  the hermeticity contract, and no workspace-level test-concurrency mechanism
  (section 4's reasoning, so the lock is not reinvented).
- `CHANGELOG.md`, and the Testing section of `CLAUDE.md`.

There is **no** `Makefile` change and no `tools/test_lock.py`. An earlier draft
had `make test` acquire a workspace concurrency slot; that is rejected in
section 4 and must not reappear.

Explicitly **not** in the write-set: any change to `thread_config.py`. Its caps
are correct; the defect was that tests bypassed them, which the conftest pin
fixes.

Out of scope: bead quarry-lnog, the stuck `ingest-background` hook processes.
Same shape as the incident — unbounded concurrency of a bounded unit — but a
daemon-side defect, not a test-suite one. Nothing else is deferred; in
particular there is no follow-on for cross-repo coordination, because section 4
rejects that work rather than postponing it.

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
and the one that establishes the incident's multiplier as environmental rather
than a defect in this suite.

## 10. Ruling on scope

The mission contract's stated root cause does not survive measurement, and two
of its four questions therefore have much smaller answers than anticipated:
there is no engine multiplication to fix, and the per-run budget is already met.
The finding that remains is the hermeticity breach — 7,034 log lines per run,
enough to rotate away real daemon history every seven or eight runs. That is
worse than the incident which prompted the mission, and it is the reason this
document still recommends real work.

An earlier draft asked whether to bound concurrent suite runs across sibling
repositories. **The operator ruled against it: quarry does not manage test
concurrency across punt-labs.** The suite must behave reliably regardless of
what other repositories do. No workspace lock file, no biff/vox coordination,
and no follow-on bead — the work is rejected, not deferred.

The reasoning is recorded in section 4 and is a product judgement rather than a
technical one. Quarry is shipped; we are its authors, not its only users. A
concurrency mechanism keyed to the punt-labs workspace layout would bake our
development environment into the product's test suite and mean nothing to any
other contributor or CI environment. The suite's obligations are to be bounded
and hermetic on any machine, and to assume nothing about what else that machine
is running. Both are met by per-run enforcement alone.

Two smaller rulings, for the record: the `docs/README.md` index entry that
accompanies this document stays, and the guard correction at `03735e4` — `HOME`
redirection in place of the tree fingerprint — is accepted. Section 5.2 retains
the rejected fingerprint and the measurements that killed it, because "stat the
data directory too" is the natural next suggestion and it does not work.

This design is complete. Implementation goes to a separate agent against the
write-set in section 8.
