# Running and logging

When the pipeline is run with the `calkit run` command,
Calkit will first compile the pipeline into a DVC pipeline with
some additional stages to handle environment checking.

Calkit also collects important system information such as
foundational dependency versions to log for the sake of
traceability and saves to JSON files in `.calkit/systems`.

While the run is executing, DVC logs will be sent into `.calkit/logs`
and after it's complete, run metadata will be saved to a JSON file in
`.calkit/runs`.
Again, these can be helpful for traceability and
diagnosing reproducibility issues down
the road, e.g., if the project is being run on multiple machines and
the results are different between them.

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
            from '.calkit/runs/*.json' run
            left join '.calkit/systems/*.json' system
                on run.system_id = system.id
            where run.dvc_args = '[]'
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
