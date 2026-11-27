# Running and logging

When the pipeline is run with the `calkit run` command,
Calkit will first compile the pipeline into a DVC pipeline
with its dependencies set based on [environment](../environments.md)
lock files, such that a change in an environment causes a rerun.

Before running, and before `calkit status` checks the pipeline,
Calkit also prepares files the stages depend on that aren't stored in the
project.
It checks environments and writes their lock files,
and cleans the outputs out of notebooks.
While turning each `latex` stage into a DVC stage, it also copies the
components the document includes with
[Calkit's commands](../latex.md#including-project-components) beside it.
These steps are quick when nothing has changed, so they run every time.

Each successfully completed stage is recorded in
`.calkit/stage-runs.json`, which is intended to be committed
to the project's Git repository.
This records when it ran, in which environment
(and which option any `switch` environment used),
with which version of Calkit,
and on which machine.
A stage that runs an app no environment pins,
e.g., an Inkscape export,
also records which version of that app it ran.
The entry is replaced each time the stage runs,
so the file describes how the current outputs were made,
and its Git history is the stage's run history.
It also records the commit the run started from,
whether there were uncommitted changes,
and a checksum of the stage's `dvc.lock` entry after it ran.
`calkit check stage-runs` reports any stage whose `dvc.lock` entry
doesn't match its recorded run,
e.g., after `dvc commit` of an edited output.

<!-- TODO: needs human review -->

Since run records are often public,
the machine is recorded as `machine_id_hash`,
a Calkit-specific hash of the ID the platform gives it,
e.g., macOS's hardware UUID or Linux's `/etc/machine-id`,
rather than that ID itself,
which can't always be reset and which other software uses too.
A system environment that locks `machine-id` records the same hash.
A run record or lock written before Calkit hashed machine IDs
keeps the raw ID until it's rewritten,
so each release archived from the project publishes it until then.
A stage's entry is rewritten when that stage runs again,
e.g., with `calkit run --force`.
A lock with `relock: auto` is rewritten with the hash
the next time it's checked, e.g., by `calkit run`,
and one with the default, `relock: manual`,
when it's relocked with `calkit update env -n NAME --lock`.
Either way the lock file changes,
so the stages that depend on it rerun once.
The project's Git history keeps the earlier values regardless.

If the `--log` option is specified,
DVC logs will be sent into `.calkit/logs` while the run is executing,
and after it's complete, run metadata,
including system information such as foundational dependency versions,
will be saved to a JSON file in `.calkit/runs`.
Again, these can be helpful for traceability and
diagnosing reproducibility issues down
the road, e.g., if the project is being run on multiple machines and
the results are different between them.
Without `--log`, these are saved in `.calkit/local`, which is kept out
of version control.

The run metadata can be queried and analyzed, for example,
with [DuckDB](https://duckdb.org):

```python
import duckdb

duckdb.sql(
    """
        select
            system.node_id,
            system.calkit_version,
            cast(end_time as timestamp)
                - cast(start_time as timestamp) duration,
            status
            from '.calkit/runs/*.json'
            where dvc_args = '[]'
    """
)
```

```
┌─────────────────┬────────────────┬─────────────────┬─────────┐
│     node_id     │ calkit_version │    duration     │ status  │
│      int64      │    varchar     │    interval     │ varchar │
├─────────────────┼────────────────┼─────────────────┼─────────┤
│ 138587250590302 │ 0.26.0         │ 00:00:02.481729 │ success │
│ 138587250590302 │ 0.26.0         │ 00:00:02.57566  │ success │
│ 138587250590302 │ 0.26.0         │ 00:00:04.728486 │ success │
│ 138587250590302 │ 0.26.0         │ 00:00:08.676203 │ success │
└─────────────────┴────────────────┴─────────────────┴─────────┘
```
