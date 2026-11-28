#!/usr/bin/env bash
# Build every arm's template and task 4's incoming file.
#
# Builds the none arm as round 2 did (build/build_none.sh), the history arms
# (messy, messy-git, make, calkit), and the Git arms' stale variants for
# stale-clone, by replaying one research history in each
# (build/build_history.py), with the Calkit arm's commands run by Calkit at
# <calkit rev>. Builds outside the repo, so no Calkit or Git command sees the
# research project around it, then archives the templates into one
# deterministic .tar.gz, since they hold nested Git repos, and lists each
# template's files and Git head in a JSON manifest.
#
# Usage: build/build_templates.sh <calkit rev> <archive> <manifest>
#     <incoming file>
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
REV="$1"
mkdir -p "$(dirname "$2")" "$(dirname "$3")" "$(dirname "$4")"
ARCHIVE="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
MANIFEST="$(cd "$(dirname "$3")" && pwd)/$(basename "$3")"
INCOMING="$(cd "$(dirname "$4")" && pwd)/$(basename "$4")"
unset VIRTUAL_ENV PYTHONPATH
# The history's dates are Pacific time, and every commit is the builder's
export TZ=America/Los_Angeles
PY="$ROOT/.venv/bin/python"
eval "$("$PY" -c "
import sys; sys.path.insert(0, '$ROOT/bench'); import arms
for k, v in arms.get_git_identity_env(arms.BUILDER).items():
    print(f'export {k}=\"{v}\"')
")"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
BENCH_CALKIT="$(bash "$HERE/snapshot_calkit.sh" "$REV" "$WORK/calkit")"
export BENCH_CALKIT
TEMPLATES="$WORK/templates"
mkdir -p "$TEMPLATES/stale" "$WORK/data"
"$PY" -W ignore "$HERE/generate_data.py" --out-dir "$WORK/data" > /dev/null
# The history arms in parallel, then none; the notebooks' kernels log to
# stderr, which is shown only if a build fails
pids=()
for arm in messy messy-git make calkit; do
  "$PY" "$HERE/build_history.py" "$arm" "$TEMPLATES/$arm" \
    > "$WORK/build-$arm.log" 2>&1 &
  pids+=($!)
done
for arm in messy-git make calkit; do
  "$PY" "$HERE/build_history.py" "$arm" "$TEMPLATES/stale/$arm" --stale \
    > "$WORK/build-stale-$arm.log" 2>&1 &
  pids+=($!)
done
bash "$HERE/build_none.sh" "$PY" "$WORK/data" "$TEMPLATES/none" \
  > "$WORK/build-none.log" 2>&1 || { cat "$WORK/build-none.log"; exit 1; }
failed=0
for pid in "${pids[@]}"; do wait "$pid" || failed=1; done
if [ "$failed" = 1 ]; then
  tail -n 40 "$WORK"/build-*.log
  exit 1
fi
# Calkit recreates its environment and local state where it runs
rm -rf "$TEMPLATES"/{calkit,stale/calkit}/{.venv,.calkit/local/logs} \
  "$TEMPLATES"/{calkit,stale/calkit}/{.calkit/local/runs,.dvc/tmp}
# All the arms' current analysis outputs agree
cmp "$TEMPLATES/make/results/score_by_week.png" \
  "$TEMPLATES/calkit/results/score_by_week.png"
cmp "$TEMPLATES/make/results/report.md" "$TEMPLATES/calkit/results/report.md"
cmp "$TEMPLATES/make/data/analysis.csv" "$TEMPLATES/none/data/merged_final.csv"
for arm in messy messy-git; do
  cmp "$TEMPLATES/$arm/data/merged_final.csv" \
    "$TEMPLATES/none/data/merged_final.csv"
  cmp "$TEMPLATES/$arm/results/model_ancova.json" \
    "$TEMPLATES/none/results/model_ancova.json"
done
cmp "$TEMPLATES/make/results/model-ancova.json" \
  "$TEMPLATES/none/results/model_ancova.json"
# Task 4's incoming file, from the coordinator
"$PY" "$HERE/make_corrected_participants.py" \
  --participants "$WORK/data/participants.csv" --out "$INCOMING"
# Times after the history ends only say when the build ran, e.g., in
# .git/, so they become the history's last step
"$PY" - "$TEMPLATES" "$ARCHIVE" "$MANIFEST" <<EOF
import datetime, json, subprocess, sys
from pathlib import Path
sys.path.insert(0, "$ROOT/bench")
import archive, arms
templates, out, manifest = map(Path, sys.argv[1:])
end = datetime.datetime(2026, 5, 18, 17).timestamp()
archive.pack(templates, out, clamp_after=end, clamp_to=end)
heads = {}
for project in sorted(p.parent for p in templates.rglob("README.md")):
    if project.parent not in (templates, templates / "stale"):
        continue
    git = None
    if (project / ".git").exists():
        git = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project, capture_output=True, text=True, check=True,
        ).stdout.strip()
    heads[project.relative_to(templates).as_posix()] = {
        "git_head": git,
        "files": arms.get_manifest(project),
    }
manifest.write_text(
    json.dumps(
        {"archive_sha256": arms.get_sha256(out), "templates": heads}, indent=2
    )
    + "\n"
)
EOF
echo "Built templates into $ARCHIVE"
