#!/usr/bin/env bash
[[ -f "$HOME/.punt-hooks-kill" ]] && exit 0
# SessionStart: auto-register and sync the current repo with quarry.
# Delegates to the Python handler which returns additionalContext.
quarry-hook session-start 2>/dev/null || true
