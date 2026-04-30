---
name: conventions
description: Calkit conventions and foundational context. Load whenever working
  in a Calkit project—defines calkit.yaml structure, environments, pipeline
  stages, CLI commands, and version control conventions.
---

# Calkit conventions

Calkit is a tool for research project management focused on automation and
reproducibility—enabling continuous delivery for research.
It provides a unified
interface over Git (source control) and DVC (data versioning), and adds
environment management and pipeline orchestration on top. The central artifact
is `calkit.yaml`, the project's metadata database.

## The `calkit.yaml` file

`calkit.yaml` lives at the repo root and contains:

- `environments`—computational environments (Python venvs, Conda, Docker,
  R, Julia, MATLAB, etc.)
- `pipeline.stages`—the reproducible pipeline
- `notebooks`—registered Jupyter notebooks
- `datasets`, `figures`, `publications`—versioned project outputs
- `procedures`, `calculations`, `references`—supporting metadata
- `showcase`—elements shown on the project's Calkit Cloud homepage

A minimal example:

```yaml
environments:
  main:
    kind: uv-venv
    path: requirements.txt
    python: "3.13"

pipeline:
  stages:
    process-data:
      kind: python-script
      script_path: scripts/process.py
      environment: main
      inputs:
        - data/raw.csv
      outputs:
        - data/processed.csv
```

## Environments

Every pipeline stage must reference a named environment defined in
`environments`. Calkit enforces this to ensure reproducibility. Supported
kinds:

| Kind      | Spec file                               |
| --------- | --------------------------------------- |
| `uv-venv` | `requirements.txt` or `pyproject.toml`  |
| `venv`    | `requirements.txt`                      |
| `conda`   | `environment.yml`                       |
| `pixi`    | `pixi.toml`                             |
| `docker`  | (image name, no local spec file needed) |
| `renv`    | `renv.lock`                             |
| `julia`   | `Project.toml`                          |
| `matlab`  | (no spec file)                          |
| `ssh`     | (remote host config)                    |
| `slurm`   | (HPC cluster config)                    |

Example environment definitions:

```yaml
environments:
  main:
    kind: uv-venv
    path: requirements.txt
    python: "3.13"

  texlive:
    kind: docker
    image: texlive/texlive:latest-full

  r-env:
    kind: renv
    path: renv.lock
```

Calkit generates a lock file for each environment under `.calkit/env-locks/`
and uses it as a DVC dependency. If the environment changes, affected stages
are automatically flagged for re-run.

## Pipeline stages

Stages live under `pipeline.stages` in `calkit.yaml`. Every stage requires
`kind` and `environment`. Most stages also declare `inputs` and `outputs`.

### Common parameters (all stage kinds)

| Parameter      | Type   | Notes                                           |
| -------------- | ------ | ----------------------------------------------- |
| `kind`         | string | Required. See stage kinds below.                |
| `environment`  | string | Required. Must match a key in `environments`.   |
| `inputs`       | list   | Files this stage reads. Changes trigger re-run. |
| `outputs`      | list   | Files this stage writes. Stored in Git or DVC.  |
| `wdir`         | string | Working directory (relative to repo root).      |
| `always_run`   | bool   | Force re-run even if nothing changed.           |
| `iterate_over` | list   | Parameterize the stage over a list of values.   |
| `description`  | string | Human-readable description.                     |

### Stage kinds and their required fields

**`python-script`**—run a Python script

```yaml
kind: python-script
script_path: scripts/run.py
args: ["--flag", "value"] # optional
```

**`jupyter-notebook`**—execute a Jupyter notebook

```yaml
kind: jupyter-notebook
notebook_path: notebooks/analysis.ipynb
html_storage: git # optional, default: dvc
executed_ipynb_storage: git # optional, default: dvc
parameters: { key: value } # optional, papermill parameters
```

**`shell-command`**—run an arbitrary shell command

```yaml
kind: shell-command
command: "python -m mymodule --arg val"
shell: bash # optional, default: bash
```

**`shell-script`**—run a shell script file

```yaml
kind: shell-script
script_path: scripts/run.sh
```

**`latex`**—compile a LaTeX document to PDF

```yaml
kind: latex
target_path: paper/paper.tex
pdf_storage: git # optional, default: dvc
```

**`r-script`**—run an R script

```yaml
kind: r-script
script_path: scripts/analysis.R
```

**`julia-script`** / **`julia-command`**—run Julia code

```yaml
kind: julia-script
script_path: scripts/run.jl
```

**`matlab-script`** / **`matlab-command`**—run MATLAB code

```yaml
kind: matlab-script
script_path: scripts/run.m
```

**`docker-command`**—run a command inside a Docker container

```yaml
kind: docker-command
command: "docker run --rm myimage mycommand"
```

**`command`**—generic command (for tools that don't fit other kinds)

```yaml
kind: command
command: "mytool --input data/raw.csv --output data/out.csv"
```

### Outputs: Git vs. DVC storage

By default, outputs are stored with DVC (large file storage). Use
`storage: git` for small files that belong in version control:

```yaml
outputs:
  - data/processed.csv # DVC (default)
  - path: data/meta.json
    storage: git # committed to Git
  - path: results/summary.txt
    storage: git
    delete_before_run: false # don't delete before re-running
```

### Declaring dependencies between stages

Use `from_stage_outputs` to declare that a stage depends on another stage's
outputs rather than listing individual files:

```yaml
stages:
  collect-data:
    kind: python-script
    script_path: scripts/collect.py
    environment: main
    outputs:
      - data/raw.csv

  process-data:
    kind: python-script
    script_path: scripts/process.py
    environment: main
    inputs:
      - from_stage_outputs: collect-data
    outputs:
      - data/processed.csv
```

### Iterating over parameters

```yaml
stages:
  train-model:
    kind: python-script
    script_path: scripts/train.py
    environment: main
    args:
      - "--model={model}"
    iterate_over:
      - arg_name: model
        values:
          - linear-regression
          - random-forest
    inputs:
      - data/processed.csv
    outputs:
      - models/{model}.pkl
```

## Relationship to DVC

Calkit compiles `calkit.yaml` into `dvc.yaml` when `calkit run` is called.
Do not edit `dvc.yaml` directly—it is a generated file. The authoritative
pipeline definition is always `calkit.yaml`.

DVC handles:

- Caching: stages that haven't changed since last run are skipped
- Remote storage: large files pushed/pulled with `calkit push` / `calkit pull`
- Dependency graph: run order is computed from declared inputs/outputs

## Key CLI commands

| Command                         | What it does                                         |
| ------------------------------- | ---------------------------------------------------- |
| `calkit run`                    | Run the pipeline (skips unchanged stages)            |
| `calkit run --force`            | Force re-run all stages                              |
| `calkit status`                 | Show which stages are stale                          |
| `calkit xr <file>`              | Auto-detect stage type, env, I/O, add to pipeline    |
| `calkit xenv -n <env> -- <cmd>` | Run a command in a named environment                 |
| `calkit push`                   | Push Git commits and DVC-tracked files to remotes    |
| `calkit pull`                   | Pull latest code and data                            |
| `calkit save`                   | Auto-add, commit, and push (Git + DVC)               |
| `calkit commit -m "msg"`        | Commit all tracked changes (Git + DVC)               |
| `calkit add <file>`             | Add a file to version control                        |
| `calkit check env --name <env>` | Verify an environment matches its spec               |
| `calkit new`                    | Create new project objects (notebook, dataset, etc.) |

## `calkit xr`: The fastest path to a reproducible stage

`xr` ("execute and record") is the recommended way to add scripts and
notebooks to the pipeline for the first time. It:

1. Detects the stage kind from the file extension (`.py`, `.ipynb`, `.R`,
   `.jl`, `.m`, `.sh`, `.tex`)
2. Detects or creates the right environment
3. Heuristically detects inputs and outputs from the script's file I/O calls
4. Adds the stage to `calkit.yaml` and `dvc.yaml`
5. Runs the stage

```bash
calkit xr scripts/run.py              # Python script
calkit xr notebooks/analysis.ipynb    # Jupyter notebook
calkit xr paper/paper.tex             # LaTeX document
calkit xr scripts/run.R               # R script

calkit xr scripts/run.py --input data/raw.csv --output results/out.csv
calkit xr scripts/run.py --environment main
calkit xr scripts/run.py --dry-run    # see what would happen without running
```

## Version control conventions

- Source code and small outputs: tracked with Git
- Large binary files, datasets, model weights: tracked with DVC
- Lock files (`.calkit/env-locks/`): committed to Git, act as DVC dependencies
- `dvc.yaml`: generated by Calkit—don't edit manually
- `.calkit/`: Calkit's internal directory—commit its contents unless they
  are large generated files
