#!/usr/bin/env bash
# Build the .mcpb Desktop Extension bundle.
#
# Prerequisites: npm install -g @anthropic-ai/mcpb
#
# Usage: ./scripts/build-mcpb.sh
#
# Output: dist/quarry-mcp-<version>.mcpb

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

echo "Building quarry-mcp $version .mcpb bundle..."

mkdir -p dist
mcpb pack . "dist/quarry-mcp-${version}.mcpb"

# Create stable-named copy for GitHub release (latest/download/quarry-mcp.mcpb).
cp "dist/quarry-mcp-${version}.mcpb" "dist/quarry-mcp.mcpb"

echo "Built: dist/quarry-mcp-${version}.mcpb"
echo "       dist/quarry-mcp.mcpb (stable name)"
echo "Size: $(du -h "dist/quarry-mcp-${version}.mcpb" | cut -f1)"
