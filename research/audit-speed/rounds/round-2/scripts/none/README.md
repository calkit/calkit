# Cognitive training trial: analysis

Data from the trial coordinator are in `data/raw/`; see `codebook.md`.
The corrected sessions export (2026-04-14) replaces the original one.

Packages: `requirements.txt`. To rerun:

```
python scripts/prepare_data.py --participants data/raw/participants.csv --sessions data/raw/sessions_2026-04-14_corrected.csv --out data/merged_final.csv
python scripts/fit_model.py --data data/merged_final.csv --adjustment ancova --out results/model_ancova.json
python scripts/fit_model.py --data data/merged_final.csv --adjustment change --out results/model_change.json
```

Then run `figures.ipynb` for Figure 1. Write-up: `report.md`.
