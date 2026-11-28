#!/usr/bin/env bash
# Build the no-framework arm in none/: a plain folder, no version control,
# scripts and a notebook run by hand, and report.md typed by hand. Replays
# the history: a first pass on the original sessions export, whose merged
# table is left behind as data/merged.csv, then a rerun on the corrected
# export, after which the report's numbers were retyped, all but one.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/versions.env"
unset VIRTUAL_ENV
PROJ="$ROOT/none"
# The researcher's Python, outside the project folder
VENV="$ROOT/tools/none-venv"
if [ ! -x "$VENV/bin/python" ]; then
  uv venv -q --python-preference only-managed --python "$PYTHON_VERSION" "$VENV"
  # shellcheck disable=SC2086
  VIRTUAL_ENV="$VENV" uv pip install -q $PACKAGES $NOTEBOOK_PACKAGES
fi
PY="$VENV/bin/python"
if [ -d "$PROJ" ]; then rm -rf "$PROJ"; fi
mkdir -p "$PROJ"/{data/raw,scripts,results,figures}
cd "$PROJ"
cp "$ROOT"/shared/{prepare_data,fit_model}.py scripts/
cp "$ROOT/build-data/participants.csv" data/raw/participants.csv
cp "$ROOT/build-data/sessions_v1.csv" data/raw/sessions_2026-03-02.csv
cp "$ROOT/build-data/codebook_v1.md" codebook.md
printf '%s\n' $PACKAGES $NOTEBOOK_PACKAGES > requirements.txt
# First pass, on the original export
"$PY" -W ignore scripts/prepare_data.py --participants data/raw/participants.csv \
  --sessions data/raw/sessions_2026-03-02.csv --out data/merged.csv
for adj in ancova change; do
  "$PY" -W ignore scripts/fit_model.py --data data/merged.csv \
    --adjustment "$adj" --out "results/model_$adj.json" > /dev/null
done
# Corrected export arrives; rerun into new files and overwrite the results
cp "$ROOT/build-data/sessions_v2.csv" data/raw/sessions_2026-04-14_corrected.csv
cp "$ROOT/shared/codebook.md" codebook.md
"$PY" -W ignore scripts/prepare_data.py --participants data/raw/participants.csv \
  --sessions data/raw/sessions_2026-04-14_corrected.csv --out data/merged_final.csv
for adj in ancova change; do
  "$PY" -W ignore scripts/fit_model.py --data data/merged_final.csv \
    --adjustment "$adj" --out "results/model_$adj.json" > /dev/null
done
# Figure from the notebook, executed in place so its outputs are saved, with
# Jupyter's and IPython's state kept out of the real home directory
"$PY" "$ROOT/scripts/none/write_notebook.py" figures.ipynb
JHOME="$ROOT/tools/none-home"
mkdir -p "$JHOME"
HOME="$JHOME" JUPYTER_DATA_DIR="$JHOME/jupyter-data" \
  "$PY" -m ipykernel install --user --name python3 \
  --display-name "Python 3 (ipykernel)" > /dev/null
HOME="$JHOME" JUPYTER_DATA_DIR="$JHOME/jupyter-data" \
  JUPYTER_CONFIG_DIR="$JHOME/jupyter-config" \
  JUPYTER_RUNTIME_DIR="$JHOME/jupyter-runtime" IPYTHONDIR="$JHOME/ipython" \
  "$PY" -m jupyter nbconvert --to notebook --execute --inplace figures.ipynb \
  --ExecutePreprocessor.kernel_name=python3
# Typed by hand from results/*.json; item 3's training mean is left from the
# first pass
cp "$ROOT/scripts/none/report.md" report.md
cp "$ROOT/scripts/none/README.md" README.md
find . -name __pycache__ -prune -exec rm -rf {} +
find . -type f | sort
