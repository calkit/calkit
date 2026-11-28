<!-- TODO: needs human review -->

# Research

Product research for Calkit:
what would get researchers to adopt it,
which problems in an analysis change its conclusions, who finds them,
and what would catch them.
An automatic data profile at every stage boundary catches the data
problems auditors skip,
but documented errors suggest those are a small share of what changes
conclusions;
most are modeling choices found by people with domain knowledge.
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

<!-- TODO: needs human review -->

## Real-world errors

Documented errors in published research and in research made by AI
agents, coded from public notices and reports,
to see which kinds change conclusions and who finds them.

- `real-world-errors/errors.csv`: 316 errors in three samples that must
  not be pooled: human-era general research (I4R replication reports,
  Retraction Watch, Kapoor & Narayanan's leakage list), computational
  physics and engineering errata (`field_group`), and agent-made research
  (`era` is `agent`)
- `real-world-errors/README.md`: columns, sampling, taxonomy, coding
  rules, base rates for stale numbers, and limitations
- `real-world-errors/build/`: the coding spec, per-route logs,
  and the script that merged the coders' parts, kept as a record
- `scripts/summarize-real-world-errors.py`: counts by sample, error type,
  and impact, weighted changed 3, weakened 1, unclear 0.5, none 0,
  and the share of weighted impact a data profile could catch
  (sentinel codes, merges, and duplicate rows,
  and separately with unit errors)
- `results/real-world-errors.json` and `.md`: those counts

<!-- TODO: needs human review -->

## Agent reliability

Whether coding agents change a research project more reliably when it's a
Calkit project than when it's a plain folder, a Makefile project, or a
messy one, by trials of one agent on one task in a fresh copy of each
arm's project, graded by deterministic checks.

- `agent-reliability/README.md`: the arms, tasks, graders, and how to run a
  batch
- `agent-reliability/templates.tar.gz`: each arm's starting project, built
  by a stage that replays one research history, with Calkit pinned by
  commit in `calkit.yaml`, and checked to rebuild byte for byte
- `agent-reliability/runs/batch-<n>/`: each trial as the agent left it;
  batches 1 and 2 ran before the benchmark moved here and are archived by
  frozen import stages, and later batches run by frozen trial stages from
  `agent-reliability/batches/batch-<n>.csv`
- `agent-reliability/grades/batch-<n>/`: every trial graded by the current
  graders, so a grader fix regrades without rerunning agents
- `agent-reliability/interventions/`: guidance to check results, which
  batch 3 gives one Calkit arm through its agent plugin's skill and one
  Makefile arm through its README
- `results/agent-reliability.json` and `.md`: passes by arm and task, cost
  and time, unprompted mentions of the site the merge drops and of a new
  site's repeated records, the guidance's effect on them, and tool inputs
  that reached outside a trial's folder

<!-- TODO: needs human review -->

## Adoption

Whether question-driven development with a coding agent is what gets
researchers to adopt Calkit, not yet tested.

- `adoption/workshop-protocol.md`: how to test it at a workshop,
  against figures that update themselves, installable research,
  and running on a cluster from a laptop
