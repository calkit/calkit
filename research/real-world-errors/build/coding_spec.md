<!-- TODO: needs human review -->

# Shared coding spec for the error dataset parts

Write your part as a CSV with Python's csv module (QUOTE_MINIMAL, UTF-8), with
exactly this header:

id,citation,doi,field,year,source,source_url,selection,error_type,stage_introduced,impact,how_found,package_available,notes,confidence

- id: `<PREFIX>-<number>` per paper; if a paper has several distinct errors,
  one row per error with suffixes `-a`, `-b`, ... Prefixes: `I4R-<DP number>`,
  `RW-<Retraction Watch Record ID>`, `KN-<n>`.
- citation: original (audited) paper, short form "Authors (year). Title. Journal."
- doi: original paper DOI (blank if none found).
- field: e.g., economics, political science, psychology, medicine, biology,
  ecology, ML/genomics, etc.
- year: publication year of the original paper.
- source: short name of where the error was documented
  (e.g., "I4R DP 123 (Smith et al. 2024)", "Retraction notice, J Foo 2023").
- source_url: a URL for that document (required, every row).
- selection: sampling route, one of `i4r_block_111_180`, `rw_random_seed20261127`,
  `kapoor_narayanan_first_per_field`.
- error_type, one of: transcription, stale_result, sentinel_or_missing_code,
  unit_or_conversion, merge_or_join, duplicate_rows, recode_error,
  wrong_variable, sample_filter, spec_mismatch, inference, leakage,
  environment, missing_step, other, plus two added types:
  `none_found` (audit found no coding/data error; robustness fragility or
  disagreement over defensible choices goes in notes) and `unspecified`
  (an error was admitted/found but the mechanism isn't stated).
  Use `other` only for a stated mechanism the list lacks, and describe it.
  Disagreement over a defensible modeling choice is not an error
  (`none_found`), unless the auditor shows the choice is wrong, e.g.,
  clustering at the wrong level (inference), proxy measures something else
  (wrong_variable).
- stage_introduced: data collection, import, cleaning, merge, transformation,
  modeling, inference, figure, writing; `n/a` for none_found; `unknown` if
  not determinable.
- impact: changed (a conclusion reversed or no longer supported), weakened
  (magnitude or significance materially reduced, conclusion survives),
  none (no material effect), unclear. Judge against the paper's main
  conclusions, as the auditor (and any author reply) describes.
  A retraction for an error normally means changed, unless the notice says
  conclusions stand.
- how_found: semicolon-separated from: reran_code, read_code,
  profiled_data, compared_text_to_output, rederived_from_raw,
  domain_knowledge, new_data, reanalysis_alt_spec, author_self_check,
  reader_report, unknown.
- package_available: yes, partial, no, unknown (were code and data public).
- notes: one or two sentences, paraphrased (never copy source text).
- confidence: high, medium, low (in your coding).

Don't download replication packages, sign up, or contact anyone.
Fetch abstracts and the papers/notices themselves (HTML or PDF) as needed.

## Agent-era sample (added)

Agent-era parts add a final column `era` = `agent` (human parts get `human`
at merge). Header for agent parts:

id,citation,doi,field,year,source,source_url,selection,error_type,stage_introduced,impact,how_found,package_available,notes,confidence,era

- Unit: one documented error instance made by an AI agent doing research or
  data analysis (a specific generated paper, report, analysis, or statement
  class an evaluation documents). citation = the agent output audited (e.g.,
  "AI Scientist v2 generated paper 'X'") or, if no specific output is named,
  the system plus the evaluation, e.g., "Kosmos run reports (Edison 2025)".
  doi/year refer to the evaluation if the output has none.
- Aggregate statistics (e.g., accuracy by statement type) may be one row per
  error class with the counts in notes; say so in notes.
- Extra error types for this sample (use only when the base list doesn't
  fit): fabricated_result, fabricated_citation, scope_drift, overclaim,
  unrecorded_decision, reward_hacking, unrequested_change, stale_context,
  forking_paths_at_scale.
- impact: relative to the agent output's main conclusion/claim.
- package_available: whether the agent's code/logs/outputs were public.
- Verify every source exists and say what it reports; never invent a
  source, a number, or a case. If a suggested source can't be found, log it.
