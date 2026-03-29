# Quarry

Local semantic search for AI agents and humans. Indexes 20+ document formats, embeds with a local ONNX model (snowflake-arctic-embed-m-v1.5, 768-dim), stores vectors in LanceDB, serves via MCP (stdio or WebSocket daemon on port 8420).

## Architecture

- **Embedding**: ONNX Runtime with snowflake-arctic-embed-m-v1.5. int8 on CPU (default), FP16 on CUDA (auto-detected). See DES-004 and DES-016 in DESIGN.md.
- **Storage**: LanceDB (Rust core via PyO3). Single `chunks` table per database with vector, text, and metadata columns.
- **Search**: Hybrid search — vector similarity + BM25 full-text (Tantivy) fused via RRF. Temporal decay for agent-scoped memories. See DES-017 in DESIGN.md.
- **Agent memory**: `agent_handle`, `memory_type`, `summary` columns on all chunks. Identity tagging from ethos config. See DES-018 in DESIGN.md.
- **Surfaces**: CLI (`quarry`), MCP server (stdio + WebSocket), HTTP API, Claude Code plugin with slash commands.
- **User data**: `~/.punt-labs/quarry/` per filesystem standard. Per-repo config at `.punt-labs/quarry/config.md`.

## Project-Specific Conventions

- **Quality gates**: always use `make check` — never ad-hoc individual lint/type/test commands.
- `make check` = `make lint` + `make type` + `make test`
- `make docs` builds all LaTeX documents (prfaq, architecture, Z spec). PDFs are committed.
- **Full test suite** needs `timeout=300000` on the Bash tool (5 minutes). During development, use targeted tests: `uv run pytest tests/test_specific.py -v`.
- **Never retry a command that produces no output.** Diagnose first.

## Key Design Documents

- `DESIGN.md` — ADR log (DES-001 through DES-018)
- `docs/architecture.tex` → `docs/architecture.pdf` — system architecture, module responsibilities, search and retrieval, deployment
- `prfaq.tex` → `prfaq.pdf` — product direction and risk assumptions
- `docs/improving-agent-memory.md` — agent memory design rationale
- `docs/provider-detection-design.md` — ONNX provider auto-detection design
