#!/usr/bin/env bash
# Rebuild the templates in a scratch folder and check the archive and the
# incoming file come out byte for byte the same as the build stage's.
# Writes the hashes to <out> and fails if they differ.
#
# Usage: build/check_rebuild.sh <calkit rev> <manifest> <incoming file> <out>
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REV="$1" MANIFEST="$2" INCOMING="$3" OUT="$4"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
bash "$HERE/build_templates.sh" "$REV" "$WORK/templates.tar.gz" \
  "$WORK/templates.json" "$WORK/incoming.csv" > /dev/null
python - "$MANIFEST" "$INCOMING" "$WORK" "$OUT" <<'EOF'
import hashlib, json, sys
from pathlib import Path
manifest, incoming, work, out = map(Path, sys.argv[1:])
def get_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
result = {
    "archive_sha256": json.loads(manifest.read_text())["archive_sha256"],
    "rebuilt_archive_sha256": get_sha256(work / "templates.tar.gz"),
    "incoming_sha256": get_sha256(incoming),
    "rebuilt_incoming_sha256": get_sha256(work / "incoming.csv"),
}
result["identical"] = (
    result["archive_sha256"] == result["rebuilt_archive_sha256"]
    and result["incoming_sha256"] == result["rebuilt_incoming_sha256"]
)
out.write_text(json.dumps(result, indent=2) + "\n")
sys.exit(0 if result["identical"] else "rebuild differs")
EOF
