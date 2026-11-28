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

After a stage with an output table runs,
`calkit run` prints how many rows went into and came out of it,
so rows lost along the way show without anyone looking, e.g.:

```
prepare-data: data/raw/participants.csv 480 rows, data/raw/sessions.csv 1,877 rows -> data/analysis.csv 395 rows (85 fewer than data/raw/participants.csv, 18%; site D: 36 -> 0 rows)
```

An output with fewer rows than the stage's smallest input table
is noted with how many fewer.
So is a group that has rows in an input but none in the output,
from a text column they share with up to 20 distinct values
that repeat, e.g., a site.
The counts are recorded under the stage's `rows` in
`.calkit/stage-runs.json`.
Only CSV and TSV files the stage lists as inputs and outputs are counted,
by their lines, a header less,
and only those up to 100 MB, or 2 MB for comparing groups,
so counting stays quick.
Parquet files are counted too if pyarrow is installed with Calkit.

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
