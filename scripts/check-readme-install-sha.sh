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
# Requires the pinned commit to be present in the local object DB. The release
# workflow checks out with fetch-depth: 0, so full history — and therefore the
# pinned commit — is always available there. Under a shallow clone the pinned
# commit is absent and this fails with a clear, actionable message (deepen the
# clone), rather than silently passing.
#
# Usage: ./scripts/check-readme-install-sha.sh
#
# Env overrides (for hermetic testing): REPO_DIR (git repo to operate in),
# README_PATH, INSTALL_PATH.

set -euo pipefail

# Operate inside REPO_DIR (default: the repo this script lives in). Making the
# directory an override keeps the check hermetically testable against a fixture
# repo instead of the live checkout's history/clone-depth.
repo_dir="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$repo_dir"

readme="${README_PATH:-README.md}"
install_sh="${INSTALL_PATH:-install.sh}"

# Extract every SHA a README install URL pins, de-duplicated. Uses a plain
# command substitution + `while read` rather than `mapfile`/`readarray`, which
# do not exist in Bash 3.2 (macOS's default /bin/bash) — a local-contributor
# portability trap. The trailing `|| true` is load-bearing under `set -o
# pipefail`: `grep` exits non-zero when it matches nothing, which would abort
# the script before the `[ -z "$shas" ]` check below and skip the intended
# "no install-URL SHA found" message. `|| true` lets a no-match fall through to
# that empty-check branch.
shas=$(
    grep -oE 'raw\.githubusercontent\.com/punt-labs/quarry/[0-9a-f]{7,40}/' "$readme" \
        | grep -oE '[0-9a-f]{7,40}' \
        | sort -u \
        || true
)

if [ -z "$shas" ]; then
    echo "ERROR: no install-URL SHA found in $readme" >&2
    exit 1
fi

count=0
first_sha=""
while IFS= read -r sha; do
    count=$((count + 1))
    if [ -z "$first_sha" ]; then
        first_sha="$sha"
    fi
done <<EOF
$shas
EOF

if [ "$count" -ne 1 ]; then
    echo "ERROR: README install URLs pin multiple SHAs:" >&2
    echo "$shas" >&2
    exit 1
fi

readme_sha="$first_sha"

if ! git rev-parse --verify --quiet "${readme_sha}^{commit}" >/dev/null; then
    echo "ERROR: README install SHA $readme_sha is not present in the local git" >&2
    echo "       object DB. This usually means a shallow clone (actions/checkout" >&2
    echo "       without fetch-depth: 0). The release workflow fetches full history" >&2
    echo "       (fetch-depth: 0), so the pinned commit is always present there;" >&2
    echo "       deepen the clone (git fetch --unshallow) to run this check locally." >&2
    exit 1
fi

# The pinned installer must match the current one byte-for-byte. Both sides use
# the same resolved $install_sh path — the committed blob (git show <sha>:<path>)
# and the working-tree file — so INSTALL_PATH varies both reads together and a
# fixture can point the check at a differently-named installer.
if ! git show "${readme_sha}:${install_sh}" | diff -q - "$install_sh" >/dev/null; then
    echo "ERROR: install.sh at README SHA $readme_sha differs from $install_sh." >&2
    echo "       The README install-URL SHA is stale — bump it to a commit whose" >&2
    echo "       install.sh matches the current one." >&2
    exit 1
fi

echo "OK: README install SHA $readme_sha pins an install.sh matching $install_sh"
