#!/usr/bin/env bash
# PreCompact: capture session transcript before compaction.
# Delegates to the Python handler for transcript extraction and ingestion.
quarry hooks pre-compact 2>/dev/null || true
