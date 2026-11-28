# Round 2 answer key (do not show to auditors)

Study: a randomized trial of 12-week computerized cognitive training in
older adults, 480 enrolled at four sites (A 150, B 152, C 142, D 36).
Raw data come from `audit-compare-r2/scripts/generate_data.py` (seed
20261127), which isn't in any arm. Every arm's report has the same Methods
text and eight numbered results; the auditors audit those.

Values below are computed by `round-2-compute-key.py` (next to this file),
which runs the shared scripts and patched copies on freshly generated data
and writes every variant to `round-2-key-values.json`.
The as-built reports were rendered by `round-2-canonical/run.sh`.

## Bug 1: silent row loss in the merge (all four arms, identical code)

Site D's tablet app exports `participant_id` without zero padding
(`D-7`, `D-36`) while the enrollment file pads (`D-007`, `D-036`), as the
codebook documents ("Site letter and three-digit number, e.g., `A-014`").
`prepare_data.py` normalizes only case and whitespace:

```python
# lines 22-24
for df in (participants, sessions):
    df["participant_id"] = df["participant_id"].str.strip().str.upper()
# lines 32-34
df = participants.merge(
    scores.reset_index(), on="participant_id", how="inner"
)
```

so the inner join drops all 36 site D participants (7.5% of enrollment).
The next line's legitimate `dropna(subset=["score_w0", "score_w12"])` hides
the loss among real exclusions. Nothing reports enrolled N or a per-site
count; the Methods says "recruited at four community centers" and "The
analysis sample comprises participants with a scored baseline and week-12
assessment", both true as statements of intent.

Exclusions, correct: 480 enrolled; 3 outside ages 60–85 (A-091 87, C-002 59,
C-135 58); 48 without a scored baseline and week-12 assessment; 429
analyzed (A 129, B 143, C 123, D 34). As built: 395 analyzed, no site D;
the 34 eligible, complete site D participants are lost (7.9% of the correct
sample). Site D's training effect is larger in the generator (7.0 vs. 3.0
points), so the loss lowers the effect estimate.

How to find it: count rows in and out of each step (480 → 477 → 395), or
anti-join the files' IDs (36 session IDs match no participant), or
tabulate sites in the analysis table (no D).

## Bug 2: wrong reference level for education (all four arms, identical code)

The report says education is modeled "with secondary as the reference
category". `prepare_data.py` lines 37–40 make `education` a
`pd.Categorical` with levels `["secondary", "college", "graduate"]`, but
it's written to CSV, which drops the level order. `fit_model.py` reads the
CSV and uses `C(education)` (lines 12 and 14), so patsy takes levels in
alphabetical order and the reference is **college**. Line 30 reads
`C(education)[T.graduate]` and saves it as `graduate_vs_secondary`; it is
graduate vs. college.

How to find it: refit with `C(education, Treatment('secondary'))`, or note
the fit has a `C(education)[T.secondary]` term, or compare group means.

## Bug 3: stale typed number (none, ASTRA, OpenResearch; not Calkit)

History in every arm: the first analysis used the original sessions export
(2026-03-02), which scored week-12 form B sessions with the wrong answer key
(2.5 points low, 225 sessions); the corrected export (2026-04-14) replaced
it, as the codebook's last paragraph says. After rerunning, every typed
number was updated except result 3's training-group week-12 mean:

> 3. Mean week-12 score was **57.4** in the training group and 54.3 in the
> control group.

The current output says **58.6** (`w12_mean_training` = 58.6242); 57.4
(57.4129) is the value from the original export. The control mean, 54.3,
was updated (it was 52.9).

| Arm          | Where the stale 57.4 is typed |
| ------------ | ----------------------------- |
| none         | `none/report.md`, result 3 |
| Calkit       | Nowhere: prevented by construction. The report is `results/report.md`, written by stage `write-report` from `results/model-ancova.json` and `results/model-change.json` through `report_template.md`; the question answers in `calkit.yaml` use `{name}` placeholders filled from the same files. After the corrected export, `calkit run` regenerated both, with nothing retyped. |
| ASTRA        | `astra/astra.yaml`, `findings.week12_means.claim`, shown in the report page `astra/index.md` by `:::{astra} findings.week12_means`. Its evidence `source_commit` was refreshed to the rematerialized commit, so it looks current. |
| OpenResearch | The report `openresearch/orx-data/files/cognitive-training/cognitive-training/report.md`, result 3, and the notes (description) of experiment "Corrected sessions export" (`orx exp desc 8aef98ff-7b04-478b-bee3-3f4617e957cb`). The Baseline node's notes and run hold the 57.4 it came from. |

How to find it: compare each reported number with the current output, e.g.,
`w12_mean_training` in the model results.

Fairness note on bug 3: it is planted where each tool, used as intended,
has numbers typed by hand. ASTRA's findings and OpenResearch's notes and
artifacts reports are free text by design (lc's report template says never
hard-type a measured value in index.md, but the findings it embeds are
typed). Calkit's conventions template answers from results and generate
reports in a stage, so a Calkit project built as intended has no typed
number to go stale. A Calkit user could still type numbers into a report or
answer; this round tests the intended workflow, not misuse.

## Effect on the report's claims

Corrected = both computational bugs fixed (site D IDs padded, secondary as
reference). Bug 3 is corrected separately: result 3's 57.4 should read 58.6
as built, 58.8 fully corrected. Columns for one fix at a time are in
`round-2-key-values.json`.

| Result | As reported | Bug 1 fixed only | Bug 2 fixed only | Both fixed |
| --- | --- | --- | --- | --- |
| 1. N analyzed | **395** | 429 | 395 | **429** |
| 1. Mean age; % women | 72.9; 63% | 73.0; 63% | 72.9; 63% | 73.0; 63% |
| 2. Baseline mean, training / control | 52.0 / 51.4 | 51.9 / 51.3 | 52.0 / 51.4 | 51.9 / 51.3 |
| 3. Week-12 mean, training / control | **57.4** (stale; current 58.6) / 54.3 | 58.8 / 54.1 | 58.6 / 54.3 | **58.8** / 54.1 |
| 4. Training effect, ANCOVA (95% CI) | **3.93 (2.89 to 4.96)** | 4.29 (3.30 to 5.28) | 3.93 (2.89 to 4.96) | **4.29 (3.30 to 5.28)** |
| 5. Training effect, change score (95% CI) | **3.76 (2.67 to 4.86)** | 4.11 (3.06 to 5.16) | 3.76 (2.67 to 4.86) | **4.11 (3.06 to 5.16)** |
| 6. Graduate vs. secondary (95% CI; p) | **2.84 (1.50 to 4.17; p < 0.001)** | 2.80 (1.49 to 4.12) | 4.90 (3.57 to 6.22) | **4.53 (3.26 to 5.80; p < 0.001)** |
| 7. Age per 10 years (95% CI) | **-1.53 (-2.22 to -0.84)** | -1.44 (-2.10 to -0.78) | -1.53 (-2.22 to -0.84) | **-1.44 (-2.10 to -0.78)** |
| 8. R² | **0.671 (67.1%)** | 0.673 | 0.671 | **0.673 (67.3%)** |

All p-values for results 4–6 are below 0.001 either way. Bug 2 changes only
result 6 (and the change-score model's education term, which isn't
reported: 2.14 as built vs. 3.55 fixed). Bug 1 changes N by 34, the
training effects by about 0.35 points, and the other numbers slightly
(result 6 barely, 2.84 to 2.80).

Generator truth: training effect at week 12 of 3.0 points at sites A–C and
7.0 at D; education adds 1.5 (college) and 4.0 (graduate) points at
baseline and a further 2.5 and 4.5 points of gain by week 12, relative to
secondary; noise SD 4 per session, person SD 7.

## Where the bugs live in each arm

The shared scripts are byte-identical copies of
`audit-compare-r2/shared/prepare_data.py` (sha256 7347789d…) and
`fit_model.py` (sha256 26300549…), so the line numbers above hold.

| Arm | Bug 1 and 2 code | Analysis table (shows the loss) |
| --- | --- | --- |
| none | `none/scripts/prepare_data.py`, `none/scripts/fit_model.py` | `none/data/merged_final.csv` (and `data/merged.csv`, from the original export) |
| Calkit | `calkit/scripts/prepare_data.py` (stage `prepare-data`), `calkit/scripts/fit_model.py` (stage `fit-model`, iterated over `adjustment`) | `calkit/data/analysis.csv` (DVC) |
| ASTRA | `astra/src/prepare_data.py` (output `analysis_data`), `astra/src/fit_model.py` (output `model_results`, decision `adjustment`) | `astra/results/<universe>/analysis_data.csv` |
| OpenResearch | `scripts/prepare_data.py` and `scripts/fit_model.py` on branches `orx/baseline`, `orx/corrected-sessions-export`, `orx/change-score` of `openresearch/project` (not on `main`); each run's copy in `openresearch/orx-data/local-runs/<run id>/repo/scripts/` | `openresearch/orx-data/local-runs/<run id>/repo/data/analysis.csv` |

## Expected clues and non-clues

- The codebook in every arm documents the ID format and the correction.
- Every arm keeps the original export's results somewhere: none in
  `data/merged.csv` (results overwritten), Calkit and ASTRA in Git history,
  OpenResearch in the Baseline node's run and notes.
- No arm records row counts per step automatically; ASTRA's manifests and
  Calkit's `dvc.lock` record hashes, OpenResearch's run log records output
  printed by the scripts (fit_model.py prints the results JSON, which
  includes `n_analyzed`).
