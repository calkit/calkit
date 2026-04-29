# Add a pipeline stage

**Trigger:** `/calkit:add-pipeline-stage`

Add a single new stage to an existing Calkit pipeline correctly — wiring up the right environment, inputs, outputs, and storage mode.

## Before you start

Read `calkit.yaml` to understand:

- What environments are already defined (you'll reuse one if it fits)
- What stages already exist and what they output (your new stage may depend on them)

```bash
cat calkit.yaml
```

## Decide on the approach: `xr` or manual YAML

**Use `calkit xr` when:**

- The stage is a script or notebook file (`.py`, `.ipynb`, `.R`, `.jl`, `.m`, `.sh`, `.tex`)
- You want auto-detection of I/O and environment

**Write YAML manually when:**

- The stage is a shell command or compound command (not a file)
- You need `iterate_over`, specific `storage` modes, or other fine-grained control
- `xr` detected the wrong I/O

## Option A: Add with `calkit xr`

```bash
# Dry run first — see what xr would create without changing anything
calkit xr scripts/new-stage.py --dry-run

# Run for real when the dry run looks correct
calkit xr scripts/new-stage.py
```

Override detected I/O if needed:

```bash
calkit xr scripts/new-stage.py \
  --input data/processed.csv \
  --input config/params.yaml \
  --output results/output.csv
```

Specify an existing environment if auto-detection picks the wrong one:

```bash
calkit xr scripts/new-stage.py --environment main
```

After running, inspect the new stage in `calkit.yaml` to confirm inputs and outputs are correct.

## Option B: Write the stage in `calkit.yaml` manually

Add a new entry under `pipeline.stages`. Determine the stage kind from the script type:

| Script type      | Stage kind                   |
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

Minimal template for a Python script stage:

```yaml
pipeline:
  stages:
    # ... existing stages ...

    new-stage-name:
      kind: python-script
      script_path: scripts/new-stage.py
      environment: main # must match a key in environments:
      inputs:
        - data/processed.csv # files read by this script
      outputs:
        - results/output.csv # files written by this script
```

## Wiring dependencies correctly

**If the new stage reads files produced by an existing stage**, declare them as inputs. You have two options:

1. List files explicitly (use when you only need some of the prior stage's outputs):

```yaml
inputs:
  - data/processed.csv
```

2. Depend on everything from a prior stage (use when you need all of its outputs):

```yaml
inputs:
  - from_stage_outputs: process-data
```

**If an existing stage reads files that your new stage will now produce**, update that stage's inputs too.

## Choose output storage

For each output:

- `git` — small or text files that collaborators should see without `calkit pull`. Examples: PDFs, summary CSVs, HTML reports.
- `dvc` (default) — large or binary files that go into the DVC cache.

```yaml
outputs:
  - results/large-matrix.npy # DVC (default)
  - path: results/summary.csv
    storage: git # commit to Git
  - path: results/report.html
    storage: git
    delete_before_run: false # keep old version if stage doesn't re-run
```

## After adding the stage

Run the pipeline to verify the new stage works:

```bash
calkit run
```

To run only the new stage (and any stages it depends on):

```bash
calkit run new-stage-name
```

Check pipeline status:

```bash
calkit status
```

Commit when it works:

```bash
calkit commit -m "Add new-stage-name stage"
```

## Common mistakes

- **Wrong environment name**: the `environment` value must exactly match a key in the `environments` section. Run `calkit check env --name <env>` to verify.
- **Declaring an output that another stage already owns**: each file can only be the output of one stage. If two stages write the same file, restructure.
- **Missing inputs**: if a stage reads a file but doesn't declare it as an input, DVC won't re-run the stage when that file changes.
- **Editing `dvc.yaml`**: don't. It's auto-generated from `calkit.yaml`.
