#!/usr/bin/env bash
# SessionStart: auto-register and sync the current repo with quarry.
# Delegates to the Python handler which returns additionalContext.
quarry hooks session-start 2>/dev/null || true
