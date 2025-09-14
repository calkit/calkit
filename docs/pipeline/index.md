# The pipeline

The pipeline
defines and ties together the processes that produce
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

Any stages that have not changed since they were last run will be skipped,
since their results will have been cached.

In the `calkit.yaml` file, you can define a `pipeline`
(and `environments`) like:

```yaml
# Define environments
environments:
  main:
    kind: uv-venv
    path: requirements.txt
    python: "3.13"
  texlive:
    kind: docker
    image: texlive/texlive:latest-full

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
    process-data:
      kind: jupyter-notebook
      notebook_path: notebooks/process.ipynb
      environment: main
      inputs:
        - data/raw.csv
      outputs:
        - data/processed.csv
        - figures/fig1.png
    build-paper:
      kind: latex
      target_path: paper/paper.tex
      environment: texlive
      inputs:
        - figures/fig1.png
        - references.bib
```

## Stage types and unique attributes

All stage declarations require a `kind` and an `environment`,
and can specify `inputs` and `outputs`.
The different kinds of stages and their unique attributes are listed below.
For more details, see `calkit.models.pipeline`.

### `python-script`

- `script_path`
- `args` (list, optional)

### `shell-command`

- `command`
- `shell` (optional, e.g., `bash`, `sh`, `zsh`; default: `bash`)

### `shell-script`

- `script_path`
- `shell` (optional, e.g., `bash`, `sh`, `zsh`; default: `bash`)
- `args` (list, optional)

### `matlab-script`

- `script_path`

### `latex`

- `target_path`

### `docker-command`

- `command`

### `r-script`

- `script_path`
- `args` (list, optional)

### `julia-script`

- `script_path`

### `julia-command`

- `command`

### `sbatch`

- `script_path`
- `args`
- `sbatch_options`

This stage type runs a script with `sbatch`, which is a common way to run
jobs on a high performance computing (HPC) cluster that uses the SLURM
job scheduler.

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

### Over a table (or list of lists)

```yaml
pipeline:
  stages:
    my-iter-stage:
      kind: python-script
      script_path: scripts/my-script.py
      args:
        - "--model={var1}"
        - "--n_estimators={var2}"
      iterate_over:
        - arg_name: [var1, var2]
          values:
            - [some-model, 5]
            - [some-other-model, 7]
      inputs:
        - data/raw
      outputs:
        - models/{var1}-{var2}.h5
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
