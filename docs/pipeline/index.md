# The pipeline

The pipeline, implemented with
[DVC](https://dvc.org) and stored in the `dvc.yaml` file,
defines the processes that produce
the project's important artifacts.

The command, or `cmd` key, for each stage should typically
include the `calkit xenv` command,
such that every process is executed in a defined environment.
This way,
Calkit will ensure the environment matches its specification
before execution.

If a stage has a single output,
it is also possible to define what type of Calkit object it
produces.
For example, the stage below `collect-data` produces a dataset.
When executing `calkit run` this will automatically be
added to the datasets list in the `calkit.yaml` file,
allowing other users to search for and use this dataset in their
own work.

```yaml
stages:
  collect-data:
    cmd: calkit xenv -n main -- python scripts/collect-data.py
    deps:
      - scripts/collect-data.py
    outs:
      - data/raw.csv
    meta:
      calkit:
        type: dataset
        title: The raw data
        description: Raw voltage, collected from the sensor.
```

To learn more, see
[DVC's pipeline documentation](https://dvc.org/doc/start/data-pipelines/data-pipelines).
