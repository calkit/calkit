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

- `requirements`—what must be true of the machine before anything runs
  (apps on `PATH`, environmental variables, setup steps, machine
  properties like CPU count); formerly called `dependencies`, which
  still works
- `environments`—computational environments (Python venvs, Conda, Docker,
  R, Julia, MATLAB, etc.)
- `pipeline.stages`—the reproducible pipeline
- `questions`—research questions, hypotheses, and answers backed by
  evidence the pipeline produces
- `notebooks`—registered Jupyter notebooks
- `datasets`, `figures`, `publications`—versioned project outputs
- `procedures`, `calculations`, `references`—supporting metadata
- `showcase`—elements shown on the project's Calkit homepage

A minimal example:

```yaml
environments:
  main:
    kind: uv
    path: pyproject.toml

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
| `uv`      | `pyproject.toml` (with `uv.lock`)       |
| `uv-venv` | `requirements.txt`                      |
| `venv`    | `requirements.txt`                      |
| `conda`   | `environment.yml`                       |
| `pixi`    | `pixi.toml`                             |
| `docker`  | (image name, no local spec file needed) |
| `texlive` | (TeX Live packages, listed in the env)  |
| `renv`    | `renv.lock`                             |
| `julia`   | `Project.toml`                          |
| `matlab`  | (no spec file)                          |
| `ssh`     | (remote host config)                    |
| `slurm`   | (HPC cluster config)                    |

For Python, default to a `uv` project environment, created with
`calkit new uv-env -n <name> <packages>`, which writes `pyproject.toml` and
`uv.lock`; set the Python version with `--python`, which becomes
`requires-python`. Use `uv-venv` only for a project that already has a
`requirements.txt` it should keep.

<!-- TODO: needs human review -->

For LaTeX, default to a `texlive` environment, created with
`calkit new texlive-env`, which needs no Docker. A build adds the packages
a document needs to the environment's lock.

Example environment definitions:

```yaml
environments:
  py:
    kind: uv
    path: pyproject.toml

  tex:
    kind: texlive
    release: 2025

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

See the `calkit.yaml` schema for details.
The most common stage kinds are `python-script`, `shell-script`, `shell-command`,
`jupyter-notebook`.

<!-- TODO: needs human review -->

### LaTeX documents

A document built by a `latex` stage includes pipeline outputs by their
path in the project with the `calkit` package:

```latex
\usepackage{calkit}
...
The error falls to \ckvalue[.2f]{results/metrics.json}{rmse}.
\ckfigure[width=0.7\linewidth]{figures/plot.png}
\cktable{tables/summary.tex}
```

The stage depends on everything included this way, so don't add
`json-to-latex` or `map-paths` stages, or list those files in `inputs`.

<!-- TODO: needs human review -->

### Values, figures, and tables from notebook cells

A `jupyter-notebook` stage can save values, figures, and tables from its
cells, so the notebook doesn't need to write files.
Offer this to anyone who'd rather not add `json.dump` or `savefig` calls.
Add them with `calkit nb add-output`, which stores them under the stage's
`cell_outputs` by cell ID.
Read IDs from the `.ipynb`, or use `--cell-index`, which adds IDs if the
notebook has none.

```sh
calkit nb add-output analysis.ipynb value --cell-id 3f9a1c2e --variable-name k_25 --variable-name k_35
calkit nb add-output analysis.ipynb figure --cell-id 8b77d0aa --variable-name fig --output-path figures/fit.pdf
calkit nb add-output analysis.ipynb table --cell-id 1d2e4c0b --variable-name df --output-path tables/rates.tex
calkit nb outputs analysis.ipynb --json
```

Cite a value with the notebook's path, e.g.,
`\ckvalue[.3f]{analysis.ipynb}{k_25}`, or `{rates.25C}` for a key in a
dict.
Cite figures and tables by their paths.
Each output is saved right after its cell runs,
so if a later cell changes the variable, the saved one doesn't change.
Outputs are only saved when the pipeline runs the notebook,
so run `calkit run` after adding them.
`calkit nb remove-output` stops saving one.
Don't also list a saved figure or table in the stage's `outputs`.

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
  - path: results/runs
    storage: git
    ignore: ["*.log"] # neither stored nor part of the output
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

| Command                         | What it does                                            |
| ------------------------------- | ------------------------------------------------------- |
| `calkit run`                    | Run the pipeline (skips unchanged stages)               |
| `calkit run --force`            | Force re-run all stages                                 |
| `calkit status`                 | Show which stages are stale                             |
| `calkit xr <file>`              | Auto-detect stage type, env, I/O, add to pipeline       |
| `calkit xenv -n <env> -- <cmd>` | Run a command in a named environment                    |
| `calkit shell -e <env>`         | Open an interactive shell with an environment activated |
| `calkit push`                   | Push Git commits and DVC-tracked files to remotes       |
| `calkit pull`                   | Pull latest code and data                               |
| `calkit save`                   | Auto-add, commit, and push (Git + DVC)                  |
| `calkit commit -m "msg"`        | Commit all tracked changes (Git + DVC)                  |
| `calkit add <file>`             | Add a file to version control                           |
| `calkit check env --name <env>` | Verify an environment matches its spec                  |
| `calkit new`                    | Create new project objects (notebook, dataset, etc.)    |
| `calkit new question "<text>"`  | Record a research question                              |
| `calkit list questions`         | List questions with what each has and lacks             |
| `calkit show question <n>`      | Show a question with its answer rendered from evidence  |
| `calkit check questions`        | Check answers against current evidence                  |

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

## Questions and answers

Research in a Calkit project is organized around the `questions` list in
`calkit.yaml`. Follow this workflow:

1. Before starting an analysis, make sure the question it answers is
   recorded, e.g., with `calkit new question`. If the user hasn't stated
   one, ask them for it rather than inventing it. Add a `hypothesis` if
   they have one.
2. Produce evidence with pipeline stages, never by hand, so every figure,
   table, and number traces back to data and code.
3. Write the `answer` citing that evidence. Read numbers out of results
   files and put them in the prose with `{name}` placeholders instead of
   typing them in, either one per `kind: value` entry, or several from one
   file with a `kind: result` entry's `values` mapping of names to keys.
4. After a pipeline run changes results, run `calkit check questions`,
   then use the `check-questions` skill to judge whether each answer's
   wording still follows from its evidence.

See the Calkit docs on questions for the full evidence schema.

## Version control conventions

- Source code and small outputs: tracked with Git
- Large binary files, datasets, model weights: tracked with DVC
- Lock files (`.calkit/env-locks/`): committed to Git, act as DVC dependencies
- `dvc.yaml`: generated by Calkit—don't edit manually
- `.calkit/`: Calkit's internal directory—commit its contents unless they
  are large generated files

## Papers synced with Overleaf

<!-- TODO: needs human review -->

A folder listed under `overleaf_sync` in `calkit.yaml` is linked to an
Overleaf project, where coauthors write.
After changing anything a paper shows, e.g., a figure, table, or value,
coauthors only see it once it's run, saved, and synced.
Unless the user has already said how they want this done,
ask whether to finish with:

```bash
calkit run --save --overleaf
```

This syncs with Overleaf, runs the pipeline, saves the project,
and syncs again, so coauthors see the update.
It's a good default for anyone who doesn't want fine-grained control over
their commit history.
If the user would rather make their own commits,
run `calkit run` and leave saving and syncing to them.
Don't copy outputs to Overleaf or edit them there by hand.
Don't edit a linked paper's source unless the user asks,
since coauthors may be writing in it,
and sync first with `calkit overleaf sync` when they do ask,
so their latest changes are kept.

## Provenance

Calkit's data model emphasizes provenance.
Any derived artifact (produced by a script, notebook, etc.) should be
produced by the pipeline so we can know if it's up-to-date w.r.t. its
inputs and process definition.
Imported artifacts should have attribution.
Primary artifacts should have attestation, including AI-generated content,
though the human is considered the author and AI is noted with a `with_ai` field.

<!-- TODO: needs human review -->

When asked "How did you calculate it?" about a result, figure, table, or
value, run `calkit show provenance <path>` (with `--key <key>` for one value,
and `--json` for every field) and start from what it prints, not from
memory, then read the source it names for the method.
