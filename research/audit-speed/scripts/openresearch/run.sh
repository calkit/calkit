#!/usr/bin/env bash
# Run the full analysis: data, cleaning, model, figure, and report.
set -euo pipefail
export PYTHONUNBUFFERED=1
report() { printf '::orx:: %s\n' "$1"; }
report '{"phase":"install"}'
uv sync --locked
report '{"phase":"analysis","step":0,"of":5,"unit":"steps"}'
uv run --locked python scripts/generate_data.py --out data/raw/participants.csv
report '{"step":1}'
uv run --locked python scripts/clean_data.py --raw data/raw/participants.csv \
  --out data/clean/participants.csv --missing-ses drop
report '{"step":2}'
uv run --locked python scripts/fit_model.py --clean data/clean/participants.csv \
  --out results/model.json
report '{"step":3}'
uv run --locked python scripts/make_figure.py --clean data/clean/participants.csv \
  --out results/outcome_by_ses.png
report '{"step":4}'
uv run --locked python scripts/write_report.py --results results/model.json \
  --template report_template.md --figure outcome_by_ses.png \
  --out results/report.md --missing-ses drop
report '{"step":5}'
cat results/model.json && echo
uv run --locked python -c '
import json
r = json.load(open("results/model.json"))
keys = ["n_analyzed", "treatment_effect", "treatment_p", "ses_high_vs_low",
        "ses_high_p", "r_squared"]
print("::orx:: " + json.dumps({"m": {k: r[k] for k in keys}}))
'
cat results/report.md
