#!/usr/bin/env bash
# PostToolUse on WebFetch: auto-ingest fetched URLs into web-captures.
# Delegates to the Python handler for dedup and ingestion.
quarry hooks post-web-fetch 2>/dev/null || true
