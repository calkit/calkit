# Cognitive training trial: analysis

Data from the trial coordinator are in `data/raw/`; see `codebook.md`.
The manuscript is `report_template.md`, which the pipeline fills in with
the results to write `results/report.md`.

## Running

The environment is defined in `pyproject.toml` and locked in `uv.lock`.
Run the whole analysis with:

```
calkit run
```

`calkit run` reruns only the stages whose inputs changed, and creates the
environment if needed. The stages, defined in `calkit.yaml`, are:

1. `prepare-data` runs `scripts/prepare_data.py`, which merges the raw files
   into `data/analysis.csv`, keeping participants in the eligible ages set
   in `scripts/utils.py`.
2. `fit-model` runs `scripts/fit_model.py`, which fits the ANCOVA and
   change-score models into `results/model-ancova.json` and
   `results/model-change.json`.
3. `make-figure` runs `scripts/make_figure.py`, which makes Figure 1,
   `results/score_by_week.png`.
4. `write-report` runs `scripts/write_report.py`, which writes the report,
   `results/report.md`, from `report_template.md` and the results.

Edit the report's text in `report_template.md`, not `results/report.md`,
which `calkit run` overwrites.
The questions the analysis answers, and their answers, are in `calkit.yaml`.
