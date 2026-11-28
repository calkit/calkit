#!/usr/bin/env bash
# Build the ASTRA arm in astra/, the way a coding agent following the astra
# skill and the lightcone-cli README would: lc init, uv add, astra.yaml with
# declared inputs and a decision with two universes, commit, materialize on
# a local cluster, then typed findings and a MySTRA report page (index.md)
# that shows them. Then the corrected sessions export replaces the original,
# everything is rematerialized, and the findings are retyped, all but one
# number.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/versions.env"
unset VIRTUAL_ENV
export PATH="$ROUND_1_TOOLS/astra/bin:$PATH"
# Keep lc's compute catalog and cluster state out of ~/.lightcone
export LC_COMPUTE_CONFIG="$ROUND_1_TOOLS/lc-compute.yaml"
export GIT_AUTHOR_NAME="Audit Builder" GIT_AUTHOR_EMAIL="builder@example.org"
export GIT_COMMITTER_NAME="Audit Builder" GIT_COMMITTER_EMAIL="builder@example.org"
PROJ="$ROOT/astra"
if [ -d "$PROJ" ]; then chmod -R u+w "$PROJ"; rm -rf "$PROJ"; fi
lc init "$PROJ"
cd "$PROJ"
# Code, codebook, and the raw data as first received
mkdir -p src
cp "$ROOT"/shared/{prepare_data,fit_model,make_figure}.py src/
cp "$ROOT/build-data/codebook_v1.md" codebook.md
cp "$ROOT/build-data/participants.csv" data/participants.csv
cp "$ROOT/build-data/sessions_v1.csv" data/sessions.csv
# shellcheck disable=SC2086
uv add -q --python "$PYTHON_VERSION" $PACKAGES
cp "$ROOT/scripts/astra/astra.yaml" astra.yaml
cp "$ROOT/scripts/astra/baseline.yaml" universes/baseline.yaml
cp "$ROOT/scripts/astra/change_score.yaml" universes/change_score.yaml
astra validate
git add -A && git commit -q -m "Specify analysis with baseline-adjustment decision, add code and data"
materialize() {
  local cluster
  cluster="$(lc compute launch --wait)"
  lc materialize "$cluster"
  lc compute down "$cluster"
}
materialize
# Findings typed from the materialized outputs, and the report page
uv run -q --no-project --with pyyaml python "$ROOT/scripts/astra/set_findings.py" \
  astra.yaml "$ROOT/scripts/astra/findings_v1.yaml"
cp "$ROOT/scripts/astra/index.md" index.md
astra validate
git add -A && git commit -q -m "Record findings and report page"
# Corrected sessions export replaces the original
cp "$ROOT/build-data/sessions_v2.csv" data/sessions.csv
cp "$ROOT/shared/codebook.md" codebook.md
git add -A && git commit -q -m "Use corrected sessions export with week-12 form B rescored"
lc materialize --check || true
materialize
# Findings retyped from the new outputs; one number is left from before
uv run -q --no-project --with pyyaml python "$ROOT/scripts/astra/set_findings.py" \
  astra.yaml "$ROOT/scripts/astra/findings_v2.yaml"
astra validate
astra validate astra.yaml --verify-evidence
git add -A && git commit -q -m "Update findings for corrected sessions export"
lc status
git status --short
git log --oneline
