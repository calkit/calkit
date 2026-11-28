#!/usr/bin/env bash
# Build the OpenResearch version of the study in openresearch/ from shared/,
# the way an agent in an `orx up` session would, following the orx skills:
# create the project, seed a Baseline experiment on its branch, declare its
# stages, measures, and view, launch it on the local backend, then write the
# report into the project's artifacts directory and the experiment notes.
# The dashboard runs headless on its own data and config directories; project
# creation goes through the dashboard's API, as its "create project" form
# does. No agent harness is started.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/versions.env"
unset VIRTUAL_ENV
ORX="$ROOT/tools/openresearch/bin/orx"
OUT="$ROOT/openresearch"
PROJ="$OUT/project"
PORT="${ORX_PORT:-4797}"
# Build traces go outside the project, so auditors see only what orx keeps
LOGS="$ROOT/build-logs/openresearch"
# Give orx its own home, so it can't pick up credentials stored there, e.g.,
# a Hugging Face token, which it would copy into each local run's launch.json
export UV_CACHE_DIR="${UV_CACHE_DIR:-$(uv cache dir)}"
export HOME="$ROOT/tools/orx-home"
unset HF_TOKEN
export XDG_CONFIG_HOME="$ROOT/tools/orx-config"
export ORX_DATA_DIR="$OUT/orx-data"
export GIT_AUTHOR_NAME="Audit Builder" GIT_AUTHOR_EMAIL="builder@example.org"
export GIT_COMMITTER_NAME="Audit Builder" GIT_COMMITTER_EMAIL="builder@example.org"
rm -rf "$OUT" "$LOGS"
mkdir -p "$OUT" "$LOGS" "$ORX_DATA_DIR" "$XDG_CONFIG_HOME" "$HOME"
"$ORX" telemetry off
# Start the dashboard server
"$ORX" up --no-browser --no-agent --no-telemetry --port "$PORT" \
  > "$LOGS/orx-up.log" 2>&1 &
UP_PID=$!
stop_servers() {
  kill "$UP_PID" 2>/dev/null || true
  pkill -f "$ORX up --headless" 2>/dev/null || true
}
trap stop_servers EXIT
for _ in $(seq 1 60); do
  curl -sf "http://127.0.0.1:$PORT/api/projects" > /dev/null && break
  sleep 1
done
# Create the project, as the dashboard's form does
curl -sf -X POST "http://127.0.0.1:$PORT/api/projects" \
  -H 'Content-Type: application/json' \
  -d "{\"name\": \"ses-study\", \"path\": \"$PROJ\", \"createFolder\": true,
       \"requireNewFolder\": true, \"initializeGit\": true,
       \"githubSyncEnabled\": false, \"runCommand\": \"bash run.sh\",
       \"starterAgent\": {\"harness\": \"none\"}}" > "$LOGS/project.json"
ARTIFACTS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["project"]["artifactsDir"])' "$LOGS/project.json")"
cd "$PROJ"
# Baseline experiment node, seeded on its own branch
"$ORX" create-experiment --title "Baseline" \
  --description "OLS of outcome on condition and SES category, excluding participants with missing SES. Measures: treatment effect, high vs. low SES difference, N, R²." \
  | tee "$LOGS/create-experiment.txt"
EXP_ID="$(awk '$1 == "id:" {print $2}' "$LOGS/create-experiment.txt")"
BRANCH="$(awk '$1 == "branch:" {print $2}' "$LOGS/create-experiment.txt")"
git checkout -q "$BRANCH"
mkdir -p scripts
cp "$ROOT"/shared/{generate_data,clean_data,fit_model,make_figure,write_report}.py scripts/
cp "$ROOT"/shared/{report_template,codebook}.md .
cp "$ROOT/scripts/openresearch/run.sh" run.sh
uv init --bare --name ses-study --python "$PYTHON_VERSION" --no-workspace
uv add matplotlib==3.11.2 numpy==2.5.5 pandas==3.1.1 statsmodels==0.15.0
printf '.venv/\n__pycache__/\ndata/\nresults/\n' > .gitignore
git add -A && git commit -q -m "Seed baseline: analysis scripts, run script, and locked environment"
git status --short
git show --stat --oneline HEAD
# Stages, measures, and view, before the first launch
"$ORX" exp view set "$EXP_ID" --file "$ROOT/scripts/openresearch/view.xml" \
  --config "$ROOT/scripts/openresearch/plan.json"
"$ORX" exp run "$EXP_ID" --backend local
"$ORX" exp wait "$EXP_ID" --timeout 900
# Let the server finish reading the log's measures
for _ in $(seq 1 30); do
  "$ORX" exp status "$EXP_ID" | grep -q "final log is still being read" || break
  sleep 1
done
"$ORX" exp status "$EXP_ID" | tee "$LOGS/exp-status.txt"
"$ORX" exp status "$EXP_ID" --json > "$LOGS/exp-status.json"
"$ORX" runs | tee "$LOGS/runs.txt"
RUN_ID="$(python3 "$ROOT/scripts/openresearch/get_run_id.py" "$LOGS/exp-status.json")"
"$ORX" exp view check "$RUN_ID" | tee "$LOGS/view-check.txt"
"$ORX" logs "$RUN_ID" | tee "$LOGS/run-log-summary.txt"
# Durable outputs into the artifacts directory, and notes on the node
RUN_REPO="$ORX_DATA_DIR/local-runs/$RUN_ID/repo"
mkdir -p "$ARTIFACTS/ses-study"
cp "$RUN_REPO"/results/{report.md,outcome_by_ses.png,model.json} "$ARTIFACTS/ses-study/"
python3 - "$RUN_REPO/results/model.json" "$RUN_ID" <<'EOF' | "$ORX" exp desc "$EXP_ID" --stdin
import json
import sys

r = json.load(open(sys.argv[1]))
run_id = sys.argv[2]
print(
    "OLS of outcome on condition and SES category, excluding participants"
    " with missing SES.\n\n"
    f"Result (run {run_id}): N = {r['n_analyzed']}. Treatment raised outcome"
    f" scores by {r['treatment_effect']:.2f} points (95% CI"
    f" {r['treatment_ci_low']:.2f} to {r['treatment_ci_high']:.2f};"
    f" p = {r['treatment_p']:.2g}). High-SES participants scored"
    f" {r['ses_high_vs_low']:.2f} points higher than low-SES participants"
    f" (95% CI {r['ses_high_ci_low']:.2f} to {r['ses_high_ci_high']:.2f};"
    f" p = {r['ses_high_p']:.2g}). R² = {r['r_squared']:.3f}.\n\n"
    "Report: artifacts/ses-study/report.md"
)
EOF
"$ORX" exp desc "$EXP_ID"
"$ORX" project view
git checkout -q main
# Fail if any credential-looking string landed in the outputs
if grep -rla --exclude-dir=.venv -E 'hf_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}' "$OUT"; then
  echo "credential found in $OUT" >&2
  exit 1
fi
