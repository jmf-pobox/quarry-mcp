# Quarry Documentation

Index of the `docs/` tree. `DESIGN.md` (repo root) is the ADR source of truth (DES-001+);
this directory holds reference material, active design work, and archived process artifacts.

## Reference (authoritative, kept current)

- **`architecture.tex` → `architecture.pdf`** — full system architecture: modules, search and
  retrieval, embedding/provider, deployment. The consolidation target every archived design
  points to (DES-012).
- **`claude-code-quarry.tex` → `.pdf`** — standalone whitepaper on the Claude Code integration.
- **`improving-agent-memory.md`** — design rationale for the agent-memory layer (identity
  tagging, summaries, temporal decay). Historical (implemented 2026-03); kept for the "why".
- **`tex/`** — LaTeX build support (`fuzz.sty`, MetaFont) for `make docs`.

## Active work

- **`eval-harness-design.md`** — ratified design for the retrieval-quality eval harness.
  **Phase 0 (retrieval seam, #343) and Phase 1 (`make eval`, ranx MRR/success@k, #344) are
  merged** (see DES-037); next is full-fixture curation, then Phase 2/3 lever bake-offs.
- **`retrieval-quality-improvements.md`** — 2026-07 research synthesis (turbopuffer / reranker /
  late-chunking) and the case for eval-first. The eval harness it calls a prerequisite has
  shipped (Phase 0–1, above); the **embedding levers themselves are not yet implemented** —
  they are measured against `make eval` before adoption.
- **`test-resource-governance-design.md`** — test-suite resource governance and hermeticity
  (quarry-21xv). Measurement corrects the load-200 post-mortem: the suite is single-process,
  I/O-bound (0.69 cores), and loads no ONNX models. The real defects are that one run writes
  7,034 lines into the operator's production log, and that nothing bounds concurrent suite
  runs across sibling repos. Awaiting a leader ruling on the cross-repo scope.

## Operations

- **`smoke-test.md`** — post-release manual smoke test: 14 MCP + 18 CLI + 7 enable/disable
  checks (incl. a capture PII-redaction check), plus install verification. Run after every release.

## Archive (`archive/`)

Completed build-plans, design reviews, and superseded designs — preserved for history, not
maintained. Each maps to a settled ADR in `DESIGN.md`. Do not treat as current.

| Archived doc | Feature | ADR |
|---|---|---|
| `async-ops.md` | HTTP async task model | DES-001 |
| `provider-detection-design.md`, `provider-detection-review.md`, `build-plan-provider-detection.md` | ONNX provider auto-detection | DES-016 |
| `build-plan-remote-cli-parity.md` | Remote CLI routing | DES-021 |
| `cli-logging-ux.md`, `cli-logging-impl.md` | CLI logging / verbosity | DES-028 |
| `prfaq-quarry-enable.md`, `quarry-enable-impl.md` | `quarry enable` / `disable` | DES-029 |
| `sync-concurrency-fix.md` | Concurrent-sync guard (batch-write portion superseded by DES-034) | DES-026 |
| `testing-legacy.md` | Older testing strategy (now in CLAUDE.md) | — |
| `oo-refactoring/` | Completed OO-refactoring initiative | — |
