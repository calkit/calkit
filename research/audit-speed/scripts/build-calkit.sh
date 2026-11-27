#!/usr/bin/env bash
# Build the Calkit version of the study in calkit/ from shared/, the way a
# coding agent following the calkit:conventions skill would: environment,
# question declared first, pipeline stages, run, then an answer citing evidence.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/versions.env"
unset VIRTUAL_ENV
# Calkit from this repo, which audit-speed is two levels inside
CALKIT_REPO="${CALKIT_REPO:-$(cd "$ROOT/../.." && pwd)}"
calkit() { uv run --project "$CALKIT_REPO" calkit "$@"; }
export GIT_AUTHOR_NAME="Audit Builder" GIT_AUTHOR_EMAIL="builder@example.org"
export GIT_COMMITTER_NAME="Audit Builder" GIT_COMMITTER_EMAIL="builder@example.org"
PROJ="$ROOT/calkit"
rm -rf "$PROJ" && mkdir -p "$PROJ/scripts"
cd "$PROJ"
git init -q -b main
calkit init
# Shared code and docs
cp "$ROOT"/shared/{generate_data,clean_data,fit_model,make_figure,write_report}.py scripts/
cp "$ROOT"/shared/{report_template,codebook}.md .
git add scripts report_template.md codebook.md
git commit -q -m "Add analysis scripts, report template, and codebook"
# Environment
calkit new uv-env -n main --python "$PYTHON_VERSION" \
  matplotlib==3.11.2 numpy==2.5.5 pandas==3.1.1 statsmodels==0.15.0
# Questions, declared before the analysis runs
calkit new question "Does the intervention raise outcome scores?" --commit
calkit update question 1 \
  --hypothesis "Treatment raises outcome scores relative to control." \
  --approach "Fit an OLS model of outcome on condition and SES category, excluding participants with missing SES."
calkit new question "How do outcome scores differ by socioeconomic status?" --commit
calkit update question 2 \
  --hypothesis "High-SES participants score higher than low-SES participants." \
  --approach "Compare the high-SES and low-SES coefficients of the same OLS model, which adjusts for condition."
git add calkit.yaml && git commit -q -m "Declare questions and approaches"
# Pipeline
calkit new python-script-stage -n generate-data -e main \
  -s scripts/generate_data.py \
  --arg=--out --arg=data/raw/participants.csv \
  -o data/raw/participants.csv --no-check --no-commit
calkit new python-script-stage -n clean-data -e main \
  -s scripts/clean_data.py \
  --arg=--raw --arg=data/raw/participants.csv \
  --arg=--out --arg=data/clean/participants.csv \
  --arg=--missing-ses --arg=drop \
  -i data/raw/participants.csv \
  -o data/clean/participants.csv --no-check --no-commit
calkit new python-script-stage -n fit-model -e main \
  -s scripts/fit_model.py \
  --arg=--clean --arg=data/clean/participants.csv \
  --arg=--out --arg=results/model.json \
  -i data/clean/participants.csv \
  --out-git results/model.json --no-check --no-commit
calkit new python-script-stage -n make-figure -e main \
  -s scripts/make_figure.py \
  --arg=--clean --arg=data/clean/participants.csv \
  --arg=--out --arg=results/outcome_by_ses.png \
  -i data/clean/participants.csv \
  --out-git results/outcome_by_ses.png --no-check --no-commit
calkit new python-script-stage -n write-report -e main \
  -s scripts/write_report.py \
  --arg=--results --arg=results/model.json \
  --arg=--template --arg=report_template.md \
  --arg=--figure --arg=outcome_by_ses.png \
  --arg=--out --arg=results/report.md \
  --arg=--missing-ses --arg=drop \
  -i results/model.json -i report_template.md -i results/outcome_by_ses.png \
  --out-git results/report.md --no-check --no-commit
git add -A && git commit -q -m "Add pipeline"
calkit run
calkit commit -m "Run pipeline"
# Answers citing the results as evidence
uv run --project "$CALKIT_REPO" python "$ROOT/scripts/calkit_add_answers.py" calkit.yaml
calkit check questions
git add -A && git commit -q -m "Answer questions with pipeline evidence"
git status --short
