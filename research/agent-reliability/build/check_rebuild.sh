#!/usr/bin/env bash
# Rebuild the templates in a scratch folder and check the archive and the
# incoming files come out byte for byte the same as the build stage's.
# Writes the hashes to <out> and fails if they differ.
#
# Usage: build/check_rebuild.sh <calkit rev> <manifest> <incoming file>
#     <site E dir> <out>
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REV="$1" MANIFEST="$2" INCOMING="$3" SITE_E="$4" OUT="$5"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
bash "$HERE/build_templates.sh" "$REV" "$WORK/templates.tar.gz" \
  "$WORK/templates.json" "$WORK/incoming.csv" "$WORK/site-e" > /dev/null
python - "$MANIFEST" "$INCOMING" "$SITE_E" "$WORK" "$OUT" <<'EOF'
import hashlib, json, sys
from pathlib import Path
manifest, incoming, site_e, work, out = map(Path, sys.argv[1:])
def get_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def get_hashes(folder):
    return {p.name: get_sha256(p) for p in sorted(folder.iterdir())}
result = {
    "archive_sha256": json.loads(manifest.read_text())["archive_sha256"],
    "rebuilt_archive_sha256": get_sha256(work / "templates.tar.gz"),
    "incoming_sha256": get_sha256(incoming),
    "rebuilt_incoming_sha256": get_sha256(work / "incoming.csv"),
    "site_e_sha256": get_hashes(site_e),
    "rebuilt_site_e_sha256": get_hashes(work / "site-e"),
}
result["identical"] = (
    result["archive_sha256"] == result["rebuilt_archive_sha256"]
    and result["incoming_sha256"] == result["rebuilt_incoming_sha256"]
    and result["site_e_sha256"] == result["rebuilt_site_e_sha256"]
)
out.write_text(json.dumps(result, indent=2) + "\n")
sys.exit(0 if result["identical"] else "rebuild differs")
EOF
