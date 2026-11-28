#!/usr/bin/env bash
# Build the none arm into <dest>: round 2's no-framework arm, a plain folder
# with no version control, scripts and a notebook run by hand, and report.md
# typed by hand. Replays round 2's history: a first pass on the original
# sessions export, whose merged table is left behind as data/merged.csv, then
# a rerun on the corrected export, after which the report's numbers were
# retyped, all but one. The same steps as round 2's build-none.sh, with the
# notebook's run times left out and every file given one time, so a rebuild
# gives the same bytes.
#
# Usage: build/build_none.sh <python> <generated data dir> <dest>
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$1" DATA="$2" PROJ="$3"
unset VIRTUAL_ENV PYTHONPATH
STATE="$(mktemp -d)"
trap 'rm -rf "$STATE"' EXIT
rm -rf "$PROJ"
mkdir -p "$PROJ"/{data/raw,scripts,results,figures}
cd "$PROJ"
source "$HERE/../versions.env"
cp "$HERE"/shared/{prepare_data,fit_model}.py scripts/
cp "$DATA/participants.csv" data/raw/participants.csv
cp "$DATA/sessions_v1.csv" data/raw/sessions_2026-03-02.csv
cp "$HERE/shared/codebook_v1.md" codebook.md
printf '%s\n' $PACKAGES $NOTEBOOK_PACKAGES > requirements.txt
# First pass, on the original export
"$PY" -W ignore scripts/prepare_data.py --participants data/raw/participants.csv \
  --sessions data/raw/sessions_2026-03-02.csv --out data/merged.csv
for adj in ancova change; do
  "$PY" -W ignore scripts/fit_model.py --data data/merged.csv \
    --adjustment "$adj" --out "results/model_$adj.json" > /dev/null
done
# Corrected export arrives; rerun into new files and overwrite the results
cp "$DATA/sessions_v2.csv" data/raw/sessions_2026-04-14_corrected.csv
cp "$HERE/shared/codebook.md" codebook.md
"$PY" -W ignore scripts/prepare_data.py --participants data/raw/participants.csv \
  --sessions data/raw/sessions_2026-04-14_corrected.csv --out data/merged_final.csv
for adj in ancova change; do
  "$PY" -W ignore scripts/fit_model.py --data data/merged_final.csv \
    --adjustment "$adj" --out "results/model_$adj.json" > /dev/null
done
# Figure from the notebook, executed in place so its outputs are saved, with
# Jupyter's and IPython's state kept out of the real home directory
"$PY" "$HERE/none/write_notebook.py" figures.ipynb
# Matplotlib's font cache, built first so the notebook's output doesn't say so
MPLCONFIGDIR="$STATE/mplconfig" "$PY" -c "import matplotlib.pyplot"
HOME="$STATE" JUPYTER_DATA_DIR="$STATE/jupyter-data" \
  "$PY" -m ipykernel install --user --name python3 \
  --display-name "Python 3 (ipykernel)" > /dev/null
HOME="$STATE" JUPYTER_DATA_DIR="$STATE/jupyter-data" \
  JUPYTER_CONFIG_DIR="$STATE/jupyter-config" \
  JUPYTER_RUNTIME_DIR="$STATE/jupyter-runtime" IPYTHONDIR="$STATE/ipython" \
  MPLCONFIGDIR="$STATE/mplconfig" \
  "$PY" -m jupyter nbconvert --to notebook --execute --inplace figures.ipynb \
  --ExecutePreprocessor.kernel_name=python3 \
  --ExecutePreprocessor.record_timing=False
# Typed by hand from results/*.json; item 3's training mean is left from the
# first pass
cp "$HERE/none/report.md" report.md
cp "$HERE/none/README.md" README.md
find . -name __pycache__ -prune -exec rm -rf {} +
# The day of the rerun, for every file and folder
find . -exec touch -h -t 202604141200.00 {} +
