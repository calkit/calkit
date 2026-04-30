---
name: add-pipeline-stage
description: Add a single new stage to an existing Calkit pipeline. Use when
  the user invokes `/calkit:add-pipeline-stage` or asks to add a script,
  notebook, or command to the pipeline.
---

# Add a pipeline stage

Add a single new stage to an existing Calkit pipeline — wiring up the right
environment, inputs, outputs, and storage mode.

## Before you start

Read `calkit.yaml` to understand what environments are already defined (you
will reuse one if it fits) and what stages already exist and what they output
(your new stage may depend on them).

## Option A — Add with `calkit xr`

Use `xr` when the stage is a script or notebook file (`.py`, `.ipynb`, `.R`,
`.jl`, `.m`, `.sh`, `.tex`) and you want auto-detection of I/O and
environment.

```bash
calkit xr scripts/new-stage.py --dry-run   # preview first
calkit xr scripts/new-stage.py             # run for real
```

Override detected I/O or environment if needed:

```bash
calkit xr scripts/new-stage.py \
  --input data/processed.csv \
  --input config/params.yaml \
  --output results/output.csv \
  --environment main
```

After running, inspect the new stage in `calkit.yaml` to confirm I/O is
correct.

## Option B — Write the stage manually

Write YAML directly when the stage is a shell command, or when you need
`iterate_over`, specific storage modes, or other fine-grained control.

| File type        | Stage kind                   |
| ---------------- | ---------------------------- |
| `.py`            | `python-script`              |
| `.ipynb`         | `jupyter-notebook`           |
| `.sh`            | `shell-script`               |
| Inline command   | `shell-command` or `command` |
| `.tex`           | `latex`                      |
| `.R`             | `r-script`                   |
| `.jl`            | `julia-script`               |
| `.m`             | `matlab-script`              |
| `docker run ...` | `docker-command`             |

```yaml
pipeline:
  stages:
    # ... existing stages ...

    new-stage-name:
      kind: python-script
      script_path: scripts/new-stage.py
      environment: main # must match a key in environments:
      inputs:
        - data/processed.csv
      outputs:
        - results/output.csv
```

## Wiring dependencies

If the new stage reads files produced by an existing stage, declare them as
inputs. List files explicitly, or depend on all outputs of a prior stage:

```yaml
inputs:
  - data/processed.csv # explicit file
  - from_stage_outputs: process-data # all outputs of that stage
```

If an existing stage reads files your new stage now produces, update that
stage's inputs too.

## Output storage

- `git` — small or text files collaborators should see without `calkit pull`
  (PDFs, summary CSVs, HTML reports)
- `dvc` (default) — large or binary files

```yaml
outputs:
  - results/large-matrix.npy # DVC (default)
  - path: results/summary.csv
    storage: git
  - path: results/report.html
    storage: git
    delete_before_run: false # keep old version if stage is skipped
```

## After adding the stage

```bash
calkit run                                    # run full pipeline
calkit run new-stage-name                     # run only this stage
calkit status                                 # check what's stale
calkit commit -m "Add new-stage-name stage"
```

## Common mistakes

- **Wrong environment name**: must exactly match a key in `environments`. Run
  `calkit check env --name <env>` to verify.
- **Two stages claiming the same output**: each file can only be the output of
  one stage.
- **Missing inputs**: if a stage reads a file but doesn't declare it, DVC
  won't re-run the stage when that file changes.
- **Editing `dvc.yaml`**: don't — it's auto-generated from `calkit.yaml`.
