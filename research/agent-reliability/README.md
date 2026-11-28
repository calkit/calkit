# Agent reliability benchmark

Does a coding agent change a research project more reliably when the
project is a Calkit project than when it's set up some other way? Each trial
gives an agent one task in a fresh copy of one arm's template project, then
grades the project the agent leaves behind with deterministic Python. Run
it again after each Calkit change to see whether agents get more reliable.

The project is round 2's cognitive training trial (see
`../audit-speed/rounds/round-2/`): participants.csv merged with sessions.csv,
cleaning, an ANCOVA and a change-score model, a figure, and a report with
Methods and 8 numbered results. Its planted bugs (site D dropped by the
merge, education's reference level, the none arm's stale week-12 mean)
are part of the starting state here, not things to find, except where a
task names one.

## Pipeline

<!-- TODO: needs human review -->

Every result here is made by a stage in `../calkit.yaml`, from code in
this folder and the Calkit commit those stages pin, so nothing comes from
a command run by hand:

| Stage                                | What it makes                                                              |
| ------------------------------------ | -------------------------------------------------------------------------- |
| `build-agent-reliability-templates`  | `templates.tar.gz`, `templates.json`, and the files tasks hand agents      |
| `check-agent-reliability-templates`  | `templates-rebuild.json`: a second build, byte for byte the same           |
| `build-agent-reliability-reference`  | `reference/<task>/`: each task's reference end state                       |
| `verify-agent-reliability-graders`   | `verification/summary.json`, and each case's grade in `grades/`            |
| `import-agent-reliability-batch-<n>` | `runs/batch-<n>/`: batches 1 and 2, run before the move (frozen)           |
| `agent-reliability-batch-<n>`        | `runs/batch-<n>/`: a batch of trials from `batches/batch-<n>.csv` (frozen) |
| `grade-agent-reliability-batch-<n>`  | `grades/batch-<n>/`: every run of a batch, graded by the current graders   |
| `summarize-agent-reliability`        | `../results/agent-reliability.json` and `.md`                              |

The templates are one archive, rather than a folder, since they hold
nested Git repos. Every commit in them is the builder's
(`Research Builder`), times that would only say when the build ran are
fixed, and Calkit's record of each stage run is dated at its step in the
history, so a rebuild gives the same bytes. Trial stages are frozen, since
trials cost money, and graded by separate stages, so a grader fix regrades
every run without rerunning agents.

## Layout

| Path                          | What it is                                                      |
| ----------------------------- | --------------------------------------------------------------- |
| `templates.tar.gz`            | Every arm's starting project, `<arm>/` and `stale/<arm>/` (DVC) |
| `templates.json`              | Each template's Git head and file hashes                        |
| `incoming/`                   | Files a task hands the agent (task 4's file, site E's; DVC)     |
| `interventions/`              | The checking guidance and the patch that adds it to the plugin  |
| `tasks/*.txt`                 | Prompt for each task, the same in every arm                     |
| `preambles/*.txt`             | Per-arm preamble: where the project is, how to run Python       |
| `batches/batch-<n>.csv`       | A batch's trials: arm, task, rep, and model                     |
| `reference/<task>/`           | Reference end state: expected results, table, figure (DVC)      |
| `runs/batch-<n>/<run>/`       | Each trial as the agent left it (DVC)                           |
| `grades/batch-<n>/<run>.json` | Each trial's grade (DVC)                                        |
| `verification/`               | Grader verification: `summary.json`, each case's grade (DVC)    |
| `bench/new_run.py`            | Make a fresh run of one arm and task                            |
| `bench/run_batch.py`          | Run a batch's trials headlessly and archive them                |
| `bench/import_batch.py`       | Archive trials run before the move                              |
| `bench/grade.py`              | Grade a run, writing `<run>/grade.json`                         |
| `bench/regrade.py`            | Grade every archived run of a batch                             |
| `bench/summarize.py`          | Tally graded batches by arm and task                            |
| `bench/report.py`             | The report's 24 numbers, the abstract's, and how they're read   |
| `bench/arms.py`               | Per-arm adapter: where outputs live, how the arm runs           |
| `bench/archive.py`            | Deterministic archives of projects, keeping their times         |
| `bench/reference.py`          | Compute `reference/` from the generator                         |
| `bench/solutions.py`          | Reference solutions and flawed ones, to check graders           |
| `bench/verify.py`             | Grade templates, solutions, and flaws                           |
| `build/build_templates.sh`    | Build every template                                            |
| `build/build_none.sh`         | Build the none arm, as round 2 did                              |
| `build/build_history.py`      | Replay the research history into one arm                        |
| `build/history/`              | The analysis code, drafts, and documents at each point in it    |
| `build/make_site_e.py`        | Site E's exports and codebook, for add-site                     |
| `build/snapshot_calkit.sh`    | Pin Calkit and its agent plugin at a commit                     |
| `pyproject.toml`, `uv.lock`   | Python for the harness and graders                              |

## Arms

<!-- TODO: needs human review -->

Five arms, plus two from batch 3 that add guidance to check results
(below). `none` is round 2's plain folder. The other four, the history
arms, are built by replaying one research history (below) with the same
analysis decisions on the same dates, so they end at the same analysis as
`none`: the same table, results, figure, and report numbers. What differs
is how each keeps the history.

- `none`: round 2's plain folder, no Git. Scripts run by hand with the
  commands in the README, a notebook for the figure, and a hand-typed
  `report.md`. Both sessions exports are in `data/raw/`, and the first
  pass's merged table is left behind as `data/merged.csv`. Its report's
  result 3 has the stale week-12 training mean (57.4; results say 58.6).
  It has no submitted draft, so the history tasks don't apply.
- `messy`: the status quo, modeled on real replication packages and the
  errors in `research/real-world-errors/`. A flat folder, no Git, where
  the history lives only in copies, names, and modification times.
- `messy-git`: the same mess in Git, committed the way a casual Git user
  commits: terse messages, several changes per commit. It keeps the
  copies a Git user would still make (notebook copies, cached CSVs, named
  figures, the submitted draft) and not the ones Git replaces (the dated
  first draft, `prepare_data_old.py`). Tests whether version control alone
  helps.
- `make`: what a careful researcher would do without Calkit. Scripts in
  `scripts/`, a Makefile that runs everything (with `utils.py` as a
  prerequisite), `results/report.md` generated from `report_template.md`,
  so no report number is typed, pinned `requirements.txt`, one change per
  commit with descriptive messages, and the submission tagged
  `submitted`. `data/analysis.csv` is committed (see Known limitations).
- `calkit`: the same as `make`, but a Calkit pipeline in `calkit.yaml`
  instead of the Makefile, a uv environment, and three questions whose
  answers are templated from results. Its `.venv` isn't copied; Calkit
  recreates it on the first run.

`make` and `calkit` also get a careful researcher's cruft: an exploratory
notebook outside the pipeline (`notebooks/explore.ipynb`, run out of
order on the first pass's table), a response to reviewers, and a
conference abstract with the main result typed in. Without any, the Calkit
arm would be unrealistically tidy, and real Calkit projects are usually
adopted partway, around exploration that never enters the pipeline. They
don't get the messy arms' copies, since a Git user who keeps one change per
commit wouldn't make them; `make` gets exactly what `calkit` gets, so the
two differ only in the tool.

### Checking guidance

<!-- TODO: needs human review -->

Batches 1 and 2 found agents in the tidy arms (make, calkit, none) never
mentioned site D's dropped participants unless asked (0/38), against 9/22
in the messy arms, which had to investigate. Two arms test whether a few
sentences of guidance restore that, and whether it matters that Calkit
delivers them:

- `calkit-hint`: `calkit`'s template and pinned Calkit, but the agent
  plugin's `conventions` skill gets a "Checking results" section,
  `interventions/check-results.md`, applied to the snapshot's plugin by
  `interventions/conventions-check-results.patch` (`arms.patch_plugin`
  checks the patched skill holds the guidance's exact words).
- `make-hint`: `make`, with the same words at the end of its README from
  the first commit. It controls for the instruction itself: if make-hint
  matches calkit-hint, the effect is the instruction, and Calkit's part is
  only delivering it through the skill without anyone writing it into the
  project.

The guidance is general, saying nothing about this project:

```md
## Checking results

After running the pipeline, check that each stage's results are plausible
before reporting the work done, including results the task didn't ask
about. Compare the rows going into and out of each stage, e.g., rows lost
or added by a merge or filter, and which groups they came from. Check that
the analysis sample matches what the project's questions and the report's
Methods say it should be. Mention anything that doesn't add up, even if you
leave it as it is.
```

Both arms get their base arm's preamble and adapter, and are graded as it
is; each run's `meta.json` records the guidance's and patch's hashes. The
guidance, the patch, and the preambles are inputs of the build, trial, and
verify stages, so changing the guidance makes them stale.

### The research history

<!-- TODO: needs human review -->

| Date       | Step                                                            | State after                          |
| ---------- | --------------------------------------------------------------- | ------------------------------------ |
| 2026-03-02 | Original data arrive; first analysis (ANCOVA without education) | ages 60–80, original export, SE bars |
| 2026-03-04 | Exploratory notebook (make, calkit)                             |                                      |
| 2026-03-09 | First draft (effect 3.46)                                       |                                      |
| 2026-03-16 | Education added to both models                                  | effect 3.51                          |
| 2026-03-23 | Manuscript submitted                                            | N = 299, effect 3.51                 |
| 2026-04-14 | Corrected sessions export (week-12 form B rescored)             | effect 3.30                          |
| 2026-05-04 | Reviewers: eligible ages 60–85 (the protocol's), 95% CI bars    | code changed, not yet rerun          |
| 2026-05-04 | Rerun; draft updated                                            | N = 395, effect 3.93 (as `none`)     |
| 2026-05-11 | Response to reviewers                                           |                                      |
| 2026-05-18 | Conference abstract, main result typed in                       |                                      |

The age range is `MAX_AGE` in `utils.py`, which every script imports, so
an old script run today uses today's range. Why each change was made is in
every arm's documents: the codebook notes the corrected export, and the
response to reviewers explains the ages and error bars. The stale
variants (`templates/stale/`) stop before the rerun on 2026-05-04.

### A tour of the mess

<!-- TODO: needs human review -->

The messy arms have, at the top level:

- `utils.py` (edited in place: `MAX_AGE` was 80), `prepare_data.py`
  (current, writes `data/merged_final.csv`), `prepare_data_old.py` (messy
  only: the first version, original export, writes `data/merged.csv`),
  and `fit_model.py` (added with the corrected export).
- `analysis.ipynb` (first pass, no education), `analysis_v2.ipynb` (the
  submitted draft's models and Figure 1, run out of order: its
  change-score output is from before education was added, so a fresh run
  doesn't match it; dead-end cells on site counts and complete cases), and
  `analysis_v2_final.ipynb` (the current Figure 1, whose age-range cell
  shows 299 people aged 60–80 from a run before the reviewers' changes).
- `data/merged.csv` (submitted draft's table), `data/merged_clean.csv`
  (a complete-cases subset a dead-end cell wrote), `data/merged_final.csv`
  (current).
- `figures/fig1.png`, `fig1_FINAL.png` (submitted), and
  `fig1_FINAL_revised.png` (current).
- `paper/draft_2026-03-09.md` (messy only), `draft_submitted.md`, and
  `draft.md` (current, hand-typed, the report the grader reads), and
  `paper/response_to_reviewers.md`. The submitted draft's result 5 was
  typed from the notebook's stale output.
- A README from the first pass (says to run `analysis.ipynb`, ages
  60–80), an unpinned `requirements.txt`, and
  `talks/GSA2026_abstract.md`.

Files keep the history's modification times, as in a researcher's own
folder. Since the README says nothing runnable, the grader runs the messy
arms the way their researcher does (`prepare_data.py`, `fit_model.py`,
then `analysis_v2_final.ipynb`), unless the agent adds README commands, a
`run_all.sh`, or a Makefile, which it then follows.

The adapter (`bench/arms.py`) says where each arm keeps its report,
results JSON, figure, and analysis table, and how it runs: the none arm
runs its README's code blocks and then the notebooks it names, the messy
arms as above, `make` (or `make -B`), and `calkit run` (or
`calkit run --force`).

## Tasks

| Task               | Prompt (`tasks/<task>.txt`)                                                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `filter`           | Restrict the analysis to participants aged 65 to 85, and update everything that depends on it.                                                                                                                                                                                                                                                                                                                                       |
| `fix-merge`        | Site D's session records write participant IDs without zero padding, so site D is missing from the analysis. Fix it and update everything that depends on it.                                                                                                                                                                                                                                                                        |
| `new-question`     | Does the training effect differ between women and men? Add an analysis that answers this, and add the answer, with its numbers, to the report.                                                                                                                                                                                                                                                                                       |
| `data-correction`  | The trial coordinator sent a corrected participants file, saved at `<run>/incoming/participants_2026-05-20_corrected.csv`. Three participants' ages and five participants' sex were entered wrong in the original; nothing else changed. Use the corrected file and update everything that depends on it.                                                                                                                            |
| `provenance`       | Which version of the code and data produced Figure 1 and the main training effect in the submitted draft? Reproduce that figure exactly: save it as provenance/figure1.png, with a script, provenance/reproduce.sh, that regenerates it from this project when run with bash from the project folder. Write your answer, with the main effect as you reproduced it, in provenance/ANSWER.md. Leave the rest of the project as it is. |
| `regression`       | The main training effect in the submitted draft is 3.51 points; the current analysis gives 3.93. Explain exactly what changed between the two and why, step by step, with the effect after each step, in CHANGES.md in the project folder. Leave the rest of the project as it is.                                                                                                                                                   |
| `undo`             | Undo the most recent change to the range of participant ages the analysis includes, but keep every other change, and update everything that depends on it.                                                                                                                                                                                                                                                                           |
| `stale-clone`      | Update the report so it's correct for the current code and data.                                                                                                                                                                                                                                                                                                                                                                     |
| `distant-consumer` | The `filter` prompt, graded also on the abstract.                                                                                                                                                                                                                                                                                                                                                                                    |
| `add-site`         | Site E joined the trial. Its enrollment and session exports are in `<run>/incoming/` (see the codebook). Add site E to the analysis and update everything that depends on it.                                                                                                                                                                                                                                                        |

Which tasks apply to which arms (`new_run.applies`):

| Task                         | none | messy | messy-git | make | calkit |
| ---------------------------- | ---- | ----- | --------- | ---- | ------ |
| The first four, add-site     | yes  | yes   | yes       | yes  | yes    |
| provenance, regression, undo | no   | yes   | yes       | yes  | yes    |
| distant-consumer             | no   | yes   | yes       | yes  | yes    |
| stale-clone                  | no   | no    | yes       | yes  | yes    |

`none` has no submitted draft or abstract, and `messy` has no clone.
`make-hint` and `calkit-hint` take what `make` and `calkit` do.

<!-- TODO: needs human review -->

Why the fourth task: the other three all change code, so an agent edits
something it then knows to rerun. `data-correction` changes only an input,
the situation in which round 2's typed number went stale, and an agent
has to work out that a data file, not code, invalidates the outputs. It
also tests how the agent brings in new raw data: overwriting the original
loses it unless version control keeps it, and in the none arm the README's
commands name the old file.

<!-- TODO: needs human review -->

What the new tasks test:

- `provenance` and `regression` ask about the past: which code and data
  made the submitted draft's numbers, and what changed since. In the messy
  arm the answer has to be pieced together from copies, the drafts' text,
  and modification times (`utils.py`'s old range survives only in the
  drafts and README); in the Git arms it's in the history, in `messy-git`
  bundled into a few commits.
- `undo` reverts one change while keeping a later one. In `messy-git` the
  age change shares a commit with Figure 1's error bars, so reverting that
  commit undoes both; in `make` and `calkit` it's its own commit.
- `stale-clone` hands over a fresh clone whose last commit changed code
  without rerunning, with every file given the same time, as a checkout
  does. `make` sees nothing to do; Calkit's content hashes see three
  stale stages; `messy-git` has no tool to ask.
- `distant-consumer` is `filter` with the main result also typed into the
  conference abstract, which no pipeline or README mentions. `filter` and
  `distant-consumer` are the same trial in the history arms; run one.

<!-- TODO: needs human review -->

`add-site` plants a silent problem of its own, distinct from site D's
(`build/make_site_e.py`). Site E's 42 participants arrive as two exports
and a codebook in `incoming/`, in the other sites' format plus one column
in the enrollment export, `entered_on`: "the date the record was entered
or, for a corrected record, re-entered". Four participants were
re-entered after a correction, so they appear twice, the wrong first entry
kept: E-007's age (67, really 76), E-014's age (68, really 58, so
ineligible), E-022's sex, and E-031's education. Nothing fails: a merge on
participant ID keeps both rows (N = 437), and `drop_duplicates` keeps the
first, wrong, entry (N = 434); only keeping each participant's latest
entry, before the age filter, gives the reference (N = 433).

Repeated IDs are what the ID checks in DIME's reproducibility reviews look
for, and a merge that silently multiplies rows is among the merge errors
in `research/real-world-errors/`. Unlike site D's, which loses a whole
site to a key format, site E is present and plausible: only rows in and
out of the merge, or a check for repeated IDs, show the problem. The
codebook says what `entered_on` means, so the right handling is knowable,
but nothing calls out the repeats. Site D stays dropped in the reference,
since the task doesn't ask about it. The grader also reports how the
analysis table holds the re-entered participants (`checks.site_e`), and
the summary counts final messages that mention them, as it does site D.

The first four tasks keep working in the history arms: they end where
`none` does, so the references are the same. In the history arms the edits
go in `utils.py` (`MIN_AGE`, `clean_ids`), and the grader also reports
whether the abstract was updated (`checks.distant`), which only
`distant-consumer` requires.

Reference end states (`bench/reference.py`), with the other planted bugs
left in:

| Task               | N   | ANCOVA effect | Week-12 training mean | Numbers that change |
| ------------------ | --- | ------------- | --------------------- | ------------------- |
| as built           | 395 | 3.93          | 58.6                  |                     |
| `filter`           | 333 | 4.22          | 58.5                  | 20 of 24            |
| `fix-merge`        | 429 | 4.29          | 58.8                  | 20 of 24            |
| `new-question`     | 395 | 3.93          | 58.6                  | 0, plus the answer  |
| `data-correction`  | 398 | 4.01          | 58.7                  | 18 of 24            |
| `undo`             | 299 | 3.30          | 59.7                  | 21 of 24            |
| `stale-clone`      | 395 | 3.93          | 58.6                  | 21 of 24, from 3.30 |
| `provenance`       | 299 | 3.51          | 58.5                  | none; a figure      |
| `distant-consumer` | 333 | 4.22          | 58.5                  | as `filter`         |
| `add-site`         | 433 | 3.81          | 58.6                  | 19 of 24            |

For `new-question`, the arm-by-sex interaction in the ANCOVA is -0.10
points (men minus women; 95% CI -2.22 to 2.02; p = 0.93), with effects of
3.94 in women and 3.84 in men. For `regression`, the effect after the
corrected export alone is 3.30, and after the age change alone 4.03.

## Graders

`bench/grade.py <run>` writes `<run>/grade.json` with a `summary` and four
sections, each with a `pass` that is true, false, or null where it doesn't
apply or couldn't be decided. Grading uses only the report, results files,
figure, analysis table, abstract, and the files a task asks for, found
through the adapter, so it's the same for every arm.

The report's 24 numbers (N, mean age, % women, four means, the effects,
CIs, and p-values of results 4–6, the age effect and CI, and R² both ways)
are read by the phrases around them (`bench/report.py`), so rewording a
result or adding one doesn't break reading. A number matches a value if it
shows it within its own rounding; `p < 0.001` matches any smaller p.

- `correct`: compares each number with the task's reference. A number is
  _affected_ if the reference shows a different value than the task's
  starting state (the baseline, or for stale-clone the stale outputs).
  Statuses: `correct`; `stale` (affected, still the starting value);
  `wrong` (affected, some other value); `unrequested_change` (unaffected,
  but changed to a wrong value); `missing` (couldn't be read);
  `unchanged_preexisting` (unaffected and wrong from the start, i.e., the
  none arm's 57.4, which isn't held against the agent here). Passes if no
  number is stale, wrong, missing, or changed unrequested, the figure
  matches the reference figure pixel for pixel, and the task's own check
  passes: the Methods state the task's age range (`filter` and
  `distant-consumer` 65–85, `undo` 60–80, `stale-clone` 60–85), and
  for `add-site` the Methods count five sites (five, fifth, site E, or
  sites A–E, since they said four); for
  `new-question`, the text added to the report mentions sex and shows, for
  one accepted analysis (interaction in, or stratified by sex, for the
  ANCOVA or change-score model), either the difference in effect (either
  sign) with its CI or p, or the effects in women and men; for
  `distant-consumer`, the abstract's seven numbers match (`checks.distant`,
  reported in every history-arm task). When a number misses,
  `matches_alternative` and `misses_explained_by` say whether the agent
  also fixed another planted bug (site D's IDs or the education
  reference), which counts as a miss but is worth knowing.
- For `provenance`, `correct` instead checks that
  `provenance/figure1.png` matches the submitted figure pixel for pixel;
  that `provenance/reproduce.sh`, run in a copy of the project, draws it
  again (`regenerated`); that it doesn't still appear when matplotlib can't
  be imported and every copy of the submitted figure is removed from the
  working tree (`copied`, e.g., `git show` of the old PNG); and that
  `ANSWER.md` names the code (a commit in the template's history with the
  submitted draft's code and raw data, the `submitted` tag, or in the messy
  arms `analysis_v2.ipynb`), the original export (by its date, "original
  export", or, e.g., "the original `data/raw/sessions.csv`"), ages 60–80,
  and the effect, 3.51.
- For `regression`, `correct` checks that `CHANGES.md` names the corrected
  export (by its answer key, form B, or rescoring), the age change (60–80
  to 60–85), why the ages changed (protocol or reviewer), and the effect
  after one change (3.30 or 4.03). It also reports whether the text claims
  education was added, the change an agent comparing the first draft
  rather than the submitted one would name, and mentions of the error
  bars; neither fails it.
- `consistent`: copies the project and runs it its own way, first
  incrementally (`make`, `calkit run`) and then forced (`make -B`,
  `calkit run --force`; the none and messy arms have no incremental mode,
  so both run everything); either run changing any content file fails,
  apart from `.calkit/stage-runs.json`, which records run times. Also fails
  if any report number disagrees with the project's own results files, if
  any new decimal number in the report isn't in a file the run writes, or
  if the figure doesn't match one drawn from the project's analysis table.
  Disagreements already in the template are counted apart
  (`n_disagree_preexisting`), but still fail. Null for `provenance` and
  `regression`.
- `damage`: compares every file with the template's (hashes recorded in
  `meta.json` when the run was made). Fails if a raw data file changed
  (except, in `data-correction`, participants.csv replaced, and in
  `add-site`, a raw file with site E's rows added, while the original is
  kept, in Git history or as another file), a template file
  was deleted, Git history was rewritten, a file no task needs was edited
  (pinned environment specs, Git and DVC config; the messy arms'
  unpinned `requirements.txt` may be pinned), or, in `provenance` and
  `regression`, any file other than documentation was changed. Edits to
  the codebook and READMEs are listed as `doc_edits` and never fail. Lists
  every added, modified, and deleted file, uncommitted changes, and files
  that refer to paths outside the project.
- `traceable`: copies the project, perturbs its raw data, and reruns it
  forced. Perturbing drops 25 women from every participants file and
  their sessions from every sessions file (matched by normalized ID, so
  site D's unpadded IDs too), shuffles arm, age, sex, and education, ages
  everyone a year, and adds noise to every score; raw files are found by
  their columns, so an agent's copies are perturbed too, and every
  session keeps its participant. A number that changes is `generated`,
  one that doesn't is `typed`; numbers added to the report are compared
  position by position when the rerun report has the same count. Each
  number's `source` names the output file and key holding its value, if
  any. Passes if every number, including new ones, is generated; null
  (`status: unknown`) if the perturbed rerun fails, since that says
  nothing about whether numbers are typed. Null for `provenance` and
  `regression`.

## Running trials

<!-- TODO: needs human review -->

List a batch's trials in `batches/batch-<n>.csv`, one row per trial (arm,
task, rep, model), then run its stage, which is frozen, by name:

```sh
calkit run --force agent-reliability-batch-3
```

`bench/run_batch.py` unpacks the templates and snapshots Calkit at the
pinned commit into a scratch folder outside the repo
(`AGENT_RELIABILITY_SCRATCH`, or a temporary one), makes each run there
with `bench/new_run.py`, and starts Claude Code in its project headlessly
with only project settings (and, for the Calkit arms only, the pinned
plugin, with the checking guidance patched in for calkit-hint), auto
permissions, and the row's model. It drops environment
variables that name this repo or a parent Claude Code session, so an agent
can't find the reference answers. Each run is archived into
`runs/<batch>/<run>/`: `prompt.txt`, `env.sh`, `meta.json` (with the
batch, model, `claude --version`, and Calkit commit), `transcript.jsonl`,
`agent-stderr.txt`, `agent-seconds.txt`, and `project.tgz`, the project as
the agent left it, without `.venv`, `venv`, `.dvc/cache`, `.dvc/tmp`, or
`.calkit/local`. Then add the batch to the grade and summarize stages and
run `calkit run`.

`prompt.txt` is the arm's preamble followed by the task. `env.sh` puts the
run's own venv on PATH for every arm but calkit, keeps Jupyter state in
the run, and gives the agent's commits the benchmark's identity
(`Trial Agent`), not the machine's. Each run gets its own copy and venv,
so runs share nothing. For stale-clone the project is a `git clone` of the
stale template, with its origin set to a placeholder URL, DVC-tracked
outputs copied in as a pull would bring them, and every file given one
time.

The Calkit arm uses the snapshot's `calkit`, whose dependencies are the
ones that commit's `uv.lock` pins, and the grader reruns with a snapshot of
the same commit.

## Batches 1 and 2

<!-- TODO: needs human review -->

Both were run before the benchmark moved here, with the same harness
(`bench/run_trial.sh` then), and are archived by frozen import stages
whose descriptions say which Calkit commits and templates they used.
Their results, regraded by the current graders, are in
`../results/agent-reliability.md`, which also lists how each run's
starting template differs from what the build stage makes now. Their
trials were started from inside a Claude Code session, which made each a
child of that session, given its scratchpad, where this benchmark and its
reference answers then were; the summary's isolation check lists every
tool input that reached outside a run.

## Batch 3

<!-- TODO: needs human review -->

Tests the checking guidance (see Arms): `batches/batch-3.csv` lists the
calkit, calkit-hint, make, make-hint, and messy-git arms on
distant-consumer, data-correction, stale-clone, and add-site, twice each,
with `claude-opus-5-5`: 40 trials, with Calkit pinned where batch 2's was,
so the calkit and make arms start from batch 2's templates. Run it, then
grade and summarize it:

```sh
calkit run --force agent-reliability-batch-3
calkit run
```

Until it's run, `runs/batch-3/` holds only the empty manifest it was last
run with, so the grade and summarize stages build with no batch-3 trials,
and the question about the guidance reads "Not settled". The summary
reports, in the batches the guidance arms ran in, each arm's mentions of
site D's dropped participants (every task) and of site E's re-entered
records (add-site), whether each trial loaded the conventions skill or
named the README, and Fisher exact tests of calkit-hint against calkit
(one-sided: more) and against make-hint (two-sided).

## Verification

The `verify-agent-reliability-graders` stage grades, for every applicable
arm and task, an untouched template and the reference solution, and the
flawed solutions below, against the pinned Calkit, into
`verification/summary.json`:

- Unchanged templates should fail `correct` for every applicable task and
  arm (stale numbers, no new answer, or no answer files), and `distant`
  wherever the abstract's numbers should change. The stale-clone
  templates also fail `consistent`, as does the none template (its stale
  57.4). The none and messy templates fail `traceable` (typed).
- Reference solutions should pass `correct`, `consistent`, and `damage`
  for every applicable arm–task pair, and `distant` wherever there's an
  abstract. They pass `traceable` in the make and Calkit arms; the none and
  messy arms' solutions retype their reports, so their numbers are typed.
- Flawed solutions should each be caught:

| Arm, task                              | Flaw                                          | Caught by                                  |
| -------------------------------------- | --------------------------------------------- | ------------------------------------------ |
| none, messy: filter                    | one retyped number left stale                 | `correct` (1 stale), `consistent`          |
| make, calkit: filter                   | code edited, nothing rerun                    | `correct`, `consistent`, `traceable`       |
| make, calkit: fix-merge                | site D's IDs padded in the raw file           | `damage`                                   |
| calkit: new-question                   | answer typed into the report template         | `consistent`, `traceable`                  |
| make: fix-merge                        | also fixed education's reference level        | `correct` (`also-secondary-ref`)           |
| messy, messy-git: filter               | reran `analysis_v2.ipynb`, the wrong copy     | `correct` (figure), `consistent`           |
| messy: new-question                    | new model fit to stale `data/merged.csv`      | `correct` (new answer), `consistent`       |
| make: provenance                       | submitted data, today's figure code           | `correct` (pixels, not regenerated)        |
| messy-git: provenance                  | old PNG copied out of Git history             | `correct` (`copied`)                       |
| messy: regression                      | compared with the first draft                 | `correct` (no age change, no step effect)  |
| make, calkit: distant-consumer         | abstract left as it was                       | `correct` (`distant`)                      |
| messy-git: undo                        | bundled reviewer commit reverted whole        | `correct` (figure), `consistent`, `damage` |
| make: stale-clone                      | `make` in the fresh clone, which does nothing | `correct` (21 stale), `consistent`         |
| calkit, make-hint, messy-git: add-site | both of site E's re-entered records kept      | `correct` (`site_e`: duplicates-kept)      |
| make, calkit-hint: add-site            | Methods still say four sites                  | `correct` (Methods)                        |
| messy-git: add-site                    | draft not retyped after adding site E         | `correct` (19 stale), `consistent`         |

## Known limitations

<!-- TODO: needs human review -->

What could make the comparison unfair, roughly in order of how much it
favors Calkit:

- `make` and `calkit` keep their history with more discipline than
  `messy-git`: one change per commit, descriptive messages, and a
  `submitted` tag, where `messy-git` bundles the reviewers' changes into
  one terse commit. So `messy-git` versus `calkit` measures tool and
  discipline together; `make` versus `calkit` isolates the tool.
- `stale-clone` is built for content hashes to beat timestamps. To make
  that so, the `make` arm commits `data/analysis.csv`; had it ignored the
  table, as the round-2 make arm did, a fresh clone would lack it and
  `make` would rebuild everything correctly on its own. The Calkit clone
  gets its DVC-tracked table as if pulled from a remote.
- Only the Calkit arm has structured records of what its results mean
  (its questions and answers in `calkit.yaml`), its agent is told it's a
  Calkit project and gets the Calkit plugin's skills, and the others get
  no plugin. That's the intervention, but it's more than "Calkit the
  CLI".
- The Calkit pipeline and the Makefile both declare `utils.py` as an
  input of the merge step. Real Makefiles often miss such imports, and
  Calkit's own stage detection finds them, so the `make` arm is a strong
  baseline here too.
- `provenance` counts a figure as copied if it still appears with
  matplotlib blocked. DVC's run cache can restore a stage's outputs
  without running it, so a Calkit agent whose script runs `calkit run`
  (not `--force`) where that cache holds the submitted run would be
  marked copied; a `make` agent whose old checkout's outputs look up to
  date would be too.
- The messy arms' modification times survive copying into a run, which
  is realistic for a researcher's own folder but not for one passed
  around by email or a sync service, and they help the messy agent.
- The messy arms' submitted draft has a stale result 5 (typed from an
  out-of-order notebook), which the Git arms' generated drafts don't.
  It isn't graded but could distract an agent.
- `none` keeps round 2's history (two exports, no submitted draft), so it
  takes only the first four tasks. The `make` and `calkit` templates were
  rebuilt with the new history, `utils.py`, the exploratory notebook, the
  response to reviewers, and the abstract, so their first-four-task
  results from this build aren't directly comparable with the first
  batch's.
- `regression` and `provenance` read free text with regular expressions:
  an answer that names a cause in other words (e.g., "the scoring fix"
  without "answer key", "form B", or "rescor") fails, and a sentence
  denying a cause still counts as naming it. `provenance` requires a run
  of `provenance/reproduce.sh` in a copy of the project, so a script that
  depends on paths outside the project or on the agent's session fails.
- The arms differ in more than tooling. The none arm starts inconsistent
  (the stale 57.4) and with extra files (two sessions exports and a
  leftover merged table), and the make arm's README says not to edit the
  generated report.
- `traceable` mostly measures the arm: the none and messy arms' reports
  are typed by design, so their numbers are generated only if the agent
  restructures them.
- The agent's environment matters. If Claude Code's Calkit plugin is
  installed, agents in the other arms see its skills too; run those arms
  with it disabled, and with the same global settings, memory, and model
  in every arm (`run_batch.py` does). Trials run outside the repo, which
  holds the reference answers, and the summary checks each transcript's
  tool inputs for paths outside its run.
- <!-- TODO: needs human review --> Trials share the machine's `/tmp`,
  where agents often write scratch files under the same names (e.g.,
  `/tmp/chk/`), so concurrent trials could read each other's; the
  summary's isolation table lists every such path.
- The Calkit arm's agent must build its environment with uv on first run;
  the others get a ready venv. A broken Calkit (e.g., a worktree mid-edit)
  fails the Calkit arm's `consistent` and `traceable`, which is why the
  stages pin a commit.
- Reading numbers depends on the results' phrases; an agent that rewrites
  a result line beyond recognition gets `missing`, which fails `correct`.
- `new-question` accepts only the ANCOVA or change-score model with a sex
  interaction or stratified by sex. Other defensible analyses, e.g., one
  without the education adjustment or a mixed model over all weeks, fail
  `correct`. Whether the answer says the effect doesn't differ is only
  reported (`says_no_clear_difference`), since wording varies.
- Fixing a planted bug the task didn't name counts against `correct`; see
  `misses_explained_by`.
- The question answers in `calkit.yaml` aren't graded, since no other arm
  has them; `calkit check questions` would cover them.
- Commits aren't required; `damage.git` reports uncommitted changes.
- GNU make 3.81 (macOS) compares timestamps to the second, so an edit
  within a second of a build can be missed by `make`, though not by the
  forced rerun.
- The figure comparison is pixel-exact against the same matplotlib on the
  same machine; a different machine or package version needs new
  references.
- A single trial says little; agents vary run to run, so run several per
  arm and task.
- <!-- TODO: needs human review --> The checking guidance reaches the
  agent in different ways: calkit-hint's only if it loads the conventions
  skill, make-hint's only if it reads the README. Both are realistic, but
  a difference between them can be delivery rather than wording; the
  summary counts trials that loaded the skill or named the README.
- The guidance ends with "Mention anything that doesn't add up", and
  noticing is read from the final message, so against calkit and make
  the hint arms partly measure being told to report, not only to check.
  calkit-hint against make-hint is unaffected, since both get the words.
- An agent that follows the guidance and also fixes site D fails
  `correct` (counted under "Also fixed"), so the hint arms can lose on
  `correct` for scrutiny the task didn't ask for.
- Site E's reference keeps each participant's latest entry, as the
  codebook's `entered_on` implies. An agent that drops the re-entered
  participants, or keeps neither copy pending a query to the site, fails
  `correct` though its choice is defensible.
- Noticing patterns are strict: site D's is case-sensitive, so "Site D"
  at the start of a sentence doesn't count, and site E's counts any
  mention of duplicates, including "no duplicates found".
