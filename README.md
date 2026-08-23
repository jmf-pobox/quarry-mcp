# punt-quarry

> Local semantic search for AI agents and humans.

[![License](https://img.shields.io/github/license/punt-labs/quarry)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/punt-labs/quarry/test.yml?label=CI)](https://github.com/punt-labs/quarry/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/punt-quarry)](https://pypi.org/project/punt-quarry/)
[![Python](https://img.shields.io/pypi/pyversions/punt-quarry)](https://pypi.org/project/punt-quarry/)
[![Working Backwards](https://img.shields.io/badge/Working_Backwards-hypothesis-lightgrey)](./prfaq.pdf)

Quarry indexes documents in 20+ formats, embeds them with a local ONNX model (snowflake-arctic-embed-m-v1.5), stores the vectors in LanceDB, and serves semantic search to Claude Code, Claude Desktop, and the command line. Everything runs locally — no API keys, no cloud accounts. One `quarryd` daemon per machine loads the model once; the CLI, the MCP server, and the Claude Code hooks are thin clients over it.

**Platforms:** macOS, Linux

## Quick Start

Install the CLI, the daemon, the MCP server, and the Claude Code plugin:

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/quarry/fd274d3/install.sh | sh
```

Restart Claude Code. Your current project is auto-indexed at session start, so you can search it by meaning right away — see [What It Looks Like](#what-it-looks-like).

<details>
<summary>Manual install (if you already have uv)</summary>

Install the package:

```bash
uv tool install punt-quarry
```

Set up the daemon, TLS certificates, and MCP config:

```bash
quarry install
```

Check health:

```bash
quarry doctor
```

</details>

<details>
<summary>CLI only (skip the Claude Code plugin)</summary>

For non-Claude harnesses (Codex, Cursor, a plain terminal) or Claude Code users whose org policy blocks marketplace/plugin installs, `--no-plugin` installs everything except the marketplace-register and plugin-install steps:

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/quarry/fd274d3/install.sh | sh -s -- --no-plugin
```

Where a flag cannot be passed (CI templating a bare `curl … | sh`), set `QUARRY_NO_PLUGIN=1` — honored only when exactly `1`:

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/quarry/fd274d3/install.sh | QUARRY_NO_PLUGIN=1 sh
```

Everything else runs unchanged. Use the CLI and the stdio `quarry mcp` server directly; both talk to the resident `quarryd`. Re-run the installer without `--no-plugin` to add the plugin later.

</details>

<details>
<summary>Verify before running</summary>

Download the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/quarry/fd274d3/install.sh -o install.sh
```

Check its digest (`shasum -a 256 install.sh` on macOS):

```bash
sha256sum install.sh
```

Read it:

```bash
cat install.sh
```

Run it:

```bash
sh install.sh
```

</details>

## Features

- **20+ formats** — PDFs (with OCR for scanned pages), source code (AST-aware splitting), spreadsheets, presentations, HTML, Markdown, LaTeX, DOCX, images.
- **Semantic search** — retrieval is by meaning, not keyword. A query about "margins" finds passages about profitability even if they never use that word.
- **One daemon, thin clients** — a single `quarryd` process loads the embedding model once and serves the CLI, the MCP server, and the Claude Code hooks over a versioned REST API. Its resource use is bounded so it stays quiet in the background while you work.
- **Passive knowledge capture** — `quarry enable` sets up per-project file sync, web-fetch and session-transcript capture, and per-agent memory. Captures are PII/secret-scrubbed at write time and kept separate from the code index. See [Knowledge Capture](#knowledge-capture).
- **Named databases** — isolated LanceDB directories with independent sync registries; switch with `quarry use` for work/personal separation.
- **Remote server** — run the engine on a GPU host and connect from any Mac or Linux client over TLS. See [Remote Server](#remote-server).

## What It Looks Like

Ingest a document:

```text
> /ingest https://example.com/report

▶ Ingesting https://example.com/report (background)
```

For local files, register their containing directory instead — see
[Commands](#commands).

Search by meaning:

```text
> /find "what were the Q3 revenue figures"

▶ [report.pdf p.12 | text/.pdf] (similarity: 0.4521)
  Third quarter revenue reached $142M, up 18% year-over-year,
  driven primarily by expansion in the enterprise segment.
  Gross margins improved to 71% from 68% in Q2.
```

## Commands

### Slash Commands (Claude Code)

| Command | What it does |
|---------|-------------|
| `/ingest <source>` | Ingest a URL, or register+sync a local file or directory |
| `/remember <name>` | Ingest inline text under a document name |
| `/find <query>` | Semantic search; questions get synthesized answers, keywords get raw results |
| `/explain <topic>` | Search and synthesize an explanation |
| `/source <claim>` | Find which document a claim comes from |
| `/quarry [sub]` | Manage: `status`, `sync`, `collections`, `databases`, `registrations` |

### MCP Tools

| Tool | Purpose |
|------|---------|
| `find` | Semantic search with filters |
| `show` | Document metadata or page text |
| `list` | Documents, collections, databases, registrations |
| `status` | Database statistics |
| `ingest` / `remember` | Index a URL, or inline text |
| `register_directory` / `deregister_directory` | Manage a synced directory |
| `sync_all_registrations` | Re-index all registered directories |
| `delete` | Remove a document or collection |
| `use` | Switch the active database |

### CLI

| Command | What it does |
|---------|-------------|
| `quarry find "<query>"` | Hybrid search (vector + full-text) |
| `quarry ingest <url>` | Index a webpage (local files/directories: `quarry register`) |
| `quarry remember --name <name>` | Index inline text from stdin |
| `quarry list documents` | List indexed documents |
| `quarry register <dir>` | Watch a directory for changes |
| `quarry sync` | Re-index registered directories |
| `quarry enable` / `quarry disable` | Set up / tear down project collections + captures |
| `quarry use <name>` | Switch the active database |
| `quarry status` | Database dashboard |
| `quarry doctor` | Health check |
| `quarry install` | Set up the daemon service, TLS certs, and MCP config |
| `quarry uninstall` | Remove the daemon service (its launchd/systemd unit) |
| `quarry login <host> --api-key <token>` | Connect to a remote server (TOFU pinning) |
| `quarry logout` | Disconnect, revert to the local daemon |

Agent-memory tagging is available on `ingest`/`remember`/`find` via `--agent-handle`, `--memory-type`, and `--summary`.

## Setup

Quarry works with zero configuration. These environment variables customize it:

| Variable | Default | Description |
|----------|---------|-------------|
| `QUARRY_PROVIDER` | *(auto)* | ONNX execution provider: `cpu`, `cuda`, or unset (auto-detect) |
| `QUARRY_API_KEY` | *(none)* | Bearer token for `quarryd` (required for a non-loopback bind) |
| `QUARRY_ROOT` | `~/.punt-labs/quarry/data` | Base directory for all databases |
| `CHUNK_MAX_CHARS` | `1800` | Max characters per chunk (~450 tokens) |
| `CHUNK_OVERLAP_CHARS` | `200` | Overlap between consecutive chunks |

The full configuration reference is in [docs/architecture.tex](docs/architecture.tex).

## Remote Server

Run quarry on a GPU host and connect from any Mac or Linux client over TLS. On the server, set an API key and install in network mode (binds `0.0.0.0`, registers a service, prints a CA fingerprint):

```bash
export QUARRY_API_KEY=$(openssl rand -hex 32)
```

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/quarry/fd274d3/install.sh | sh -s -- --network
```

On the client, install normally, then log in — queries redirect to the server over `wss://` with TOFU certificate pinning:

```bash
quarry login <server-hostname> --api-key <token>
```

## Claude Desktop

The `.mcpb` bundle is an on-top way to reach the **same** local index from Claude Desktop. It embeds no engine — it registers the thin `quarry mcp` client, which talks to the same `quarryd` that backs the CLI and Claude Code. It is not a standalone install: quarry must already be installed and running.

`quarry install` configures Claude Desktop automatically. To add it by hand instead, [download `punt-quarry.mcpb`](https://github.com/punt-labs/quarry/releases/latest/download/punt-quarry.mcpb) and double-click it.

Uploaded files in Claude Desktop live in a sandbox quarry cannot read — use `remember` for that content, or give `ingest` a local path.

## Knowledge Capture

As a Claude Code plugin, quarry captures knowledge automatically: it auto-indexes your project at session start, ingests URLs you fetch during research, and captures session transcripts before context compaction. All hooks fail open (a failure never blocks Claude Code) and are individually toggleable in `.punt-labs/quarry/config.md`.

Captures are PII/secret-scrubbed at write time (secrets, paths, emails, hostnames) through a single choke point, fail-closed. Deliberate `ingest`/`remember` content is not scrubbed. An opt-in per-project shadow repo (`<repo>` → private `<repo>-quarry`) can push the redacted captures off the public repo. See [DES-036 and DES-039 in DESIGN.md](DESIGN.md) and [AGENTS.md](AGENTS.md).

## Managing the Daemon

`quarry install` registers `quarryd` as a per-user service that starts at login and restarts on crash (launchd on macOS, systemd on Linux). **After upgrading the package, restart the service** so the new engine loads — a running daemon holds the old code in memory.

macOS:

```bash
launchctl kickstart -k gui/$(id -u)/com.punt-labs.quarry
```

Linux:

```bash
systemctl --user restart quarry
```

`quarry doctor` confirms the daemon is running and ready.

## Documentation

[Architecture](docs/architecture.tex) |
[Design (ADR log)](DESIGN.md) |
[Agents](AGENTS.md) |
[Changelog](CHANGELOG.md)

## Development

| Command | Purpose |
|---------|---------|
| `uv sync` | Install dependencies |
| `make check` | All quality gates (lint, type, test, ratchets) |
| `make test` | Test suite only |
| `make format` | Auto-format |
| `make docs` | Build the LaTeX documents |
| `make eval` | Retrieval-quality eval harness (MRR/success@k) |

## License

MIT
