# Run the whole analysis, from raw data to the report: `make`
PYTHON ?= python

RAW := data/raw/participants.csv data/raw/sessions.csv
RESULTS := results/model-ancova.json results/model-change.json

all: results/report.md

data/analysis.csv: scripts/prepare_data.py scripts/utils.py $(RAW)
	$(PYTHON) scripts/prepare_data.py --participants data/raw/participants.csv \
		--sessions data/raw/sessions.csv --out $@

results/model-%.json: scripts/fit_model.py data/analysis.csv
	$(PYTHON) scripts/fit_model.py --data data/analysis.csv --adjustment $* \
		--out $@ > /dev/null

results/score_by_week.png: scripts/make_figure.py data/analysis.csv
	$(PYTHON) scripts/make_figure.py --data data/analysis.csv --out $@

# The report's numbers come from the results, so none are typed
results/report.md: scripts/write_report.py report_template.md $(RESULTS) \
		results/score_by_week.png
	$(PYTHON) scripts/write_report.py --primary results/model-ancova.json \
		--sensitivity results/model-change.json --template report_template.md \
		--figure score_by_week.png --out $@

clean:
	rm -f data/analysis.csv $(RESULTS) results/score_by_week.png \
		results/report.md

.PHONY: all clean
