#!/usr/bin/env bash
# Scan the quarry daemon log directory for error/failure signals.
#
# The daemon writes to ~/.punt-labs/quarry/logs (quarry-stderr.log, quarry.log,
# quarry-stdout.log). Nothing surfaces the errors accumulating there — `quarry
# doctor` does not read the log and no one greps it — so a broken watch/sync
# feature logged 100+ "Watch index failed" lines that sat unnoticed for weeks
# (alongside historical "LanceError(IO): Too many open files"). This target
# closes that blind spot: a first-class diagnostic that greps the live logs for
# known error signals, prints a per-signal summary count, then the most recent
# matching lines.
#
# It is a diagnostic, not a gate: it ALWAYS exits 0 (even when matches are
# found, and even when the log dir or files are absent). Wiring it into a
# quality gate would make routine runtime noise fail the build; keep it a
# standalone probe like `make report`.
#
# Usage:
#   scripts/logs-errors.sh
#   LOG_DIR=/path/to/logs LOG_LINES=80 scripts/logs-errors.sh
#
# Env overrides:
#   LOG_DIR    daemon log directory (default $HOME/.punt-labs/quarry/logs)
#   LOG_LINES  most-recent matching lines to print (default 40)

set -euo pipefail

log_dir="${LOG_DIR:-$HOME/.punt-labs/quarry/logs}"
log_lines="${LOG_LINES:-40}"

# LOG_LINES feeds `tail -n`; a non-integer would crash it. Fall back with a
# warning rather than propagate the error (exception-boundary discipline: this
# diagnostic must not abort on a bad knob).
case "$log_lines" in
    '' | *[!0-9]*)
        echo "warning: LOG_LINES='$log_lines' is not a non-negative integer; using 40" >&2
        log_lines=40
        ;;
esac

# A missing log dir is the normal state before the daemon has ever run. Report
# it plainly and exit 0 — absence is not an error for a diagnostic.
if [ ! -d "$log_dir" ]; then
    echo "no daemon logs at $log_dir"
    exit 0
fi

# Collect the primary *.log files. The glob deliberately excludes rotated
# quarry.log.1..N (they match *.log.N, not *.log); the live files carry the
# current state. `[ -f ]` guards the literal-glob case when nothing matches,
# so an empty dir falls through to the no-logs branch below.
files=()
for f in "$log_dir"/*.log; do
    [ -f "$f" ] && files+=("$f")
done

if [ "${#files[@]}" -eq 0 ]; then
    echo "no daemon logs at $log_dir"
    exit 0
fi

# Error signals to summarize, as parallel label/pattern arrays (Bash 3.2, the
# macOS default, has no associative arrays). Patterns are matched
# case-insensitively (grep -i), which is what "case-insensitive where sensible"
# resolves to for a runtime-log probe: `ERROR`/`error`/`Error:` are all the same
# signal to an operator scanning for trouble.
labels=(
    "ERROR:"
    "Traceback:"
    "'Error:' lines:"
    "failed/Failed:"
    "not found:"
    "Too many open files / EMFILE:"
    "Watch index failed:"
    "Delete failed:"
)
patterns=(
    'ERROR'
    'Traceback'
    'Error:'
    'failed'
    'not found'
    'Too many open files|EMFILE'
    'Watch index failed'
    'Delete failed'
)

# One combined alternation drives both the distinct-line total and the
# recent-lines tail, built from the same patterns so the two never drift.
combined=""
for p in "${patterns[@]}"; do
    if [ -z "$combined" ]; then
        combined="$p"
    else
        combined="$combined|$p"
    fi
done

# Sum per-file line counts for a pattern across all log files. `grep -c` prints
# one `count` per file (filenames suppressed with -h); awk sums them. `|| true`
# is load-bearing under `set -o pipefail`: grep exits non-zero when a file has
# zero matches, which would otherwise abort the script.
count_signal() {
    { grep -hicE "$1" -- "${files[@]}" || true; } | awk '{ s += $1 } END { print s + 0 }'
}

names=""
for f in "${files[@]}"; do
    names="$names $(basename "$f")"
done

echo "quarry daemon log scan: $log_dir"
echo "files:$names"
echo
echo "error signal summary:"
i=0
while [ "$i" -lt "${#labels[@]}" ]; do
    n=$(count_signal "${patterns[$i]}")
    printf '  %-32s %s\n' "${labels[$i]}" "$n"
    i=$((i + 1))
done
echo

total=$({ grep -hicE "$combined" -- "${files[@]}" || true; } | awk '{ s += $1 } END { print s + 0 }')

if [ "$total" -eq 0 ]; then
    echo "no errors found"
    exit 0
fi

echo "most recent $log_lines matching lines:"
{ grep -hiE "$combined" -- "${files[@]}" || true; } | tail -n "$log_lines"
echo
echo "$total error lines found"
