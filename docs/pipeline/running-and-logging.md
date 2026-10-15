# Running and logging

When the pipeline is run with the `calkit run` command,
Calkit will first compile the pipeline into a DVC pipeline
with its dependencies set based on [environment](../environments.md)
lock files, such that a change in an environment causes a rerun.

Each successfully completed stage is recorded in
`.calkit/stage-runs.json`, which is intended to be committed
to the project's Git repository.
This records when it ran, in which environment
(and which option any `switch` environment used),
with which version of Calkit,
and on which machine.
The entry is replaced each time the stage runs,
so the file describes how the current outputs were made,
and its Git history is the stage's run history.
It also records the commit the run started from,
whether there were uncommitted changes,
and a checksum of the stage's `dvc.lock` entry after it ran.
`calkit check stage-runs` reports any stage whose `dvc.lock` entry
doesn't match its recorded run,
e.g., after `dvc commit` of an edited output.

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
