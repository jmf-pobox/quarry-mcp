# Advanced Setup

Quarry works with zero configuration out of the box — see the main
[README](README.md) for the standard install and daily usage. This document
covers configuration and deployment beyond the default: environment
variables and running the engine on a remote/GPU host.

## Environment Variables

These customize the local daemon; none are required for a default install.

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
