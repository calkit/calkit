<!-- TODO: needs human review -->

# Research

Product research for Calkit:
which problems in an analysis change its conclusions but get past auditors,
and what would catch them.
So far it points to an automatic data profile recorded at every stage
boundary (rows in and out, values outside a column's usual pattern,
duplicate keys, missingness),
shown along the path a reader already takes from question to evidence to
stage.
Each question in `calkit.yaml` makes one step of that case,
with its answer filled in from the pipeline's results.

Unlike `decisions`, whose stages each record one decision and are frozen
once run, a study here runs in rounds, and each round adds to the record.

## Audit speed

Agent audits of a small agent-made analysis with planted bugs,
built with Calkit, Lightcone's ASTRA, alphaXiv's OpenResearch,
or, from round 2, no framework or version control.

- `audit-speed/shared/`: the analysis round 1's projects are built from,
  with a planted bug
- `audit-speed/KEY.md`: round 1's bug and corrected values,
  computed by `audit-speed/scripts/compute_key_values.py`
- `audit-speed/scripts/`: how round 1's projects were built,
  with tool versions in `versions.env`;
  a record of what was run, not pipeline stages, so nothing reruns it
- `audit-speed/rounds/round-<n>/results.json`: each round's audits by arm
- `audit-speed/rounds/round-2/`: subtler bugs, three audits per arm,
  with its own key and build scripts
- `audit-speed/rounds/round-3/`: round 2's projects audited at a person's
  reading speed, through `reader/hread.py`,
  which charges simulated time for every look at a project and stops at a
  budget;
  `results.json` holds the two cost settings, v1 and v2
  (`hread.py` is as run for v2),
  and `logs/<arm>-<n>.jsonl` each run's reading, n being 1 for v1, 2 for v2
- `results/audit-speed.md`: every round's audits in one table,
  made by the pipeline

To add a round, put its results in
`audit-speed/rounds/round-<n>/results.json`, run `calkit run`,
and update the questions' answers in `calkit.yaml`.

## Real packages

Agent audits of published replication packages with publicly documented
problems, and whether a generic data profile flags them.

- `real-packages/audits.json`: the audits, by package and run
- `real-packages/hill-roberts-2023/`: Hill & Roberts (2023)'s archive
  at Dataverse version 1.0, before its corrigendum,
  imported by the frozen `import-hill-roberts` stage,
  which checks the checksum Dataverse reports
  and saves the version's license (CC0 1.0) in `dataverse.json`
- `scripts/profile-data.py`: the profile, two generic rules per numeric
  column, run over every CSV it's given
- `results/hill-roberts-profile.json`: the archive's flags by file and
  column
- `results/real-packages.md`: every audit in one table
