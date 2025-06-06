# The pipeline

The pipeline
defines the processes that produce
the project's important assets or artifacts, such as datasets,
figures, tables, and publications.
It is saved in the `pipeline` section of the `calkit.yaml` file,
and is compiled to a [DVC](https://dvc.org) pipeline (saved in `dvc.yaml`)
when `calkit run` is called.

A pipeline is composed of stages,
each of which has a specific type or "kind."
Each stage must specify the environment in which it runs to ensure it's
reproducible.
Calkit will automatically generate a "lock file" at the start of running
and can therefore automatically detect if an environment has changed,
and the affected stages need to be rerun.
Stages can also define `inputs` and `outputs`,
and you can decide how you'd like outputs to be stored, i.e., with Git or DVC.

In the `calkit.yaml` file, you can define a `pipeline`
(and `environments`) like:

```yaml
# Define environments
environments:
  main:
    kind: uv-venv
    path: requirements.txt
    python: "3.13"
# Define the pipeline
pipeline:
  stages:
    collect-data:
      kind: python-script
      script_path: scripts/collect-data.py
      environment: main
      outputs:
        - data/raw.csv
        - path: data/meta.json
          storage: git
          delete_before_run: false
```

## Stage types and unique attributes

All stage declarations require a `kind` and an `environment`,
and can specify `inputs` and `outputs`.
The different kinds of stages and their unique attributes are listed below.
For more details, see `calkit.models.pipeline`.

- `python-script`
  - `script_path`
  - `args` (list, optional)
- `shell-command`
  - `command`
  - `shell` (optional, e.g., `bash`, `sh`, `zsh`, etc., default `bash`)
- `shell-script`
  - `script_path`
  - `shell` (optional, e.g., `bash`, `sh`, `zsh`, etc., default `bash`)
  - `args` (list, optional)
- `matlab-script`
  - `script_path`
- `latex`
  - `target_path`
- `docker-command`
  - `command`
- `r-script`
  - `script_path`
  - `args` (list, optional)

## Iteration

### Over a list of values

```yaml
pipeline:
  stages:
    my-iter-stage:
      kind: python-script
      script_path: scripts/my-script.py
      args:
        - "--model={var}"
      iterate_over:
        - arg_name: var
          values:
            - some-model
            - some-other-model
      inputs:
        - data/raw
      outputs:
        - models/{var}.h5
```

### Over ranges of numbers

```yaml
pipeline:
  stages:
    my-iter-stage:
      kind: python-script
      script_path: scripts/my-script.py
      args:
        - "--thresh={thresh}"
      iterate_over:
        - arg_name: thresh
          values:
            - range:
                start: 0
                stop: 20
                step: 0.5
            - range:
                start: 30
                stop: 35
                step: 1
            - 41
      inputs:
        - data/raw
      outputs:
        - results/{thresh}.csv
```
