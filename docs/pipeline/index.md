# The pipeline

The pipeline
defines the processes that produce
the project's important artifacts.
It can either be written in Calkit's syntax in the `pipeline` object
of `calkit.yaml` or in
[DVC](https://dvc.org)'s syntax and stored in the `dvc.yaml` file.
If written in Calkit's syntax, a `dvc.yaml` file will be created at
run time and executed with DVC.

## Calkit pipeline syntax

Calkit's pipeline syntax defines `steps`,
each of which can have `inputs`, `outputs`, and a `kind` attribute
to indicate what kind of process is run,
e.g., a Python script, MATLAB script, R script, shell command, etc.

In the `calkit.yaml` file, you can define a `pipeline` like:

```yaml
pipeline:
  steps:
    collect-data:
      kind: python-script
      environment: main
      script: scripts/collect-data.py
      outputs:
        - data/raw.csv
        - path: data/raw.csv
          type: dataset
          title: The raw data
          description: Raw voltage, collected from the sensor.
          store_with: dvc
```

## DVC pipeline syntax

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
