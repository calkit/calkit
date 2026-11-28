#!/usr/bin/env bash
# Install lightcone-cli (lc) and astra-tools (astra) from PyPI with uv tool,
# into tools/ rather than the user's uv tool directory.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/versions.env"
export UV_TOOL_DIR="$ROOT/tools/uv-tools"
export UV_TOOL_BIN_DIR="$ROOT/tools/astra/bin"
mkdir -p "$UV_TOOL_DIR" "$UV_TOOL_BIN_DIR"
uv tool install --force --python "$PYTHON_VERSION" \
  "lightcone-cli==${LIGHTCONE_CLI_VERSION}" \
  --with "astra-tools==${ASTRA_TOOLS_VERSION}" \
  --with-executables-from astra-tools
"$UV_TOOL_BIN_DIR/lc" --version
"$UV_TOOL_BIN_DIR/astra" --version
