# Calkit agent guide

This document provides context for AI agents working in a Calkit project. It covers `calkit.yaml` structure, the pipeline model, environment conventions, and key CLI commands.

If you are using Claude Code with the Calkit plugin installed, these conventions are also available as skills: `/calkit:create-pipeline` and `/calkit:add-pipeline-stage`.

---

## What Calkit is

Calkit is a tool for research project management, with a focus on automation and reproducibility—like continuous delivery for research. It wraps Git (source control) and DVC (data versioning), adds environment management, and provides a pipeline orchestration layer. The single source of truth for the project is `calkit.yaml`.

---

## The `calkit.yaml` file

`calkit.yaml` lives at the repo root. Top-level sections:

| Section                                    | Purpose                                                     |
| ------------------------------------------ | ----------------------------------------------------------- |
| `environments`                             | Computational environments (Python, R, Julia, Docker, etc.) |
| `pipeline.stages`                          | The reproducible pipeline                                   |
| `notebooks`                                | Registered Jupyter notebooks                                |
| `datasets`, `figures`, `publications`      | Versioned project outputs                                   |
| `procedures`, `calculations`, `references` | Supporting metadata                                         |
| `showcase`                                 | Elements shown on the project's Calkit Cloud homepage       |

Example:

```yaml
environments:
  main:
    kind: uv-venv
    path: requirements.txt
    python: "3.13"
  texlive:
    kind: docker
    image: texlive/texlive:latest-full

pipeline:
  stages:
    collect-data:
      kind: python-script
      script_path: scripts/collect-data.py
      environment: main
      outputs:
        - data/raw.csv
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

---

## Environments

Every pipeline stage must reference a named environment from the `environments` section. Calkit generates a lock file for each environment and uses it as a DVC dependency—if the environment changes, affected stages are flagged for re-run.

Supported environment kinds:

| Kind      | Spec file                              |
| --------- | -------------------------------------- |
| `uv-venv` | `requirements.txt` or `pyproject.toml` |
| `venv`    | `requirements.txt`                     |
| `conda`   | `environment.yml`                      |
| `pixi`    | `pixi.toml`                            |
| `docker`  | image name (no local spec needed)      |
| `renv`    | `renv.lock`                            |
| `julia`   | `Project.toml`                         |
| `matlab`  | (no spec file)                         |
| `ssh`     | remote host config                     |
| `slurm`   | HPC cluster config                     |

---

## Pipeline stages

Stages live under `pipeline.stages`. Every stage requires `kind` and `environment`.

### Common parameters

| Parameter      | Type   | Notes                                              |
| -------------- | ------ | -------------------------------------------------- |
| `kind`         | string | Required. Stage type.                              |
| `environment`  | string | Required. Must match a key in `environments`.      |
| `inputs`       | list   | Files read by this stage. Changes trigger re-run.  |
| `outputs`      | list   | Files written by this stage. Stored in Git or DVC. |
| `wdir`         | string | Working directory (relative to repo root).         |
| `always_run`   | bool   | Force re-run even if nothing changed.              |
| `iterate_over` | list   | Parameterize over a list of values.                |
| `description`  | string | Human-readable description.                        |

### Stage kinds

**`python-script`**

```yaml
kind: python-script
script_path: scripts/run.py
args: ["--flag", "value"] # optional
```

**`jupyter-notebook`**

```yaml
kind: jupyter-notebook
notebook_path: notebooks/analysis.ipynb
html_storage: git # optional, default: dvc
executed_ipynb_storage: git # optional, default: dvc
parameters: { key: value } # optional, papermill parameters
```

**`shell-command`**

```yaml
kind: shell-command
command: "python -m mymodule --arg val"
shell: bash # optional, default: bash
```

**`shell-script`**

```yaml
kind: shell-script
script_path: scripts/run.sh
```

**`latex`**

```yaml
kind: latex
target_path: paper/paper.tex
pdf_storage: git # optional, default: dvc
```

**`r-script`**

```yaml
kind: r-script
script_path: scripts/analysis.R
```

**`julia-script`** / **`julia-command`**

```yaml
kind: julia-script
script_path: scripts/run.jl
```

**`matlab-script`** / **`matlab-command`**

```yaml
kind: matlab-script
script_path: scripts/run.m
```

**`docker-command`**

```yaml
kind: docker-command
command: "docker run --rm myimage mycommand"
```

**`command`** (generic)

```yaml
kind: command
command: "mytool --input data/raw.csv --output data/out.csv"
```

### Output storage

Default storage is DVC (large file cache). Use `storage: git` for small files that should be committed:

```yaml
outputs:
  - data/large-dataset.csv # DVC (default)
  - path: data/meta.json
    storage: git # committed to Git
  - path: results/summary.txt
    storage: git
    delete_before_run: false # keep old version if not re-run
```

### Dependencies between stages

```yaml
inputs:
  - from_stage_outputs: collect-data # depend on all outputs of collect-data
```

### Iteration over parameters

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

---

## Relationship to DVC

Calkit compiles `calkit.yaml` into `dvc.yaml` when `calkit run` is called. **Do not edit `dvc.yaml` directly**—it is a generated file. Always edit `calkit.yaml`.

DVC handles:

- Caching: unchanged stages are skipped
- Remote storage: large files pushed/pulled with `calkit push` / `calkit pull`
- Dependency graph: run order computed from declared inputs/outputs

---

## Key CLI commands

| Command                         | What it does                                                          |
| ------------------------------- | --------------------------------------------------------------------- |
| `calkit run`                    | Run the pipeline (skips unchanged stages)                             |
| `calkit run --force`            | Force re-run all stages                                               |
| `calkit run <stage>`            | Run a specific stage                                                  |
| `calkit status`                 | Show which stages are stale                                           |
| `calkit xr <file>`              | Execute-and-record: auto-detect stage type, env, I/O, add to pipeline |
| `calkit xr <file> --dry-run`    | Preview what xr would do without changing anything                    |
| `calkit xenv -n <env> -- <cmd>` | Run a command in a named environment                                  |
| `calkit push`                   | Push Git commits and DVC-tracked files to remotes                     |
| `calkit pull`                   | Pull latest code and data                                             |
| `calkit sync`                   | Pull then push                                                        |
| `calkit commit -m "msg"`        | Commit all tracked changes (Git + DVC)                                |
| `calkit add <file>`             | Add a file to version control                                         |
| `calkit check env --name <env>` | Verify an environment matches its spec                                |
| `calkit new`                    | Create new project objects (notebook, dataset, etc.)                  |
| `calkit init`                   | Initialize DVC and project structure                                  |

---

## `calkit xr`—fastest path to a reproducible stage

`xr` ("execute and record") auto-detects stage kind from the file extension, finds or creates an environment, heuristically detects I/O, adds the stage to `calkit.yaml`, and runs it.

```bash
calkit xr scripts/run.py            # Python script
calkit xr notebooks/analysis.ipynb  # Jupyter notebook
calkit xr paper/paper.tex           # LaTeX document
calkit xr scripts/analysis.R        # R script

# Preview without changing anything
calkit xr scripts/run.py --dry-run

# Override detected I/O
calkit xr scripts/run.py \
  --input data/raw.csv \
  --output results/out.csv

# Specify environment explicitly
calkit xr scripts/run.py --environment main
```

I/O detection is strongest for Python, R, Julia scripts, notebooks, LaTeX includes, and shell redirections. It is less reliable when paths are constructed at runtime. Always verify detected I/O after running `xr`.

---

## Version control conventions

- Source code and small outputs: tracked with Git
- Large binary files and datasets: tracked with DVC
- Environment lock files (`.calkit/env-locks/`): committed to Git, used as DVC dependencies
- `dvc.yaml`: generated by Calkit—don't edit manually
- `.calkit/`: Calkit's internal directory—commit its contents unless they are large generated files

---

## Common mistakes

- **Missing intermediate dependencies**: if stage B reads a file that stage A writes, A's output must be listed as B's input. Otherwise DVC won't enforce the right run order.
- **Hard-coded absolute paths**: scripts should use paths relative to the repo root (or `wdir`).
- **Editing `dvc.yaml` directly**: always edit `calkit.yaml` instead.
- **Using an undefined environment name**: the `environment` value must exactly match a key in the `environments` section.
- **Two stages writing the same file**: each output file can belong to only one stage.
