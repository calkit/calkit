#!/usr/bin/env bash
# Generate the raw data and build all four arms of round 2. A record of what
# was run, not a pipeline: it reuses round 1's installs of lc, astra, and
# orx (install-astra.sh and install-openresearch.sh in round 1's scripts),
# runs Calkit from the calkit-s3 worktree, and writes everything under
# audit-compare-r2/.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
bash "$HERE/generate-data.sh"
bash "$HERE/build-none.sh"
bash "$HERE/build-calkit.sh"
bash "$HERE/build-astra.sh"
bash "$HERE/build-openresearch.sh"
# Fail if a credential-looking string landed in anything written here;
# installed packages and orx's downloaded agent binary are skipped, since
# hashes and minified code in them match by chance
if grep -rlaE --exclude-dir=.venv --exclude-dir=none-venv \
  --exclude-dir=managed-agents \
  '(^|[^A-Za-z0-9_-])(hf_[A-Za-z0-9]{30,}|gh[pousr]_[A-Za-z0-9]{30,})' \
  "$ROOT" "$ROOT/../audit-private"; then
  echo "credential found" >&2
  exit 1
fi
echo "Built none/, calkit/, astra/, and openresearch/; no credentials found"
