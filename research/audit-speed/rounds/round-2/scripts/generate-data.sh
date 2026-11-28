#!/usr/bin/env bash
# Generate the raw data every arm receives into build-data/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/versions.env"
unset VIRTUAL_ENV
rm -rf "$ROOT/build-data" && mkdir -p "$ROOT/build-data"
# shellcheck disable=SC2086
uv run -q --no-project --python "$PYTHON_VERSION" \
  $(printf -- '--with %s ' $PACKAGES) \
  python -W ignore "$ROOT/scripts/generate_data.py" --out-dir "$ROOT/build-data"
# The codebook as first received, before the corrected export's note
awk '/^The original export/ {exit} {print}' "$ROOT/shared/codebook.md" \
  | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}' > "$ROOT/build-data/codebook_v1.md"
shasum -a 256 "$ROOT"/build-data/*.csv
