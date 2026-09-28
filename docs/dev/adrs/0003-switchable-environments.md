# ADR 0003: Switchable environments

<!-- prettier-ignore -->
!!! note
    This document was written by Anthropic's Claude Code.

- Status: proposed
- Date: 2026-09-27
- Related: [ADR 0001](0001-operators.md), [ADR 0002](0002-jupyterhub.md)

## Context

Workflow tools like Snakemake and Nextflow declare software environments
and resource needs in the workflow, but keep the executor, i.e., where
steps run, abstract: it's chosen when running, with a profile, often kept
outside the project, so the same workflow runs locally or on any cluster.

Calkit instead records where stages run in the project.
An environment of kind `slurm`, `pbs`, or `system` says which machine runs
it, e.g., by `host`, and a composite environment such as `cluster:py`
combines that with a software environment.
This has held up as the better policy:

- Where each stage runs is versioned with the project, so it's known where
  results were made, and moving a stage somewhere else is an explicit,
  visible change rather than a local profile.
- Infrastructure needs nothing per project, just to be reachable.
- Running without a cluster, e.g., to develop or test, is covered by
  scheduler mocking with `CALKIT_MOCK_SCHEDULER`, not by redefining where
  stages run.

It has a cost, though: a project used on more than one cluster needs its
environments edited every time it moves, which users have found painful.

## Decision

Placement stays in the project, and running stages elsewhere stays an
explicit change to it.
To make moving between places the project already knows about cheap, a new
environment kind, `switch`, picks one of several named environments based
on the machine Calkit is running on.

```yaml
environments:
  cluster:
    kind: switch
    options:
      - when: { hostname: "*.gps.caltech.edu" }
        use: clima
      - when: { env: { NERSC_HOST: perlmutter } }
        use: perlmutter
      # From anywhere else, e.g., a laptop, reach clima remotely
      - use: clima-remote
  clima:
    kind: slurm
    default_options: [--gpus=1, --partition=gpu]
  perlmutter:
    kind: slurm
    default_options: [--gpus=1, -C, gpu, -A, m1234]
  clima-remote:
    kind: slurm
    host: clima.gps.caltech.edu
    default_options: [--gpus=1, --partition=gpu]
  py:
    kind: uv-venv
    path: requirements.txt
```

A stage using `environment: cluster:py` runs with `clima`'s scheduler
options when run on that cluster, `perlmutter`'s on Perlmutter, and
submits to `clima` remotely from anywhere else, always in the same `py`
environment.
Adding another cluster is still a change to the project; moving between
the ones it declares isn't.

### Matching

- Options are tried in order, and the first whose `when` matches is used.
  An option without `when` matches anywhere, so it can serve as a default.
- `when` can match this machine's hostname against a glob, its
  `machine_id` as `calkit describe system` reports it, or environment
  variables, all of which must match.
  Hostnames often differ between a cluster's login and compute nodes, so
  variables a site sets, e.g., `NERSC_HOST`, can be more reliable.
- If nothing matches and there's no default, it's an error listing the
  options and what this machine looked like, rather than a guess.
- Options name ordinary environments, so each can be used, checked, and
  locked on its own.
  An option can't be another `switch`.

### What makes results stale

Declaring where to run is separate from whether results depend on the
machine, as ADR 0001 also holds for Operators.
So a stage using a switch depends on the switch's definition and the
environments it names, so editing them reruns the stages that use them,
but not on which option was picked, so moving between clusters doesn't
make everything stale.
Projects whose results really do depend on the machine can lock
`machine-id` as they can today.

### Provenance

A run records which option each stage used and on which machine, so
where results were made is known even though nothing in the project
changed.
`calkit status` shows which option applies on the current machine, and
`calkit check` validates every option, including those for machines it
isn't running on.

## Consequences

- Moving a project between clusters it already declares needs no edits,
  while where it can run stays in the project.
- The same checkout resolves stages differently depending on the machine,
  which the run record and `calkit status` make visible.
- Stages don't rerun just because they ran on a different declared
  cluster, which is right for placement but means machine-dependent
  results need an explicit `machine-id` lock.
- Projects using several clusters need all of them described, which is
  more to write than a single environment, but is written once.

## Alternatives considered

- **Per-user or per-run placement, e.g., profiles or a `--placement`
  option**, as in Snakemake and Nextflow.
  Flexible, but where stages ran would no longer follow from the project,
  and moving them would be silent.
- **Editing environments each time a project moves**, today's approach,
  which keeps everything explicit but is what users found painful.
- **Making the chosen option part of each stage's dependencies**, which
  would rerun every stage after moving clusters, even when results don't
  depend on the machine.
