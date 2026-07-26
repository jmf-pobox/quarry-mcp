#!/usr/bin/env bash
#
# Host-side orchestrator for the clean-machine install harness (make test-install-clean).
#
# 1. Builds a wheel from the WORKING TREE (uv build) and stages it.
# 2. Builds the clean-machine image (tests/harness/Dockerfile).
# 3. Runs the in-container guide (tests/harness/guide.sh), which installs the
#    staged wheel via install.sh's QUARRY_LOCAL_WHEEL hook and asserts the
#    CLI-only path across both skip triggers + a remember->find round-trip.
#
# The staged wheel means the harness gates THIS branch's install.sh AND package,
# not the already-released version on PyPI.
#
# Env:
#   HARNESS_IMAGE       image tag (default: quarry-install-harness:local)
#   HARNESS_SKIP_BUILD  set to 1 to skip `docker build` (CI pre-builds with
#                       buildx + gha layer cache, then runs with this set)
set -euo pipefail

cd "$(dirname "$0")/../.."

IMAGE="${HARNESS_IMAGE:-quarry-install-harness:local}"
STAGE="tests/harness/.stage"

echo "==> building working-tree wheel (uv build)"
rm -rf "$STAGE"
mkdir -p "$STAGE"
uv build --wheel --out-dir "$STAGE" >/dev/null
shopt -s nullglob
wheels=("$STAGE"/punt_quarry-*.whl)
shopt -u nullglob
if [ "${#wheels[@]}" -eq 0 ]; then
  echo "!! uv build produced no wheel in $STAGE" >&2
  exit 1
fi
wheel="${wheels[0]}"
# Keep the real PEP 427 wheel name — uv rejects a renamed wheel ("Must have a
# Python tag"). The Dockerfile COPYs the whole $STAGE dir and the guide globs it.
echo "    staged $(basename "$wheel") in $STAGE/"

if [ "${HARNESS_SKIP_BUILD:-0}" != "1" ]; then
  echo "==> building clean-machine image: $IMAGE"
  docker build -f tests/harness/Dockerfile -t "$IMAGE" .
else
  echo "==> skipping docker build (HARNESS_SKIP_BUILD=1); using existing $IMAGE"
fi

echo "==> running clean-machine guide"
docker run --rm "$IMAGE"
