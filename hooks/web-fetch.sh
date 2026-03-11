#!/usr/bin/env bash
[[ -f "$HOME/.punt-hooks-kill" ]] && exit 0
# PostToolUse on WebFetch: auto-ingest fetched URLs into web-captures.
# Delegates to the Python handler for dedup and ingestion.
quarry-hook post-web-fetch 2>/dev/null || true
