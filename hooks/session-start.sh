#!/usr/bin/env bash
[[ -f "$HOME/.punt-hooks-kill" ]] && exit 0
quarry-hook session-setup 2>/dev/null || true
