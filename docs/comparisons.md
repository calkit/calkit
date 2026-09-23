# Calkit vs. other tools

Calkit is an interface on top of a project's files.
It declares how to run the project (environments and the pipeline),
what the project claims (questions answered with evidence),
and whether those claims are current (`calkit check questions`).
Without it, that structure is usually implicit,
or described in prose, e.g., in a README.

Other tools overlap with parts of this.
This page compares them on the facts, and says where they fit together.

## Harbor and Terminal-Bench-Science

[Harbor](https://github.com/harbor-framework/harbor) is a framework for
evaluating agents and models in containers.
[Terminal-Bench-Science](https://github.com/harbor-framework/terminal-bench-science)
(TB-Science) is a benchmark built on it,
with 70 research tasks written by domain scientists as of v0.1.

A Harbor task is a directory with:

- `instruction.md`, the prompt the agent receives
- `task.toml`, with metadata, resource limits, timeouts, network policy,
  and the paths to collect from the sandbox after the agent finishes
- `environment/Dockerfile`, the agent's container
- `tests/`, a verifier that writes a reward, optionally in its own container
- `solution/`, a reference solution the `oracle` agent runs

A trial is one agent's attempt at one task.
A job is a set of trials.
Each trial directory records its configuration, a `lock.json`,
the agent's logs, the collected artifacts with a manifest,
and the verifier's output and reward.
`harbor trial regrade` reruns a new verifier on the recorded artifacts
without rerunning the agent,
and records which trial the new result was derived from.

|                   | Harbor                                     | Calkit                                        |
| ----------------- | ------------------------------------------ | --------------------------------------------- |
| Unit              | A trial: an agent's attempt and its reward | A project: its pipeline, outputs, and claims  |
| Question answered | Did this agent solve this task?            | Do these outputs follow from these inputs?    |
| Environment       | A container per task                       | Named environments per stage, of many kinds   |
| What reruns       | The verifier, on recorded artifacts        | Stages whose inputs or environments changed   |
| Claims            | A reward from the verifier                 | Questions whose answers cite pipeline outputs |

They answer different questions, so they don't compete.
They meet in three places.

### Task authoring

TB-Science tasks can include an `authoring/` directory, holding
`provenance/` (generators, checksums, source URLs) and
`evidence/` (independent reimplementations, calibration studies).
48 of the 70 tasks in v0.1 have one.
The contributing guide says CI doesn't inspect it.
How to rerun it, and which script backs which number in the task's
README, is described in prose.

As a prototype, we added a `calkit.yaml` to the `reactor-safety-control`
task, with a Docker environment pinned to the same base image and packages
as the task's, and four stages:
generating the fixtures, calibrating the accept region,
an alternate-noise sweep, and an identification check.
The pipeline took 13 minutes to run.
The regenerated fixtures, including the hidden scenarios, reference times,
and hash manifest, were byte-identical to the committed ones.
Four questions answer from values in the results files,
reproducing numbers the README states by hand,
e.g., the independent controller's worst productivity ratio of 1.04981,
and a baseline failing 7 and 13 of 21 scenarios with 1.0 K and 1.5 K of
safety back-off.

### Agent submissions

A task can ask the agent to deliver a Calkit project,
so the verifier can check that its claims trace back to its pipeline,
and a person reviewing the trial has an entry point into the files.

We made a variant of the same task whose instructions require the
submission to be a committed Calkit project,
with a pipeline that produces the design report,
and an answered question backed by `value` evidence.
Its verifier copies the project, removes untracked files with
`git clean -fdx`, then runs `calkit check questions` and
`calkit run --force` and requires an identical report.
The oracle solution passed all 34 tests under `harbor run`.
Two tampered copies of the recorded submission,
rescored with `harbor trial regrade`, were both rejected:

| Tampering                                    | Original tests              | Calkit checks                                                   |
| -------------------------------------------- | --------------------------- | --------------------------------------------------------------- |
| Report edited by 1% and committed            | Pass, since tolerance is 2% | Fail: the evidence is `stale`, and the rerun changes the report |
| Answer cites a number in a hand-written file | Pass                        | Fail: `error`, since no pipeline stage computes the value       |

Calkit checks that claims are traceable and current, not that they're
correct.
The verifier's own tests still do that.

Some constraints came from the verifier's sandbox:

- Rerunning the pipeline executes the agent's code,
  so it has to run as an unprivileged user,
  or it could read the hidden fixtures or write its own reward.
- The verifier has no network,
  so the project uses a `system` environment,
  and must carry its own copies of its inputs.
- The verifier makes `/var/tmp` unwritable for other users,
  so `DVC_SITE_CACHE_DIR` has to point somewhere the unprivileged user can
  write.

The prototype turned up some gaps in Calkit, since fixed:
`calkit run` reported a DVC repo it couldn't open as a missing one,
`value` keys containing dots could only be read at the top level,
and a true/false value couldn't be used on its own in a condition.

Both prototypes can be rebuilt from the
[example](https://github.com/calkit/calkit/tree/main/examples/harbor-tb-science),
which fetches the task at a pinned commit rather than copying it.

### Benchmark results

A claim like "model A outperforms model B on the physical sciences tasks"
is itself a research result.
Harbor jobs could be frozen pipeline stages,
with questions citing values from each trial's `result.json`.
We haven't tried this yet.

## Agentic research tools

These run AI agents that do research.
Calkit doesn't run agents itself;
it gives them, and the people checking their work,
a declared structure to work within.

### Claude Science

[Claude Science](https://claude.com/docs/claude-science/overview)
is a desktop app in beta, launched in June 2026,
that pairs Claude with an analysis environment on the user's computer,
aimed at the life sciences first.
Claude runs Python, R, and shell code in a sandbox,
in conda environments it manages,
and connects to scientific databases and compute clusters.
It requires a paid Claude plan, and its source isn't published.

Its record of the work is per
[artifact](https://claude.com/docs/claude-science/artifacts),
i.e., a saved figure, dataset, report, or notebook.
Each version of an artifact records the conversation around it,
a reproducible script, the log of every command that ran,
and the environment's packages and versions.
[The reviewer](https://claude.com/docs/claude-science/the-reviewer)
checks Claude's claims against that record,
e.g., a value that contradicts the file it came from,
but it doesn't re-run analyses.
Artifacts live in the app's data folder, `~/.claude-science`,
not in a repository.

Checking claims against evidence is common to both tools.
Calkit keeps that record in the project repository instead,
as a declared pipeline that anyone who clones it can rerun,
and `calkit check questions` also reports evidence whose stage is out of
date.

### OpenResearch

[OpenResearch](https://github.com/alphaXiv/OpenResearch), by alphaXiv,
is a local-first workspace that turns coding agents,
e.g., Claude Code or Codex,
into research agents that review literature, form hypotheses,
and run experiments.
A project is a tree of experiments,
each on its own Git branch,
sharing one fixed run command.
Each run uses a snapshot of its branch's commit,
and the run record keeps the command, commit, and exit code.

Environments are left to the project,
with the agent told to prefer uv with committed lock files.
There's no pipeline of stages or caching of outputs.
Agents are told to cite runs and files after claims in their replies,
but nothing checks the citations.
Run logs, reports, and figures are kept in a data directory outside the
repository.

A project's run command could be `calkit run`,
which would add declared environments, stages that are skipped when
unchanged, and versioned outputs in the repository.
In the other direction, OpenResearch's experiment trees and launching on
remote compute are things Calkit doesn't do.

## Workflow and pipeline tools

These run a graph of steps and skip the ones that are up to date.
Calkit's pipeline is one of these:
it's compiled to a DVC pipeline.
What Calkit adds is mainly around it:
environments declared per stage and checked before running,
and questions whose answers are checked against the outputs.

| Tool                                          | Unit of work            | Environments                                         | Skips unchanged work by               |
| --------------------------------------------- | ----------------------- | ---------------------------------------------------- | ------------------------------------- |
| [DVC](https://doc.dvc.org/user-guide)         | Stage in `dvc.yaml`     | Not part of the tool                                 | Hashes of inputs and outputs          |
| [Snakemake](https://snakemake.readthedocs.io) | Rule                    | Conda or a container per rule                        | Rerun triggers, optional cache        |
| [Nextflow](https://docs.seqera.io/nextflow/)  | Process                 | A container, conda, or Spack per process             | A hash of each task (`-resume`)       |
| [Make](https://www.gnu.org/software/make/)    | Rule                    | Not part of the tool                                 | File timestamps                       |
| [Airflow](https://airflow.apache.org/docs/)   | Task in a scheduled DAG | Virtualenv, Docker, or Kubernetes operators          | Not its purpose                       |
| Calkit                                        | Stage in `calkit.yaml`  | Many kinds per stage, e.g., uv, conda, Docker, Julia | DVC, with environment locks as inputs |

Snakemake and Nextflow run on clusters and in the cloud without changes
to the workflow, and Nextflow has a large library of community pipelines
in [nf-core](https://nf-co.re/).
Airflow is for workflows that run on a schedule,
rather than for reproducing a result.
None of these link claims in a paper to their outputs.

### showyourwork

[showyourwork](https://show-your.work/) is the closest to Calkit.
It builds a LaTeX article from a Snakemake workflow on every push with
GitHub Actions, and it uses conda for environments.
`\script` ties a figure to the script that made it,
`\variable` inserts a file's contents, e.g., a computed number,
into the text as a workflow dependency,
and the PDF gets margin icons linking figures to their scripts.
Expensive outputs can be cached on Zenodo.
The project layout is fixed,
and as of September 2026 its docs note that the last release is over two
years old.

Calkit isn't limited to one article, layout, or kind of environment,
and its questions state claims apart from any document,
with the check reporting stale or untraceable evidence.

### The Turing Way

[The Turing Way](https://book.the-turing-way.org/) is a community-written
handbook on reproducible research, rather than a tool.
Its guidance, e.g., on environments and version control,
is what tools like these put into practice.
