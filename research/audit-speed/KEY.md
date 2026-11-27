# Answer key: planted error (do not show to auditors)

## The error

In `clean_data.py` (lines 23–24, identical in all three projects), SES codes
are mapped to categories with:

```python
df["ses"] = pd.cut(
    df["ses_code"], bins=[0, 1, 2, np.inf], labels=SES_LABELS
)
```

The raw data codes nonresponse as `ses_code = 9` (see `codebook.md`:
"9 = not reported"). The last bin `(2, inf]` puts code 9 into **"high"**.
Because nothing is ever NaN, the `--missing-ses drop` branch
(`df.dropna(subset=["ses"])`, line 27) drops nobody, even though the
report's Methods says "Participants with missing SES were excluded from the
analysis." This mirrors the published-audit error of coding missing SES as
high SES.

The 55 nonrespondents' true SES (from the generator) is 37 low, 16 middle,
2 high, so mostly low-SES participants are relabeled as high, which
attenuates the high-vs-low gap.

A side effect: the `category` option of the same flag gives identical
results, since no missing category ever appears.

## Where it lives in each project

| Project      | File                                                                                                         |
| ------------ | ------------------------------------------------------------------------------------------------------------ |
| Calkit       | `calkit/scripts/clean_data.py` (stage `clean-data`)                                                          |
| ASTRA        | `astra/src/clean_data.py` (output `participants_clean`, decision `missing_ses = drop`)                       |
| OpenResearch | `openresearch/project/scripts/clean_data.py` on branch `orx/baseline` (not on `main`); the run's copy is in `openresearch/orx-data/local-runs/<run id>/repo/scripts/clean_data.py` |

## Effect on the report's claims

Reported ("as built") vs. corrected (code 9 treated as missing and excluded,
as the Methods says). Computed by `scripts/compute_key_values.py`.

| Claim (report item)                          | As built                         | Corrected                         |
| -------------------------------------------- | -------------------------------- | --------------------------------- |
| 1. N analyzed                                | 300                              | 245                               |
| 1. Mean age                                  | 42.0                             | 42.2                              |
| 2. Mean outcome, treatment / control         | 58.3 / 54.8                      | 58.3 / 55.6                       |
| 3. Treatment effect (95% CI; p)              | 3.72 (1.82 to 5.63; p = 0.00015) | 3.07 (1.07 to 5.07; p = 0.0028)   |
| **4. High vs. low SES (95% CI; p)**          | **4.01 (1.57 to 6.45; p = 0.0014)** | **6.31 (3.71 to 8.92; p = 3.2e-06)** |
| 5. R²                                        | 0.073 (7.3%)                     | 0.110 (11.0%)                     |
| (not in report) Middle vs. low SES           | 2.56                             | 2.59                              |

The data-generating truth is a high-vs-low gap of 9.0 points and a
treatment effect of 5.0 points (N = 300, noise SD 8).

## Claim for auditors to verify

Report item 4 (also Calkit question 2's answer, ASTRA finding `ses_gap`,
and the OpenResearch experiment notes):

> Adjusting for condition, high-SES participants scored 4.01 points higher
> than low-SES participants (95% CI 1.57 to 6.45; p = 0.0014).

It reproduces exactly from the code and data, but understates the gap by
about 36% (4.01 vs. 6.31) because of the error above.
Observable clues: N = 300 equals the enrolled sample although the Methods
says missing-SES participants were excluded; the codebook's code 9.
