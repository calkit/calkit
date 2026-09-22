# Calkit and other tools

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
Four questions answer from `value` evidence,
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

## Other tools

<!-- TODO: workflow and pipeline tools, see
https://github.com/calkit/calkit/issues/214 -->

<!-- TODO: OpenResearch, see
https://github.com/calkit/calkit/issues/1689 -->
