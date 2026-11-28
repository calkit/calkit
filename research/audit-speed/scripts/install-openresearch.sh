#!/usr/bin/env bash
# Install the OpenResearch CLI (orx) from its GitHub release into tools/,
# verifying the published checksum. Nothing outside tools/ is touched.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/versions.env"
DEST="$ROOT/tools/openresearch"
ASSET="openresearch-cli-${OPENRESEARCH_TARGET}.tar.gz"
BASE="https://github.com/alphaXiv/OpenResearch/releases/download/${OPENRESEARCH_VERSION}"
rm -rf "$DEST" && mkdir -p "$DEST/download" "$DEST/bin"
curl -fsSL -o "$DEST/download/$ASSET" "$BASE/$ASSET"
curl -fsSL -o "$DEST/download/$ASSET.sha256" "$BASE/$ASSET.sha256"
expected="$(awk '{print $1}' "$DEST/download/$ASSET.sha256")"
actual="$(shasum -a 256 "$DEST/download/$ASSET" | awk '{print $1}')"
[ "$expected" = "$actual" ] || { echo "checksum mismatch" >&2; exit 1; }
tar -xzf "$DEST/download/$ASSET" -C "$DEST/download"
find "$DEST/download" -type f -name orx -perm -u+x -exec cp {} "$DEST/bin/orx" \;
"$DEST/bin/orx" --version
