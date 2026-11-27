<!-- TODO: needs human review -->

# Research

Studies of claims about Calkit as a product,
e.g., how fast an agent can audit an analysis built with it,
compared with other tools.
Unlike `decisions`, whose stages each record one decision and are frozen
once run, a study here runs in rounds, and each round adds to the record.

## Audit speed

How fast an agent can audit a claim in an agent-made analysis built with
Calkit, Lightcone's ASTRA, or alphaXiv's OpenResearch.

- `audit-speed/shared/`: the analysis each tool's project is built from,
  with a planted bug
- `audit-speed/KEY.md`: the bug and the corrected values,
  computed by `audit-speed/scripts/compute_key_values.py`
- `audit-speed/scripts/`: how round 1's projects were built,
  with tool versions in `versions.env`;
  a record of what was run, not pipeline stages, so nothing reruns it
- `audit-speed/rounds/round-<n>/results.json`: each round's audits by tool
- `results/audit-speed.md`: every round's audits in one table,
  made by the pipeline

To add a round, put its results in
`audit-speed/rounds/round-<n>/results.json`, run `calkit run`,
and update the question's answer in `calkit.yaml`.
