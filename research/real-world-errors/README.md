# Errors in research data analysis: a coded sample

<!-- TODO: needs human review -->

`errors.csv` codes documented errors in published research analyses,
one row per distinct error, to judge which tool features would prevent or
catch the errors that matter most.
A paper with several distinct errors has several rows
(ids ending `-a`, `-b`, ...).
Audits that found no error get one `none_found` row,
so base rates can be read off the I4R route.

The file holds three samples, kept apart by columns:

- `era` = `human`, `field_group` = `general`: 175 rows, 136 papers,
  from I4R replication reports, Retraction Watch, and Kapoor & Narayanan's
  leakage list.
- `era` = `human`, `field_group` = `computational_physics_engineering`:
  71 rows from errata in simulation-heavy physics and engineering journals.
- `era` = `agent`: 70 rows of errors made by AI agents doing research or
  data analysis, from published evaluations and incidents.

Never pool the three samples, or the routes within them, into one rate:
each route has its own selection bias (see Limitations).

## Columns

| Column                             | Meaning                                                                                                                                                                                                                                     |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                               | `I4R-<DP>`, `RW-<Retraction Watch record>`, `KN-<n>`, `CPE-<n>`, `AG-<source>-<n>`; suffix `-a`, `-b` for several errors in one paper                                                                                                       |
| `citation`, `doi`, `field`, `year` | The paper (or agent output) that contains the error                                                                                                                                                                                         |
| `source`, `source_url`             | Where the error was documented; every row has a URL                                                                                                                                                                                         |
| `selection`                        | Sampling route (below)                                                                                                                                                                                                                      |
| `error_type`                       | Taxonomy below                                                                                                                                                                                                                              |
| `stage_introduced`                 | data collection, import, cleaning, merge, transformation, modeling, inference, figure, writing; `n/a` for `none_found`; `unknown`                                                                                                           |
| `impact`                           | `changed`, `weakened`, `none`, `unclear`                                                                                                                                                                                                    |
| `how_found`                        | Semicolon-separated: `reran_code`, `read_code`, `profiled_data`, `compared_text_to_output`, `rederived_from_raw`, `domain_knowledge`, `new_data`, `reanalysis_alt_spec`, `author_self_check`, `reader_report`, `reference_check`, `unknown` |
| `package_available`                | Were code and data public: `yes`, `partial`, `no`, `unknown`                                                                                                                                                                                |
| `notes`                            | One or two paraphrased sentences                                                                                                                                                                                                            |
| `confidence`                       | Confidence in the coding: `high`, `medium`, `low`                                                                                                                                                                                           |
| `mismatch_cause`                   | For rows where a number, table, or figure disagreed with what the analysis produces: `stale`, `typo`, or `unclear`; blank otherwise                                                                                                         |
| `field_group`                      | `general`, `computational_physics_engineering`, or `agent`                                                                                                                                                                                  |
| `era`                              | `human` or `agent`                                                                                                                                                                                                                          |

## Sources and sampling

### I4R discussion papers (`i4r_block_111_180`)

All 70 Institute for Replication discussion papers numbered 111-180
(listing: https://econpapers.repec.org/paper/zbwi4rdps/), each read from
its IDEAS abstract and, where needed, the EconStor PDF.
60 audit a specific paper and are coded (86 rows);
10 are skipped: four author responses (117, 150, 159, 179), used only to
inform the impact of the comment they answer, and six meta, methods, or
multi-paper papers (123, 124, 125, 136, 141, 143).
DP 124's per-paper reports are DPs 130-134, which are coded.
One paper (Liu, Shamdasani, and Taraz 2023) is audited twice
(I4R-162, I4R-180).
30 of the 60 papers have no error at all, and only 5 have an error that
changed or weakened a result.

### Retraction Watch (`rw_random_seed20261127`)

Frame: the Retraction Watch database as published through Crossref
(https://gitlab.com/crossref/retraction-watch-data, downloaded
2026-11-27, 74,173 records).
Kept retractions and corrections dated 2022-2025 whose reasons include
"Error in Analyses" or "Error in Data" and none of the misconduct-type
reasons (paper mill, fabrication, plagiarism, misconduct, compromised
peer review, computer-generated content, image manipulation or
duplication, rogue editor, third-party involvement): 543 records.
Drew 60 with `random.seed(20261127); random.sample(frame, 60)`.
4 were excluded as image duplication with no data or analysis mechanism;
56 papers are coded (65 rows).
18 notices could not be read (publisher sites block automated access);
they are kept as `unspecified`, impact `unclear`, low confidence, with the
database's reason labels in notes, so the sample isn't biased toward
readable publishers.
`source_url` is the notice's DOI link.

### Kapoor & Narayanan leakage list (`kapoor_narayanan_first_per_field`)

Frame: the 41-row table of fields with leakage at
https://reproducible.cs.princeton.edu/ (30 distinct fields), from
Kapoor and Narayanan, "Leakage and the reproducibility crisis in
machine-learning-based science", Patterns 2023
(https://doi.org/10.1016/j.patter.2023.100804).
Rule: for each field, in table order, the first paper the field's cited
source names as affected, falling through to the field's next source if
none.
Political science is their own civil-war case study, so all four papers
they reran are included.
17 fields yield 20 papers (24 rows); 13 fields named no specific paper in
accessible text.

### Computational physics and engineering errata (`cpe_errata_census_seed20261127_*`)

Frame: 397 errata and corrigenda dated 2018-2025 listed by Crossref for
10 journals fixed in advance: J. Fluid Mech., J. Climate, Phys. Rev. E,
Phys. Rev. Fluids, AIAA J., Applied Energy, J. Comput. Phys.,
Geosci. Model Dev. (widened to 2008, since it now corrects articles in
place), Computers & Structures, and JAMES (none found).
All 177 readable notices were screened (a census of the readable frame,
not a sample).
71 (40%) cite a code bug, numerical error, unit or processing error,
methods-code mismatch, or wrong reported values and are coded;
the other 106 were mostly equation or derivation typos that didn't feed
computed results, authorship, funding, or reference fixes, and publisher
production errors.
A seeded subset of 40 (`..._first40`) can be used where a 40-case
stratum is wanted; the rest are `..._overflow`.
APS, AIAA, and Elsevier pages block automated fetches, so their notices
were read from index abstracts when available; J. Fluid Mech. (31) and
J. Climate (18) dominate the kept cases.

### Agent era (`agent_*`)

Every distinct, specific error each source documents, in the order the
source presents it, capped at about 12 per source:

- The AI Scientist v1 and v2, as disclosed by Sakana
  (arXiv 2408.06292, 2504.08066).
- Critiques: Beel, Kan, and Baumgart (arXiv 2502.14297);
  Luo, Kasirzadeh, and Shah (arXiv 2509.08713), whose rows are induced
  failures in controlled experiments.
- Agents4Science 2025: the venue's published code audits of accepted
  papers (every paper rated critical, partial, or failed, plus one
  `none_found` row for those that passed) and the organizers' report
  (arXiv 2511.15534). OpenReview reviews could not be fetched.
- Kosmos (arXiv 2511.02824): expert accuracy by statement type, plus each
  specific error the paper describes.
- Google's ScientistOne Chain-of-Evidence audit of 75 papers from five
  systems (arXiv 2605.26340); numbers are Google's own, unreplicated.
- The survey "Autonomous Research Agents: A Survey of AI Scientists and
  the Verification Gap" (arXiv 2608.05179) and claim-level auditability
  work (arXiv 2602.13855).
- Incidents and benchmarks found by web search, taken in result order
  (queries logged): AutoResearchEval (arXiv 2608.14905), AI Village
  incidents, the Jr. AI Scientist risk report, Sakana's AI CUDA Engineer,
  and a retracted paper with fabricated references (human-written with AI
  assistance, not an autonomous agent).

12 agent rows are aggregates (e.g., Kosmos accuracy by statement type, a
share of papers with phantom citations), marked "Aggregate row" in notes
with counts; filter them out to count individual instances.
Agents4Science audit rows come from an unchecked AI auditor and are
medium or low confidence.
"Agent era" there means a paper with an AI first author; several were
largely human-led by their own disclosure.

## Taxonomy

Base types: `transcription` (number typed or copied wrong),
`stale_result` (text or figure from an older run), `sentinel_or_missing_code`,
`unit_or_conversion`, `merge_or_join`, `duplicate_rows`, `recode_error`,
`wrong_variable`, `sample_filter`, `spec_mismatch` (methods describe a
different model than was run), `inference`, `leakage`, `environment`,
`missing_step`, `other`.

Types added for the human-era samples:

- `none_found`: the audit found no coding or data error.
- `unspecified`: an error was admitted or found, but its mechanism isn't
  stated (most often an unreadable or terse retraction notice).
- `calculation_error`: a wrong formula, constant, boundary condition,
  weighting, or a code bug in a computation, e.g., a sign reversal in a
  solver, a miscalculated survey weight, fMRI volumes misaligned with
  events.
- `numerical_method`: insufficient resolution, precision, or convergence,
  or a scheme unsuited to the problem.
- `interpretation_error`: a measurement or result misread, e.g.,
  misassigned NMR peaks, a misidentified bacterial strain; found by domain
  knowledge and largely out of a pipeline tool's reach.
- `design_or_measurement`: a flaw in data collection or the experiment,
  e.g., an uncorrected satellite sensor changeover, a wrong primer, a
  miscalibrated accelerometer.
- `upstream_data_error`: an error in a third-party data source carried
  into the paper, e.g., a census provider's miscoded variable.

Types added for the agent-era sample: `fabricated_result` (numbers or
findings not produced by any run), `fabricated_citation`, `scope_drift`
(answers an adjacent question), `overclaim` (prose stronger than the
evidence, including synthesis errors), `unrecorded_decision` (an analysis
choice made silently), `reward_hacking` (e.g., editing tests or data
handling to make checks pass), `unrequested_change`, `stale_context`
(working from outdated outputs or assumptions), and
`forking_paths_at_scale` (many variants tried, one reported).
The base types are used where they fit, e.g., an agent tuning against the
task's own evaluator is `leakage`.

`other` remains for named mechanisms the list lacks, e.g., a reported N
from a different sample than the estimation, geocoding errors, a
string-numeric type mismatch that broke a merge, a wrong figure file.

## Coding rules

- **Impact** is judged against the paper's main conclusions, as the
  auditor and any author reply describe them.
  `changed`: a conclusion reversed or no longer supported;
  `weakened`: magnitude or significance materially reduced, conclusion
  survives; `none`; `unclear`.
  A retraction for an error counts as `changed` unless the notice says the
  conclusions stand; an erratum that says the conclusions stand is `none`
  even if a secondary claim changed (noted).
  Disputed critiques where the authors reply that results hold are
  `unclear` (e.g., I4R-116) or low-confidence `changed` (e.g., I4R-158-a).
- **Robustness is not an error.** Results that are fragile under other
  defensible specifications are `none_found` with the fragility in notes,
  unless the auditor shows the original choice was wrong, e.g., clustering
  at the wrong level (`inference`) or a proxy that measures something else
  (`wrong_variable`).
- **Stale versus typo.** Where a number, table, or figure disagreed with
  the analysis output, `stale_result` and `mismatch_cause` = `stale` only
  when the source says it came from an earlier run, version, dataset, or
  input; `transcription` and `typo` only when the source says it was
  mistyped or miscopied; otherwise `unspecified` (or the mechanism type)
  with `mismatch_cause` = `unclear`. No cause was guessed.
  A code bug that produced wrong outputs is coded by mechanism, not as a
  mismatch.
- Missing raw-to-clean code is `missing_step` only when the auditor
  stresses it, so it is undercounted.
- Every row was coded by an AI agent from public documents (abstracts,
  reports, notices, papers), not by rerunning anything; no replication
  package was downloaded.

## Summary

Weighted count: changed 3, weakened 1, none 0, unclear 0.5.

### Human era, general (I4R, Retraction Watch, Kapoor & Narayanan)

| Error type               | Changed | Weakened | None | Unclear | Weighted |
| ------------------------ | ------- | -------- | ---- | ------- | -------- |
| unspecified              | 14      | 0        | 4    | 17      | 50.5     |
| leakage                  | 8       | 3        | 0    | 9       | 31.5     |
| calculation_error        | 7       | 0        | 0    | 1       | 21.5     |
| interpretation_error     | 5       | 0        | 0    | 0       | 15       |
| design_or_measurement    | 4       | 0        | 0    | 0       | 12       |
| wrong_variable           | 3       | 1        | 0    | 1       | 10.5     |
| unit_or_conversion       | 3       | 0        | 0    | 0       | 9        |
| transcription            | 2       | 0        | 6    | 0       | 6        |
| inference                | 1       | 1        | 0    | 1       | 4.5      |
| sample_filter            | 1       | 0        | 1    | 1       | 3.5      |
| recode_error             | 1       | 0        | 3    | 1       | 3.5      |
| upstream_data_error      | 1       | 0        | 0    | 1       | 3.5      |
| other                    | 0       | 2        | 5    | 2       | 3        |
| spec_mismatch            | 1       | 0        | 7    | 0       | 3        |
| sentinel_or_missing_code | 0       | 0        | 2    | 3       | 1.5      |
| environment              | 0       | 1        | 5    | 0       | 1        |
| missing_step             | 0       | 0        | 12   | 2       | 1        |
| merge_or_join            | 0       | 1        | 0    | 0       | 1        |
| duplicate_rows           | 0       | 0        | 0    | 1       | 0.5      |
| none_found               | 0       | 0        | 30   | 0       | 0        |

Impact by route: I4R none 73, unclear 6, weakened 4, changed 3;
Retraction Watch changed 40, unclear 22, weakened 2, none 1;
Kapoor & Narayanan unclear 12, changed 8, weakened 3, none 1.

### Human era, computational physics and engineering

| Error type            | Changed | Weakened | None | Unclear | Weighted |
| --------------------- | ------- | -------- | ---- | ------- | -------- |
| calculation_error     | 5       | 0        | 16   | 4       | 17       |
| numerical_method      | 2       | 0        | 1    | 1       | 6.5      |
| unspecified           | 0       | 0        | 6    | 9       | 4.5      |
| spec_mismatch         | 1       | 0        | 4    | 2       | 4        |
| unit_or_conversion    | 1       | 0        | 6    | 2       | 4        |
| other                 | 0       | 0        | 1    | 3       | 1.5      |
| wrong_variable        | 0       | 0        | 1    | 1       | 0.5      |
| transcription         | 0       | 0        | 1    | 1       | 0.5      |
| design_or_measurement | 0       | 0        | 0    | 1       | 0.5      |
| sample_filter         | 0       | 0        | 1    | 0       | 0        |
| stale_result          | 0       | 0        | 1    | 0       | 0        |

20 of the 71 errata concern reported values or figures that disagreed
with the analysis: 1 stale (CPE-47, composite figures built from an
earlier event selection, no effect on conclusions), 2 typos, 17 cause not
stated.

### Agent era

| Error type             | Changed | Weakened | None | Unclear | Weighted |
| ---------------------- | ------- | -------- | ---- | ------- | -------- |
| spec_mismatch          | 8       | 1        | 1    | 1       | 25.5     |
| overclaim              | 2       | 1        | 0    | 6       | 10       |
| fabricated_result      | 2       | 1        | 1    | 3       | 8.5      |
| leakage                | 2       | 1        | 0    | 1       | 7.5      |
| reward_hacking         | 2       | 0        | 1    | 0       | 6        |
| unspecified            | 1       | 0        | 0    | 4       | 5        |
| other                  | 1       | 1        | 0    | 2       | 5        |
| unrecorded_decision    | 1       | 0        | 0    | 2       | 4        |
| wrong_variable         | 1       | 1        | 1    | 0       | 4        |
| stale_result           | 1       | 0        | 0    | 0       | 3        |
| merge_or_join          | 1       | 0        | 0    | 0       | 3        |
| recode_error           | 1       | 0        | 0    | 0       | 3        |
| missing_step           | 0       | 0        | 0    | 5       | 2.5      |
| forking_paths_at_scale | 0       | 1        | 0    | 2       | 2        |
| inference              | 0       | 1        | 0    | 0       | 1        |
| fabricated_citation    | 0       | 0        | 3    | 1       | 0.5      |
| scope_drift            | 0       | 0        | 0    | 1       | 0.5      |
| unrequested_change     | 0       | 0        | 2    | 0       | 0        |
| none_found             | 0       | 0        | 2    | 0       | 0        |

The one agent `stale_result` (AG-S-14) is an AI Scientist run that never
reran its k-fold baseline under the new setup, so the proposed method
looked better than is possible by design.

## Base rates for inconsistent and stale numbers

<!-- TODO: needs human review -->

These systematic studies measure how often published numbers disagree
with themselves or with a rerun of the analysis.
The question for this dataset is narrower:
how often a wrong number is _stale_, i.e., left over from an older run,
rather than a typo, and how often it changes a conclusion.
No study below measures staleness directly.

| Study                                         | Sample                                                                      | Inconsistent or non-reproducible                                                                     | Changed significance or conclusions                                                     | Stale vs typo?                                                                                                                                                                        |
| --------------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Bakker & Wicherts 2011                        | 281 psych articles (2 samples)                                              | ~18% of results misreported                                                                          | ~15% of articles (39/257) had a result whose significance flipped on recalculation      | Partly: asked 21 authors; one error traced to a former dataset version, others to typos, rounding, copy-paste                                                                         |
| Nuijten et al. 2016 (statcheck)               | 30,717 articles, 258,105 p-values, 8 psych journals 1985-2013               | 9.7% of p-values; 49.6% of NHST articles had ≥1                                                      | 1.4% of p-values, 12.9% of articles had ≥1 significance-changing inconsistency          | No (internal check only)                                                                                                                                                              |
| Nuijten & Wicherts 2024 (statcheck in review) | >7,000 articles, >147,000 statistics, 4 journals                            | Inconsistencies fell much faster where journals ran statcheck in review                              | Decision inconsistencies fell too (percentages not in abstract)                         | No                                                                                                                                                                                    |
| Brown & Heathers 2017 (GRIM)                  | 260 psych articles, 71 testable                                             | ~51% (36/71) had ≥1 impossible mean; 16 had several                                                  | 3 of 9 articles with data obtained needed extensive corrections                         | No (internal check only)                                                                                                                                                              |
| Hardwicke et al. 2018                         | 35 _Cognition_ articles with reusable data, 1,324 values                    | 64 values (5%) not reproducible within 10%; 13 articles not fully reproducible even with author help | No decision errors; conclusions not seriously affected                                  | Partly: 3 "original analysis" issues, one example being values not from the latest analysis version; most issues were unclear specification (30/57) or data files (10/57), typos 5/57 |
| Hardwicke et al. 2021                         | 25 _Psych Science_ open-data-badge articles, 789 values                     | 16 articles (64%) initially had a major discrepancy; 37 values (5%) remained                         | 3 decision errors; conclusions did not appear affected                                  | Partly: causes coded, mostly unclear reporting; typos and data-file errors rarer; many unidentified                                                                                   |
| Artner et al. 2021                            | 46 psych articles (2012), 232 key claims, raw data from authors             | 30% of claims not reproduced; 18 more only by deviating from methods                                 | 13 of 185 significant claims (7%) no longer significant                                 | No: lists rounding, labeling, typo, copy-paste, case-selection errors, but causes often unknowable; no stale category                                                                 |
| Obels et al. 2020                             | 62 psych Registered Reports, 36 with data and code                          | Main results reproduced for 21 of 36 (58%)                                                           | Not reported                                                                            | No                                                                                                                                                                                    |
| Crüwell et al. 2023                           | 14 articles, one _Psych Science_ issue (all open-data badges)               | 1 exactly and 3 essentially reproducible                                                             | Not reported                                                                            | No                                                                                                                                                                                    |
| Brodeur et al. 2024 (I4R DP 107)              | 110 econ and polisci papers                                                 | >85% computationally reproducible; ~25% had coding errors                                            | Not reported in abstract                                                                | No                                                                                                                                                                                    |
| Frank 2026 (AI audit, blog, preliminary)      | 79 papers from one lab, 58 empirical with code/data, >10,000 numbers        | 40 of 58 papers had ≥1 number off by >10% (~2% of numbers); 216 discrepancies                        | 10 crossed a significance threshold, mostly minor results; no major claim changed       | Partly: 60 of 216 judged typos; others missing seeds or reconstruction gaps; staleness not reported as a category                                                                     |
| Brierley et al. 2022                          | 184 bioRxiv/medRxiv preprints vs published versions                         | ~23% had substantive figure content added or removed                                                 | Major abstract conclusion change in 17.2% (COVID) and 7.2% (other); one reversed        | Version comparison, but changes reflect review and new data, not stale numbers                                                                                                        |
| Zeraatkar et al. 2022                         | COVID-19 trial preprints vs published reports, 60 meta-analytic comparisons | Few important differences in methods or results                                                      | 2 of 60 (3.3%) changed direction of effect conclusion; 9 (15%) changed certainty rating | Version comparison; doesn't separate staleness                                                                                                                                        |

Internal-consistency checks (statcheck, GRIM) find a number that
cannot be right, but not why it is wrong:
a typo, a copy-paste slip, and a value left over from an earlier run
look the same to them.
Rerun-based audits (Hardwicke, Artner, Obels, Crüwell, Frank) can say a
value doesn't match the shared data and code, but usually can't say
whether the paper was written from an older run, since the older run is
gone; they recover a cause only by asking authors, and many causes stay
unidentified.
Only two sources here document staleness at all, both anecdotally:
Bakker & Wicherts (one author traced an error to a former dataset
version) and Hardwicke et al. 2018 (one issue was values not from the
most recent analysis version).
Preprint-to-publication comparisons see numbers change between
versions, but those changes are mostly deliberate updates, not stale
leftovers.

Across studies, roughly half of psychology papers contain at least one
inconsistent number, about 5% of checked values don't reproduce, and
the share that flips a significance decision ranges from about 1% of
p-values (statcheck) to 7% of key claims (Artner);
audits that judged whole conclusions rarely found one overturned.
So a separate stale-versus-typo base rate doesn't exist in this
literature; measuring it would take version history, i.e., knowing
which run each number came from.

Not found: a systematic GRIMMER prevalence study (GRIMMER appears as a
method and in case-level critiques);
specific inconsistency percentages for Nuijten & Wicherts 2024 beyond
its abstract.

### Base-rate references

- Bakker, M., & Wicherts, J. M. (2011). The (mis)reporting of
  statistical results in psychology journals. _Behavior Research
  Methods_, 43, 666-678. https://doi.org/10.3758/s13428-011-0089-5
- Nuijten, M. B., Hartgerink, C. H. J., van Assen, M. A. L. M.,
  Epskamp, S., & Wicherts, J. M. (2016). The prevalence of statistical
  reporting errors in psychology (1985-2013). _Behavior Research
  Methods_, 48, 1205-1226. https://doi.org/10.3758/s13428-015-0664-2
- Nuijten, M. B., & Wicherts, J. M. (2024). Implementing statcheck
  during peer review is related to a steep decline in
  statistical-reporting inconsistencies. _AMPPS_, 7(2).
  https://doi.org/10.1177/25152459241258945
- Brown, N. J. L., & Heathers, J. A. J. (2017). The GRIM test: A simple
  technique detects numerous anomalies in the reporting of results in
  psychology. _Social Psychological and Personality Science_, 8(4),
  363-369. https://doi.org/10.1177/1948550616673876
  (preprint: https://peerj.com/preprints/2064)
- Hardwicke, T. E., et al. (2018). Data availability, reusability, and
  analytic reproducibility: Evaluating the impact of a mandatory open
  data policy at the journal _Cognition_. _Royal Society Open Science_,
  5, 180448. https://doi.org/10.1098/rsos.180448
- Hardwicke, T. E., et al. (2021). Analytic reproducibility in articles
  receiving open data badges at the journal _Psychological Science_.
  _Royal Society Open Science_, 8, 201494.
  https://doi.org/10.1098/rsos.201494
- Artner, R., et al. (2021). The reproducibility of statistical results
  in psychological research: An investigation using unpublished raw
  data. _Psychological Methods_, 26(5), 527-546.
  https://doi.org/10.1037/met0000365
- Obels, P., Lakens, D., Coles, N. A., Gottfried, J., & Green, S. A.
  (2020). Analysis of open data and computational reproducibility in
  Registered Reports in psychology. _AMPPS_, 3(2), 229-237.
  https://doi.org/10.1177/2515245920918872
- Crüwell, S., et al. (2023). What's in a badge? A computational
  reproducibility investigation of the open data badge policy in one
  issue of _Psychological Science_. _Psychological Science_, 34(4),
  512-522. https://doi.org/10.1177/09567976221140828
- Brodeur, A., et al. (2024). Mass reproducibility and replicability:
  A new hope. I4R Discussion Paper 107.
  https://ideas.repec.org/p/zbw/i4rdps/107.html
- Frank, M. C. (2026, November 10). An AI audit of my work's
  computational reproducibility. _Babies Learning Language_ (blog).
  https://babieslearninglanguage.blogspot.com/2026/11/an-ai-audit-of-my-works-computational.html
- Brierley, L., et al. (2022). Tracking changes between preprint
  posting and journal publication during a pandemic. _PLOS Biology_,
  20(2), e3001285. https://doi.org/10.1371/journal.pbio.3001285
- Zeraatkar, D., et al. (2022). Consistency of covid-19 trial preprints
  with published reports and impact for decision making: Retrospective
  review. _BMJ Medicine_, 1(1), e000309.
  https://doi.org/10.1136/bmjmed-2022-000309

## Near-misses are invisible here

<!-- TODO: needs human review -->

Every case in this dataset was published and then caught.
A stale figure or number that an author noticed and fixed before
submission, or that a coauthor or reviewer caught, leaves no public
record, so no published-error dataset can contain it.
This dataset therefore undercounts how often staleness nearly happens,
and the near-miss rate, not the published rate, is what a tool that
keeps outputs current would mostly reduce.
Measuring it would take version histories of manuscripts and outputs,
e.g., from a lab's own repositories, or a prospective study.

## Limitations

<!-- TODO: needs human review -->

- **Each route sees a different slice.**
  I4R audits are mostly economics and political science papers with
  public code and data in top journals, so they find many minor errors
  and few that change conclusions.
  Retractions select for errors severe enough to retract, so nearly all
  are `changed`; the frame excludes misconduct by construction and
  depends on Retraction Watch's reason labels.
  Kapoor & Narayanan's list selects for one error type (leakage).
  Errata select for what authors choose to correct, usually smaller
  errors; journals differ in whether they issue errata at all
  (GMD corrects in place).
  Pooling routes would mix these biases.
- **Mechanisms are often missing.**
  Retraction notices are terse; 31 of 65 RW rows are `unspecified`,
  18 of them because the notice could not be read.
  Many reported-value mismatches have no stated cause
  (`mismatch_cause` = `unclear`), so the stale-versus-typo split rests on
  very few cases: across all human rows, 1 stale, 6 typos, 25 unclear.
- **How errors were found reflects the route.**
  Changed-impact errors in the general human sample were mostly found by
  the authors themselves (28 of 51) or by readers (9), because most come
  from retractions; I4R errors were found by rerunning and reading code.
  The I4R route is the only one with a known base rate of audits that
  found nothing.
- **Fields.** Biomedicine dominates the retraction sample, economics the
  I4R block, ML the leakage list, and fluid mechanics and climate the
  errata stratum. Psychology appears mainly through the base-rate
  studies. Theses are absent: no systematic source of thesis errata was
  found.
- **Access.** Publisher bot blocking (Elsevier, Wiley, Taylor & Francis,
  APS, AIAA, ACS, Nature, RSNA) removed or thinned some journals and
  pushed some coding onto abstracts.
- **Coding.** All coding was done by AI agents from documents, with one
  coder per row and no double coding; `confidence` reflects that.
  Impact for disputed critiques depends on whose account is believed.
- **Agent era.** The sources are early, small, and mostly written by the
  systems' builders or by evaluators with a stake (e.g., Google auditing
  competitors with its own system); several rows are aggregates or
  induced failures, and the Agents4Science audits were made by an AI
  auditor no human checked.

Per-route logs (exclusions, screening, search queries) are in
`build/logs/`, with the coding spec the coders were given
(`build/coding_spec.md`) and the script that merged their parts into
`errors.csv` and applied the stale-versus-typo recodes (`build/merge.py`),
kept as a record:
the parts and downloaded notices aren't kept, so it doesn't rerun.
The `summarize-real-world-errors` stage tabulates `errors.csv` by sample
into `../results/real-world-errors.json` and `.md`.
