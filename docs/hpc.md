# High performance computing

Calkit projects can help simplify working on high performance computing (HPC)
clusters and their job schedulers.
In general, what you'll want to do is clone the project there,
run your pipeline (perhaps only certain stages), commit the results,
then push them up to the cloud.

This is different from a more ad hoc workflow where you might copy a few
files to the cluster, run some jobs, then copy the results back manually.
In the Calkit workflow, we are keeping track of all of the inputs and outputs,
so we retain a complete history of how all outputs were produced.
This can come in handy later on when it's time to do more iterations,
e.g., after journal article reviews come back.

<!-- prettier-ignore -->
!!! tip
    Use VS Code's "remote host" feature to connect to your cloned project
    folder on the HPC.

Calkit supports defining both SLURM and PBS job schedulers as environment
kinds in which to run pipeline stages.

```yaml
environments:
  cluster1:
    kind: slurm # Or `pbs`
    host: cluster.myuni.edu # Optional
    default_options: # Optional
      - --gpus=1
    default_setup: # Optional
      - module purge
      - module load something/cool
  my-conda-env:
    kind: conda
    path: environment.yml
```

The `host` for a cluster scheduler environment is optional.
It can be useful to define for the sake of documentation,
to ensure certain pipeline stages only run on certain clusters,
or to invalidate cached outputs if the host changes.

`shell-script`, `shell-command`, and `command` stages can run directly in
`slurm` or `pbs` environments, e.g.,:

```yaml
pipeline:
  stages:
    my-script:
      kind: shell-script
      environment: cluster1
      script_path: scripts/run-job.sh
      args:
        - my-case
        - --steps=1
      inputs:
        - config/simulation.txt
      outputs:
        - path: results/raw
          storage: null # If the results are too large to push to the cloud
```

It's also possible to use a nested environment, e.g., if you want to run
a Python script in a Conda inner environment with a SLURM or PBS outer
environment:

```yaml
pipeline:
  stages:
    my-python-script:
      kind: python-script
      script_path: scripts/run.py
      environment: cluster1:my-conda-env # Note the `:` between env names
      inputs:
        - results/raw
      outputs:
        - results/summary.csv
```

In this case, Calkit will first ensure the Conda environment matches its spec
and/or lock file, then run the Python script with the job scheduler.

It's generally a good idea to run the pipeline with something like `tmux`,
but it's also okay to log off and return to rerun `calkit run`.
Job status will be saved so they are not resubmitted.
If a job has finished and the pipeline is up-to-date, it won't be rerun.
On the other hand, if something failed or one of the input files has changed,
you'll be able to see that with `calkit status`.

## Options and setup

Default job options and setup commands can be defined at the environment
level, and these can be ignored, replaced, or extended (via merging)
for individual pipeline stages as shown
in the example below.

```yaml
pipeline:
  stages:
    my-python-script:
      kind: python-script
      script_path: scripts/run.py
      environment: cluster1:my-conda-env
      scheduler:
        env_default_options: replace # Default; can also be `ignore` or `merge`
        options:
          - --account=mylab
          - --gpus=2
          - --time=120
        env_default_setup: replace # Default; can also be `ignore` or `merge`
        setup:
          - module purge
          - module load something/else
      inputs:
        - results/raw
      outputs:
        - results/summary.csv
```

## Running jobs in parallel

By default, Calkit submits scheduler jobs one at a time, waiting for each to
finish before submitting the next.
This keeps execution predictable for ordinary stages.

The exception is a stage that uses `iterate_over` to sweep over a list of
values.
Because each iteration is an independent job, Calkit submits them all at once
and lets the cluster's own scheduler queue them according to available
resources---the scheduler, not Calkit, decides how many actually run at the
same time.

```yaml
pipeline:
  stages:
    sweep:
      kind: shell-script
      environment: cluster1
      script_path: scripts/run-case.sh
      args:
        - "--Re={Re}"
      iterate_over:
        - arg_name: Re
          values: [1000, 2000, 4000, 8000]
      outputs:
        - results/Re-{Re}.csv
```

The four `Re` cases above are submitted together rather than back-to-back.
Each iteration is still cached independently, so if one job fails you can
simply rerun `calkit run` to pick up where it left off: the cases that
succeeded are skipped and only the failed one is resubmitted.
(`calkit run --force` re-runs every case serially instead, since it ignores
the cache; just editing a script invalidates the affected cases without
`--force`, so they still re-run concurrently.)

## Monitoring

Inside a project folder, you can check on any of the current project's jobs
running on the cluster with:

```sh
calkit scheduler queue
```

Or with the abbreviated command:

```sh
ck sch q
```

You can also view the job output logs with:

```sh
ck sch logs
```

See the `--help` output of each command for arguments and options.

## Testing locally without a scheduler

To develop or test a scheduler-based pipeline on a machine that has no SLURM or
PBS installation, set the `CALKIT_MOCK_SCHEDULER` environment variable.
Calkit then runs each job as a regular local process---writing to the same log
files and showing up in `calkit scheduler queue`---as if it had been submitted
to a real cluster:

```sh
CALKIT_MOCK_SCHEDULER=1 calkit run
```

<!-- prettier-ignore -->
!!! tip
    Add `--dry` to preview the exact commands Calkit would run before executing
    anything, then drop it to actually run them locally:

    ```sh
    CALKIT_MOCK_SCHEDULER=1 calkit run --dry
    ```

Mock job state lives under `.calkit/local/`, which is always ignored by Git,
so it never makes its way into your project history.
