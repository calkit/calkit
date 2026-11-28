#!/usr/bin/env bash
# Build the OpenResearch arm in openresearch/, the way an agent in an `orx up`
# session would, following the orx skills: create the project, seed a
# Baseline experiment on its branch with the raw data as first received,
# declare its stages, measures, and view, and run it on the local backend.
# The corrected sessions export then goes on a child node, since a node a run
# has answered is frozen, and the change-score sensitivity analysis on a
# grandchild, changing only analysis.json. Notes on each node and the report
# in the artifacts directory are typed from the runs' measures; the
# corrected node's notes and the report keep one number from the Baseline.
# The dashboard runs headless on its own data and config directories; project
# creation goes through the dashboard's API, as its "create project" form
# does. No agent harness is started.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/versions.env"
unset VIRTUAL_ENV
ORX="$ROUND_1_TOOLS/openresearch/bin/orx"
HERE="$ROOT/scripts/openresearch"
OUT="$ROOT/openresearch"
PROJ="$OUT/project"
PORT="${ORX_PORT:-4798}"
# Build traces go outside the project, so auditors see only what orx keeps
LOGS="$ROOT/build-logs/openresearch"
# Give orx its own home, so it can't pick up credentials stored there, e.g.,
# a Hugging Face token, which it would copy into each local run's launch.json
export UV_CACHE_DIR="${UV_CACHE_DIR:-$(uv cache dir)}"
export HOME="$ROOT/tools/orx-home"
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN GITHUB_TOKEN GH_TOKEN
export XDG_CONFIG_HOME="$ROOT/tools/orx-config"
export ORX_DATA_DIR="$OUT/orx-data"
export GIT_AUTHOR_NAME="Audit Builder" GIT_AUTHOR_EMAIL="builder@example.org"
export GIT_COMMITTER_NAME="Audit Builder" GIT_COMMITTER_EMAIL="builder@example.org"
if [ -d "$OUT" ]; then rm -rf "$OUT"; fi
if [ -d "$LOGS" ]; then rm -rf "$LOGS"; fi
mkdir -p "$OUT" "$LOGS" "$ORX_DATA_DIR" "$XDG_CONFIG_HOME" "$HOME"
"$ORX" --version
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
  -d "{\"name\": \"cognitive-training\", \"path\": \"$PROJ\", \"createFolder\": true,
       \"requireNewFolder\": true, \"initializeGit\": true,
       \"githubSyncEnabled\": false, \"runCommand\": \"bash run.sh\",
       \"starterAgent\": {\"harness\": \"none\"}}" > "$LOGS/project.json"
ARTIFACTS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["project"]["artifactsDir"])' "$LOGS/project.json")"
cd "$PROJ"
# Create a node and check out its branch; prints its id
new_node() {
  local log="$LOGS/create-$1.txt"
  shift
  "$ORX" create-experiment "$@" > "$log"
  git checkout -q "$(awk '$1 == "branch:" {print $2}' "$log")"
  awk '$1 == "id:" {print $2}' "$log"
}
# Run a node, wait for it, and print its run id
run_node() {
  local exp_id="$1" name="$2"
  "$ORX" exp run "$exp_id" --backend local > "$LOGS/run-$name.txt"
  "$ORX" exp wait "$exp_id" --timeout 900 >> "$LOGS/run-$name.txt"
  # Let the server finish reading the log's measures
  for _ in $(seq 1 30); do
    "$ORX" exp status "$exp_id" | grep -q "final log is still being read" || break
    sleep 1
  done
  "$ORX" exp status "$exp_id" > "$LOGS/exp-status-$name.txt"
  "$ORX" exp status "$exp_id" --json > "$LOGS/exp-status-$name.json"
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["runId"])' \
    "$LOGS/exp-status-$name.json"
}
# Write a node's notes, typed, with its run id
set_notes() {
  sed "s/{run_id}/$3/" "$HERE/$2" | "$ORX" exp desc "$1" --stdin
}
# Baseline, on the original sessions export
BASE_ID="$(new_node baseline --title "Baseline" \
  --description "ANCOVA of week-12 score on arm, baseline score, age, and education. Measures: training effect, N, week-12 means, education gap, R².")"
mkdir -p scripts data/raw
cp "$ROOT"/shared/{prepare_data,fit_model,make_figure}.py scripts/
cp "$ROOT/build-data/participants.csv" data/raw/participants.csv
cp "$ROOT/build-data/sessions_v1.csv" data/raw/sessions.csv
cp "$ROOT/build-data/codebook_v1.md" codebook.md
cp "$HERE/run.sh" run.sh
cp "$HERE/analysis.json" analysis.json
uv init -q --bare --name cognitive-training --python "$PYTHON_VERSION" --no-workspace
# shellcheck disable=SC2086
uv add -q $PACKAGES
printf '.venv/\n__pycache__/\ndata/analysis.csv\nresults/\n' > .gitignore
git add -A && git commit -q -m "Seed baseline: analysis scripts, raw data, run script, and locked environment"
"$ORX" exp view set "$BASE_ID" --file "$HERE/view.xml" --config "$HERE/plan.json"
BASE_RUN="$(run_node "$BASE_ID" baseline)"
set_notes "$BASE_ID" notes-baseline.md "$BASE_RUN"
# Corrected sessions export, on a child of the frozen Baseline
FIX_ID="$(new_node corrected --parent "$BASE_ID" --title "Corrected sessions export" \
  --description "Rerun the Baseline on the corrected sessions export, which rescored week-12 form B sessions; code unchanged.")"
cp "$ROOT/build-data/sessions_v2.csv" data/raw/sessions.csv
cp "$ROOT/shared/codebook.md" codebook.md
git add -A && git commit -q -m "Use corrected sessions export with week-12 form B rescored"
FIX_RUN="$(run_node "$FIX_ID" corrected)"
# Change-score sensitivity analysis, on top of the corrected data
CHANGE_ID="$(new_node change --parent "$FIX_ID" --title "Change score" \
  --description "Sensitivity analysis: change from baseline to week 12 as the outcome instead of ANCOVA; set adjustment to change in analysis.json.")"
printf '{"adjustment": "change"}\n' > analysis.json
git add -A && git commit -q -m "Model change from baseline instead of ANCOVA"
CHANGE_RUN="$(run_node "$CHANGE_ID" change)"
set_notes "$CHANGE_ID" notes-change.md "$CHANGE_RUN"
# Report into the artifacts directory, with the corrected run's figure, and
# the corrected node's notes
mkdir -p "$ARTIFACTS/cognitive-training"
cp "$ORX_DATA_DIR/local-runs/$FIX_RUN/repo/results/score_by_week.png" \
  "$ARTIFACTS/cognitive-training/"
cp "$HERE/report.md" "$ARTIFACTS/cognitive-training/report.md"
set_notes "$FIX_ID" notes-corrected.md "$FIX_RUN"
for id in "$BASE_ID" "$FIX_ID" "$CHANGE_ID"; do "$ORX" exp desc "$id"; echo; done
"$ORX" runs | tee "$LOGS/runs.txt"
"$ORX" project view | tee "$LOGS/project-view.txt"
"$ORX" exp view check "$FIX_RUN" | tee "$LOGS/view-check.txt"
git checkout -q main
stop_servers
trap - EXIT
# Fail if any credential-looking string landed in the outputs
if grep -rlaE --exclude-dir=.venv 'hf_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}' "$OUT" "$ROOT/tools/orx-home" "$ROOT/tools/orx-config" "$LOGS"; then
  echo "credential found" >&2
  exit 1
fi
echo "no credentials found"
