#!/usr/bin/env bash
# Run the analysis: merge participants with sessions, fit the model with the
# adjustment set in analysis.json, and plot scores by week.
set -euo pipefail
export PYTHONUNBUFFERED=1
report() { printf '::orx:: %s\n' "$1"; }
report '{"phase":"install"}'
uv sync --locked
ADJUSTMENT="$(uv run --locked python -c 'import json; print(json.load(open("analysis.json"))["adjustment"])')"
echo "adjustment: $ADJUSTMENT"
sha256sum data/raw/*.csv 2>/dev/null || shasum -a 256 data/raw/*.csv
report '{"phase":"analysis","step":0,"of":3,"unit":"steps"}'
uv run --locked python scripts/prepare_data.py \
  --participants data/raw/participants.csv --sessions data/raw/sessions.csv \
  --out data/analysis.csv
report '{"step":1}'
uv run --locked python scripts/fit_model.py --data data/analysis.csv \
  --adjustment "$ADJUSTMENT" --out results/model.json
report '{"step":2}'
uv run --locked python scripts/make_figure.py --data data/analysis.csv \
  --out results/score_by_week.png
report '{"step":3}'
uv run --locked python -c '
import json
r = json.load(open("results/model.json"))
print("::orx:: " + json.dumps({"m": {k: v for k, v in r.items() if k != "adjustment"}}))
'
