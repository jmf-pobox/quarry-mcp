#!/usr/bin/env bash
[[ -f "$HOME/.punt-hooks-kill" ]] && exit 0
# PreToolUse on Bash: emit convention hints.
# Delegates to the Python handler which returns additionalContext.
quarry-hook pre-tool-hint 2>/dev/null || true
