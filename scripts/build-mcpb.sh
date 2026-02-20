#!/usr/bin/env bash
# Build the .mcpb Desktop Extension bundle.
#
# Prerequisites: npm install -g @anthropic-ai/mcpb
#
# Usage: ./scripts/build-mcpb.sh
#
# Output: dist/punt-quarry-<version>.mcpb

set -euo pipefail

cd "$(dirname "$0")/.."

# Extract version from manifest.json.
version=$(python3 -c "import json; print(json.load(open('manifest.json'))['version'])")

# Verify manifest version matches pyproject.toml version.
pyproject_version=$(python3 -c "
import re
text = open('pyproject.toml').read()
m = re.search(r'^version\s*=\s*\"(.+?)\"', text, re.MULTILINE)
print(m.group(1) if m else '')
")

if [ -z "$pyproject_version" ]; then
    echo "ERROR: Could not find version in pyproject.toml" >&2
    exit 1
fi

if [ "$version" != "$pyproject_version" ]; then
    echo "ERROR: Version mismatch — manifest.json ($version) != pyproject.toml ($pyproject_version)" >&2
    exit 1
fi

echo "Building punt-quarry $version .mcpb bundle..."

mkdir -p dist
mcpb pack . "dist/punt-quarry-${version}.mcpb"

# Create stable-named copy for GitHub release (latest/download/punt-quarry.mcpb).
cp "dist/punt-quarry-${version}.mcpb" "dist/punt-quarry.mcpb"

echo "Built: dist/punt-quarry-${version}.mcpb"
echo "       dist/punt-quarry.mcpb (stable name)"
echo "Size: $(du -h "dist/punt-quarry-${version}.mcpb" | cut -f1)"
