#!/usr/bin/env bash
[[ -f "$HOME/.punt-hooks-kill" ]] && exit 0
# PreCompact: capture session transcript before compaction.
# Delegates to the Python handler for transcript extraction and ingestion.
quarry-hook pre-compact 2>/dev/null || true
