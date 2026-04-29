# Create a Calkit pipeline

**Trigger:** `/calkit:create-pipeline`

Convert an existing repo with ad hoc scripts and manual steps into a fully reproducible Calkit pipeline. After this skill completes, running `calkit run` should reproduce all important outputs from scratch.

## When to use this skill

Use this when:

- The project has scripts or notebooks that are run manually, in no enforced order
- There is no `pipeline` section in `calkit.yaml` yet (or no `calkit.yaml` at all)
- The goal is to make the project reproducible end-to-end

## Step 1 — Understand the existing repo

Before writing any YAML, map out what's already there.

1. List all scripts and notebooks: look in common locations (`scripts/`, `notebooks/`, `src/`, root `.py`/`.R`/`.jl`/`.m`/`.ipynb` files)
2. Read each script to understand what it reads and writes
3. Identify the dependency order: which outputs of script A become inputs to script B?
4. Note which environment each script needs (Python version, packages, R, Julia, MATLAB, Docker, etc.)

Ask the user if the order or dependencies are unclear. Do not guess at data flow.

## Step 2 — Check or initialize the project

If there is no `calkit.yaml`, initialize the project first:

```bash
calkit init
```

This sets up Git (if needed) and DVC. Check the result:

```bash
ls calkit.yaml dvc.yaml .dvc/ 2>/dev/null
```

If `calkit.yaml` already exists but has no `pipeline` section, that's fine — you will add one.

## Step 3 — Define environments

Every stage must reference a named environment. Identify the distinct environments needed:

- **Python projects**: does the repo have `requirements.txt`, `pyproject.toml`, or `environment.yml`? Use `uv-venv` or `conda`.
- **R projects**: does it have `renv.lock` or `DESCRIPTION`? Use `renv`.
- **Julia projects**: does it have `Project.toml`? Use `julia`.
- **LaTeX**: use `docker` with `texlive/texlive:latest-full` unless the user has a preference.
- **MATLAB**: use `matlab`.

Add environments to `calkit.yaml`:

```yaml
environments:
  main:
    kind: uv-venv
    path: requirements.txt
    python: "3.13"
```

If there is only one Python environment needed, name it `main`. If there are multiple (e.g., one for analysis and one for paper-building), give them descriptive names.

## Step 4 — Try `calkit xr` for the fast path

For each script or notebook, try `calkit xr` first before writing YAML by hand. It auto-detects stage kind, environment, and I/O:

```bash
# Dry run first to see what it would do
calkit xr scripts/collect-data.py --dry-run

# If the dry run looks correct, run for real
calkit xr scripts/collect-data.py
```

Work through scripts in dependency order (inputs before outputs). After each `xr` call, verify the stage was added to `calkit.yaml` correctly and that detected I/O matches what you found in Step 1.

If `xr` misses inputs or outputs, add them explicitly:

```bash
calkit xr scripts/train.py \
  --input data/processed.csv \
  --input config/params.yaml \
  --output models/model.pkl
```

## Step 5 — Write stages manually when `xr` isn't suitable

Write stages directly in `calkit.yaml` when:

- The script is a shell command or compound command, not a standalone file
- You need fine control over storage modes, `always_run`, `iterate_over`, etc.
- `xr` does not support the stage kind

Add a `pipeline.stages` block to `calkit.yaml`:

```yaml
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
      outputs: []
```

**Rules:**

- Stage names should be short, lowercase, hyphenated — they appear in CLI output and DVC stage names.
- Every file that one stage writes and another stage reads must be declared as both an output and an input. If you skip a dependency, stages may run in the wrong order or not re-run when they should.
- Prefer `from_stage_outputs: stage-name` when a stage consumes everything from a prior stage, rather than listing individual files.

## Step 6 — Decide output storage

For each output, decide: Git or DVC?

- **Git**: small files (< a few MB), text-based, human-readable. Examples: summary CSVs, JSON metadata, PDFs, HTML reports.
- **DVC**: large files, binary files, datasets that change frequently. Examples: raw data downloads, model weights, large matrices.

```yaml
outputs:
  - data/raw.csv # DVC (default — large/binary)
  - path: data/meta.json
    storage: git # small metadata, commit to Git
  - path: paper/paper.pdf
    storage: git # PDF, commit to Git
```

When in doubt, ask the user. Storage mode affects whether collaborators can see the file without `calkit pull`.

## Step 7 — Run the pipeline

Run the full pipeline to verify everything works:

```bash
calkit run
```

Watch for errors:

- Missing inputs: a stage lists an input that doesn't exist and isn't produced by an earlier stage
- Environment errors: `calkit check env --name <env>` to diagnose
- Script errors: fix in the script, then re-run

If a specific stage fails, re-run just that stage:

```bash
calkit run <stage-name>
```

Force re-run even if nothing changed:

```bash
calkit run --force
```

## Step 8 — Commit

Once the pipeline runs successfully:

```bash
calkit commit -m "Add reproducible pipeline"
```

This commits both Git-tracked files and DVC-tracked metadata.

## Common mistakes to avoid

- **Missing intermediate files in inputs/outputs**: if `process.py` reads `data/raw.csv` but that file isn't declared as an output of the `collect-data` stage, DVC won't know the dependency exists.
- **Hard-coded absolute paths in scripts**: scripts should use relative paths from the repo root (or from `wdir` if set).
- **Editing `dvc.yaml` directly**: always edit `calkit.yaml`. `dvc.yaml` is regenerated by Calkit.
- **Forgetting `environment`**: every stage needs one. If the script uses system tools only, use `_system` as the environment name.
