#!/usr/bin/env bash
# Assert the README install-URL SHA is not stale.
#
# README.md pins install.sh to a commit SHA so users curl a stable installer:
#   curl -fsSL https://raw.githubusercontent.com/punt-labs/quarry/<sha>/install.sh | sh
#
# A stale <sha> ships an OLD installer to users even though install.sh has moved
# on — that is exactly how a stale 6f90f11 SHA shipped once, unnoticed because
# nothing verified it. The meaningful, non-circular invariant is content
# equality: install.sh AT the pinned SHA must be byte-identical to the install.sh
# in the working tree. If install.sh changes, the pin must be bumped or this
# fails. (Equality against a not-yet-created release commit would be circular;
# content equality is the property that actually protects users.)
#
# Usage: ./scripts/check-readme-install-sha.sh
#
# Env overrides (for testing): README_PATH, INSTALL_PATH.

set -euo pipefail

cd "$(dirname "$0")/.."

readme="${README_PATH:-README.md}"
install_sh="${INSTALL_PATH:-install.sh}"

# Extract every SHA that a README install URL pins, de-duplicated.
mapfile -t shas < <(
    grep -oE 'raw\.githubusercontent\.com/punt-labs/quarry/[0-9a-f]{7,40}/' "$readme" \
        | grep -oE '[0-9a-f]{7,40}' \
        | sort -u
)

if [ "${#shas[@]}" -eq 0 ]; then
    echo "ERROR: no install-URL SHA found in $readme" >&2
    exit 1
fi
if [ "${#shas[@]}" -ne 1 ]; then
    echo "ERROR: README install URLs pin multiple SHAs: ${shas[*]}" >&2
    exit 1
fi

readme_sha="${shas[0]}"

if ! git rev-parse --verify --quiet "${readme_sha}^{commit}" >/dev/null; then
    echo "ERROR: README install SHA $readme_sha is not a commit in this repo" >&2
    exit 1
fi

# The pinned installer must match the current one byte-for-byte.
if ! git show "${readme_sha}:install.sh" | diff -q - "$install_sh" >/dev/null; then
    echo "ERROR: install.sh at README SHA $readme_sha differs from $install_sh." >&2
    echo "       The README install-URL SHA is stale — bump it to a commit whose" >&2
    echo "       install.sh matches the current one." >&2
    exit 1
fi

echo "OK: README install SHA $readme_sha pins an install.sh matching $install_sh"
