# Cognitive training trial: analysis

Data from the trial coordinator are in `data/raw/`; see `codebook.md`.
The manuscript is `report_template.md`, which `make` fills in with the
results to write `results/report.md`.

## Running

The packages are pinned in `requirements.txt` (Python 3.12):

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then run the whole analysis with:

```
make
```

Use `make PYTHON=.venv/bin/python` if that environment isn't active.
`make` reruns only the steps whose inputs changed:

1. `scripts/prepare_data.py` merges the raw files into `data/analysis.csv`,
   keeping participants in the eligible ages set in `scripts/utils.py`.
2. `scripts/fit_model.py` fits the ANCOVA and change-score models into
   `results/model-ancova.json` and `results/model-change.json`.
3. `scripts/make_figure.py` makes Figure 1, `results/score_by_week.png`.
4. `scripts/write_report.py` writes the report, `results/report.md`, from
   `report_template.md` and the results.

Edit the report's text in `report_template.md`, not `results/report.md`,
which `make` overwrites. `data/analysis.csv` is committed so collaborators
can use the analysis table without rerunning.
