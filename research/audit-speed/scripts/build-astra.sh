#!/usr/bin/env bash
# Build the ASTRA version of the study in astra/ from shared/, the way a coding
# agent following the astra skill and the lightcone-cli README would: lc init,
# uv add, astra.yaml spec, commit, materialize on a local cluster, then record
# findings and validate.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/versions.env"
unset VIRTUAL_ENV
export PATH="$ROOT/tools/astra/bin:$PATH"
# Keep lc's compute catalog and cluster state out of ~/.lightcone
export LC_COMPUTE_CONFIG="$ROOT/tools/lc-compute.yaml"
mkdir -p "$ROOT/tools/lc-compute"
printf 'connection_root: %s\n' "$ROOT/tools/lc-compute" > "$LC_COMPUTE_CONFIG"
export GIT_AUTHOR_NAME="Audit Builder" GIT_AUTHOR_EMAIL="builder@example.org"
export GIT_COMMITTER_NAME="Audit Builder" GIT_COMMITTER_EMAIL="builder@example.org"
PROJ="$ROOT/astra"
if [ -d "$PROJ" ]; then chmod -R u+w "$PROJ"; rm -rf "$PROJ"; fi
lc init "$PROJ"
cd "$PROJ"
# Shared code and docs
mkdir -p src
cp "$ROOT"/shared/{generate_data,clean_data,fit_model,make_figure,write_report}.py src/
cp "$ROOT"/shared/{report_template,codebook}.md .
uv add --python "$PYTHON_VERSION" \
  matplotlib==3.11.2 numpy==2.5.5 pandas==3.1.1 statsmodels==0.15.0
cp "$ROOT/scripts/astra/astra.yaml" astra.yaml
cp "$ROOT/scripts/astra/baseline.yaml" universes/baseline.yaml
astra validate
git add -A && git commit -q -m "Specify analysis and add code"
# Materialize on the built-in local offer
CLUSTER="$(lc compute launch --wait)"
trap 'lc compute down "$CLUSTER" || true' EXIT
lc materialize "$CLUSTER"
lc compute down "$CLUSTER"
trap - EXIT
# Findings read from the materialized outputs, then the MySTRA report page
uv run --no-project --with pyyaml python "$ROOT/scripts/astra_add_findings.py" \
  astra.yaml results/baseline/model_results.json results/baseline/report.md
cp "$ROOT/scripts/astra/index.md" index.md
astra validate
astra validate astra.yaml --verify-evidence
git add -A && git commit -q -m "Record findings and report page"
lc status
git status --short
