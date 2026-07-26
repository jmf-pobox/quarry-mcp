#!/bin/sh
# Executable clean-machine guide for install.sh (CLI-only, no plugin).
#
# Runs the WORKING-TREE install.sh against a WORKING-TREE wheel
# (QUARRY_LOCAL_WHEEL), never the released curl|sh, so branch changes are what
# get tested. Mirrors ethos's clean-machine guide.sh (../ethos/.tmp/clean-machine).
#
# Proves the CLI-only path across BOTH skip triggers, then exercises the CLI:
#   Scenario A — auto-skip:  claude ABSENT         -> capability auto-skip
#   Scenario B — flag-skip:  claude PRESENT + flag -> operator-driven (--no-plugin)
#   Scenario C — env-skip:   claude PRESENT + env  -> operator-driven (QUARRY_NO_PLUGIN=1)
# plus a real quarryd + remember->find round-trip (the harness plays the init
# manager a bare container lacks).
set -u

# Resolve the working-tree wheel (real PEP 427 name) — exactly one lives here.
WHEEL=""
for _w in "$HOME"/wheel/*.whl; do
  WHEEL="$_w"
  break
done
SHIM_LOG="$HOME/claude-shim.log"
export CLAUDE_SHIM_LOG="$SHIM_LOG"

say() { printf '\n=== %s ===\n' "$1"; }
assert_contains() {
  printf '%s' "$1" | grep -qF -- "$2" ||
    { printf 'ASSERT FAIL: expected to find: %s\n' "$2" >&2; exit 1; }
}
assert_absent() {
  printf '%s' "$1" | grep -qF -- "$2" &&
    { printf 'ASSERT FAIL: unexpectedly found: %s\n' "$2" >&2; exit 1; }
  return 0
}

install_claude_shim() {
  # A fake `claude` recording every call and hard-failing on any plugin /
  # marketplace subcommand. Under a no-plugin skip those steps must never run,
  # so a call here means the operator-driven skip is broken.
  mkdir -p "$HOME/.local/bin"
  cat > "$HOME/.local/bin/claude" <<'SHIM'
#!/bin/sh
echo "claude $*" >> "${CLAUDE_SHIM_LOG:-/dev/null}"
case "${1:-}" in
  plugin|marketplace)
    echo "HARNESS-FAIL: install.sh ran 'claude $*' under a no-plugin skip" >&2
    exit 97 ;;
esac
exit 0
SHIM
  chmod +x "$HOME/.local/bin/claude"
  : > "$SHIM_LOG"
}

assert_cli_only() {
  # Shared CLI-only success contract for every scenario. $1 = install output.
  assert_absent  "$1" "Restart Claude Code to activate the plugin"
  assert_contains "$1" "The quarry CLI is installed and works via the command line"
}

exercise_roundtrip() {
  # A bare container has no init system, so `quarry install` could not register a
  # launchd/systemd service (it degraded, as designed) and the daemon is not
  # running. The harness plays the init manager: start quarryd directly with the
  # TLS material `quarry install` already generated.
  certs="$HOME/.punt-labs/quarry/tls"
  scheme="http"
  tlsarg=""
  if [ -f "$certs/server.crt" ] && [ -f "$certs/server.key" ]; then
    scheme="https"
    tlsarg="--tls"
  fi
  # $tlsarg is intentionally word-split: empty = no flag, "--tls" = one argument.
  # shellcheck disable=SC2086
  quarryd --port 8420 --host 127.0.0.1 $tlsarg > "$HOME/quarryd.log" 2>&1 &
  dpid=$!

  ready=0
  i=0
  while [ "$i" -lt 60 ]; do
    if curl -fsk "$scheme://127.0.0.1:8420/health" 2>/dev/null |
         grep -q '"state"[[:space:]]*:[[:space:]]*"ready"'; then
      ready=1
      break
    fi
    kill -0 "$dpid" 2>/dev/null ||
      { cat "$HOME/quarryd.log"; echo "quarryd exited before becoming ready" >&2; exit 1; }
    i=$((i + 1))
    sleep 1
  done
  [ "$ready" = 1 ] ||
    { cat "$HOME/quarryd.log"; echo "quarryd not ready after 60s" >&2; exit 1; }
  echo "  quarryd started + healthy ($scheme://127.0.0.1:8420)"

  if [ "$scheme" = "https" ]; then
    quarry login 127.0.0.1 --yes > "$HOME/login.log" 2>&1 ||
      { cat "$HOME/login.log"; echo "quarry login 127.0.0.1 failed" >&2; exit 1; }
    echo "  quarry login 127.0.0.1 configured TLS trust"
  fi

  token="harness-clean-machine-token-$$"
  # `quarry remember` ingests inline content from stdin and requires --name.
  printf '%s proves the clean-machine install round-trip\n' "$token" |
    quarry remember --name "harness-$$" > "$HOME/remember.log" 2>&1 ||
    { cat "$HOME/remember.log"; echo "quarry remember failed" >&2; exit 1; }

  found=0
  i=0
  while [ "$i" -lt 30 ]; do
    if quarry find "$token" 2>/dev/null | grep -qF "$token"; then
      found=1
      break
    fi
    i=$((i + 1))
    sleep 1
  done
  [ "$found" = 1 ] ||
    { quarry find "$token" 2>&1 || true; echo "quarry find did not surface the token" >&2; exit 1; }
  echo "  quarry remember -> find round-trip OK"

  kill "$dpid" 2>/dev/null || true
  wait "$dpid" 2>/dev/null || true
}

# --- Preconditions -----------------------------------------------------------
command -v quarry >/dev/null 2>&1 &&
  { echo "NOT a clean machine: quarry already on PATH" >&2; exit 1; }
[ -s "$WHEEL" ] || { echo "working-tree wheel missing: $WHEEL" >&2; exit 1; }

# --- Scenario A: auto-skip (claude ABSENT) -----------------------------------
say "Step 1: install CLI-only, claude ABSENT (capability auto-skip)"
command -v claude >/dev/null 2>&1 &&
  { echo "auto-skip scenario needs claude absent" >&2; exit 1; }
OUT=$(QUARRY_LOCAL_WHEEL="$WHEEL" sh "$HOME/install.sh" 2>&1) ||
  { echo "$OUT"; echo "install.sh FAILED (auto-skip)" >&2; exit 1; }
echo "$OUT"
say "Step 1 assertions: CLI-only success, no plugin line, no-claude remedy"
assert_cli_only "$OUT"
assert_contains "$OUT" "Claude Code was not found"

export PATH="$HOME/.local/bin:$PATH"

say "Step 2: quarry resolves on PATH + version"
command -v quarry >/dev/null 2>&1 || { echo "quarry not on PATH after install" >&2; exit 1; }
V=$(quarry version 2>&1) || true
echo "  quarry version -> $V"
printf '%s' "$V" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+' ||
  { echo "quarry version did not print a semver" >&2; exit 1; }

say "Step 3: quarry doctor runs (daemon down on a bare box -> non-zero OK)"
D=$(quarry doctor 2>&1) || true
echo "$D"
assert_contains "$D" "punt-quarry"
# The two required checks that used to abort the clean-machine install now pass:
assert_contains "$D" "Core imports"
assert_absent   "$D" "Failed: cv2"

say "Step 4: exercise the installed CLI end-to-end (harness-started quarryd)"
exercise_roundtrip

# --- Scenario B: flag-skip (claude PRESENT + --no-plugin) ---------------------
say "Step 5: install with claude PRESENT + --no-plugin (operator-driven skip)"
install_claude_shim
OUT=$(QUARRY_LOCAL_WHEEL="$WHEEL" sh "$HOME/install.sh" --no-plugin 2>&1) ||
  { echo "$OUT"; echo "install.sh --no-plugin FAILED" >&2; exit 1; }
echo "$OUT"
assert_cli_only "$OUT"
assert_contains "$OUT" "without --no-plugin"
assert_absent "$(cat "$SHIM_LOG")" "plugin"
assert_absent "$(cat "$SHIM_LOG")" "marketplace"
echo "  claude PRESENT but never invoked for a plugin/marketplace step"

# --- Scenario C: env-skip (claude PRESENT + QUARRY_NO_PLUGIN=1) ---------------
say "Step 6: install with claude PRESENT + QUARRY_NO_PLUGIN=1 (env skip)"
: > "$SHIM_LOG"
OUT=$(QUARRY_NO_PLUGIN=1 QUARRY_LOCAL_WHEEL="$WHEEL" sh "$HOME/install.sh" 2>&1) ||
  { echo "$OUT"; echo "QUARRY_NO_PLUGIN=1 install FAILED" >&2; exit 1; }
echo "$OUT"
assert_cli_only "$OUT"
assert_contains "$OUT" "without --no-plugin"
assert_absent "$(cat "$SHIM_LOG")" "plugin"
assert_absent "$(cat "$SHIM_LOG")" "marketplace"
echo "  QUARRY_NO_PLUGIN=1 skip is identical to --no-plugin"

say "ALL STEPS PASSED"
