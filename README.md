# punt-quarry

[![License](https://img.shields.io/github/license/punt-labs/quarry)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/punt-labs/quarry/test.yml?label=CI)](https://github.com/punt-labs/quarry/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/punt-quarry)](https://pypi.org/project/punt-quarry/)
[![Python](https://img.shields.io/pypi/pyversions/punt-quarry)](https://pypi.org/project/punt-quarry/)
[![Working Backwards](https://img.shields.io/badge/Working_Backwards-hypothesis-lightgrey)](./prfaq.pdf)

Local semantic search for AI agents and humans. Index documents in 20+ formats, search by meaning, recall knowledge across sessions — all local, no API keys.

## Quick Start

### Claude Code

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/quarry/25eaa96/install.sh | sh
```

<details>
<summary>Manual install (if you already have uv)</summary>

```bash
uv tool install punt-quarry
quarry install
quarry doctor
```

</details>

<details>
<summary>Verify before running</summary>

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/quarry/25eaa96/install.sh -o install.sh
shasum -a 256 install.sh
cat install.sh
sh install.sh
```

</details>

Once installed, quarry is available as both an MCP server and a Claude Code plugin. The plugin adds slash commands (`/find`, `/ingest`, `/quarry`) and hooks that passively capture knowledge from your sessions. See [AGENTS.md](AGENTS.md) for the full integration model.

### Claude Desktop

[**Download punt-quarry.mcpb**](https://github.com/punt-labs/quarry/releases/latest/download/punt-quarry.mcpb) and double-click to install. Claude Desktop will prompt you for a data directory.

Alternatively, `quarry install` (from the CLI) configures Claude Desktop automatically.

**Note:** Uploaded files in Claude Desktop live in a sandbox that quarry cannot access. Use `remember` for uploaded content, or provide local file paths to `ingest`.

## How It Works

Quarry runs as a **daemon** — a single background process that loads the embedding model once and serves all sessions. Claude Code and Desktop connect through a lightweight [**mcp-proxy**](https://github.com/punt-labs/mcp-proxy) binary (~5 MB, <10 ms startup) that bridges MCP stdio to the daemon over WebSocket:

```text
                    stdio                      WebSocket
Claude Code <-----------------> mcp-proxy <---------------------> quarry serve
             MCP JSON-RPC                                         (one process)
```

Without the proxy, every session spawns a separate Python process, each loading the embedding model into ~200 MB of RAM. With it, you get instant startup and shared state across all sessions.

`quarry install` downloads mcp-proxy automatically (SHA256-verified, correct platform) and configures MCP clients.

## Supported Formats

| Source | What happens |
|--------|-------------|
| PDF (text pages) | Text extraction via PyMuPDF |
| PDF (image pages) | Local OCR (RapidOCR) |
| Images (PNG, JPG, TIFF, BMP, WebP) | Local OCR (RapidOCR) |
| Spreadsheets (XLSX, CSV) | Tabular serialization preserving structure |
| Presentations (PPTX) | Slide-per-chunk with tables and speaker notes |
| HTML / webpages | Boilerplate stripping, converted to Markdown |
| Text files (TXT, MD, LaTeX, DOCX) | Split by headings, sections, or paragraphs |
| Source code (30+ languages) | AST parsing into functions and classes |

## MCP Tools

| Tool | Purpose |
|------|---------|
| `find` | Semantic search with optional filters |
| `ingest` | Index a file or URL (background) |
| `remember` | Index inline text (background) |
| `show` | Document metadata or page text |
| `list` | Documents, collections, databases, or registrations |
| `delete` | Remove a document or collection (background) |
| `register_directory` | Register a directory for sync (background) |
| `deregister_directory` | Remove a directory registration (background) |
| `sync_all_registrations` | Re-index all registered directories (background) |
| `use` | Switch to a different database |
| `status` | Database stats |

Background tools return immediately and process asynchronously. Detailed parameter docs are in each tool's description.

## CLI

```bash
# Ingest
quarry ingest report.pdf                       # index a file
quarry ingest https://example.com/page         # index a webpage
echo "meeting notes" | quarry remember --name notes.md  # index inline text

# Search
quarry find "revenue trends"                   # semantic search
quarry find "tests" --page-type code           # filter by type

# Manage
quarry list documents                          # list indexed documents
quarry show report.pdf                         # document metadata
quarry delete report.pdf                       # remove a document

# Directory sync
quarry register ~/Documents/notes              # watch a directory
quarry sync                                    # re-index registered directories

# Named databases
quarry use work                                # set persistent default
quarry list databases                          # list all databases

# System
quarry status                                  # database dashboard
quarry doctor                                  # health check
quarry install                                 # data dir + model + MCP clients + daemon
quarry serve                                   # start HTTP API server on :8420
```

## Configuration

Quarry works with zero configuration. These environment variables are available for customization:

| Variable | Default | Description |
|----------|---------|-------------|
| `QUARRY_API_KEY` | *(none)* | Bearer token for `quarry serve` |
| `QUARRY_ROOT` | `~/.quarry/data` | Base directory for all databases |
| `CHUNK_MAX_CHARS` | `1800` | Max characters per chunk (~450 tokens) |
| `CHUNK_OVERLAP_CHARS` | `200` | Overlap between consecutive chunks |

For the full configuration reference (embedding model, paths, logging), see [Architecture](docs/architecture.tex) section 7.

## Roadmap

- **Ambient knowledge** — passive learning and active recall via Claude Code plugin hooks ([vision](research/vision.md))
- `quarry sync --watch` for live filesystem monitoring
- PII detection and redaction
- Google Drive connector

For product vision and positioning, see [PR/FAQ](prfaq.pdf).

## Development

```bash
make check                     # run all quality gates (lint, type, test)
make test                      # run the test suite only
make format                    # auto-format code
```

## Documentation

- [Architecture](docs/architecture.tex) — system architecture, configuration, search tuning, logging standards
- [Z Specification](docs/claude-code-quarry.tex) — formal spec of the plugin state machine
- [Design](DESIGN.md) — architectural decision records
- [Agents](AGENTS.md) — integration model for AI agents (MCP tools, hooks, slash commands)
- [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE)
