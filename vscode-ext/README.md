# Calkit for VS Code

Turn a research or analytical project into a navigable, reproducible
system.

Most projects where the output artifacts (figures, datasets, results,
papers, presentations) are what matter accumulate a tangle of scripts,
notebooks, environments, and data. Calkit gives that tangle a structure: every
artifact is traceable to the pipeline stage that produced it, every stage to its
code and environment. This extension is the integration layer on top—it
surfaces the whole system in one place, lets you traverse between layers
(artifact → stage → environment → source), and lets you make changes at any
layer and re-run to keep everything in sync.

## The Calkit sidebar: a holistic view of the project

The **Calkit** activity-bar view presents the project as connected sections:

- **Questions**: The research questions the project sets out to answer.
- **Environments**: Every computational environment (uv, Pixi, venv, conda,
  renv, Docker, Julia, MATLAB, SSH, SLURM/PBS, and nested combinations).
- **Pipeline**: The stages that produce the project's artifacts, each showing
  live status (up to date, **stale**, or running).
- **Notebooks**: Jupyter notebooks and the environments/stages they belong to.
- **Figures**, **Datasets**, **Results**, **Publications**, and
  **Presentations**: The output artifacts, each annotated with the stage (or
  import source) it came from.

Items are cross-linked, so you can traverse the system in any direction:
expand a figure to jump to the stage that made it, jump from a stage to its
environment, open the stage's script/notebook, or open an output file—then run
the stage again. A badge and per-section warnings flag anything that needs
attention (stale outputs, artifacts with no defined source, notebooks with no
environment).

Use the toolbar to filter the tree across all sections, refresh status,
hide/show sections, open `calkit.yaml`, or initialize a new Calkit
project in a plain folder.

## Provenance & traceability

- **Show Source**: From an open figure, PDF, dataset, or other pipeline output,
  jump straight to the producing stage in the sidebar (and into its source).
- **Figure source links**: In Quarto (`.qmd`) and LaTeX (`.tex`) documents, a
  "Source: \<stage\>" CodeLens appears above each `![](…)` / `\includegraphics{…}`
  that references a pipeline output; right-click also offers **Go to Figure
  Source**. (From a compiled PDF, LaTeX Workshop's reverse-SyncTeX takes you to
  the `\includegraphics` line, where these actions take over.)
- **Stale-output awareness**: Outputs whose stage needs re-running are flagged
  in the sidebar and in the file explorer.
- **File history**: View a tracked file's history from the sidebar or explorer.
- **Scheduler logs**: Stages that run under SLURM/PBS surface their log file in
  the tree so you can open it with a click.

## Pipeline

- Run the whole pipeline, an individual stage, or the stage for the file
  you're editing.
- Define new stages graphically, including turning a notebook, script, or an
  existing artifact into a reproducible stage; edit existing stages.
- Visualize the pipeline DAG.
- Open the rendered PDF of a LaTeX/Quarto stage from its source.

## Environments

- Create and edit environments graphically (package lists, spec files, base
  images, etc.) for uv, Pixi, venv, conda, renv, Docker, Julia, MATLAB, SSH, and
  SLURM/PBS.
- Select a notebook's environment and let the extension register/select the
  matching Jupyter kernel—or edit that environment right from the notebook
  toolbar.
- Use nested environments like `slurm:main` for notebook jobs that need to,
  e.g., to reserve GPUs on a cluster.
- Start, stop, and restart notebook server sessions for SLURM- and
  Docker-backed workflows from the notebook toolbar.

## Figures & artifacts

- Browse figures in a gallery and carousel, including interactive Plotly
  figures (`.json`), with per-figure provenance and a one-click jump to the
  producing stage.
- Preview Plotly JSON files in a dedicated **Plotly Preview** editor.
- Open a notebook's executed HTML output.

## Getting started

1. Open a project folder. If it isn't a Calkit project yet, the sidebar offers
   **Initialize Calkit Project**.
2. Explore the Calkit sidebar to see environments, the pipeline, and
   artifacts.
3. From a notebook, run **Calkit: Select Notebook Environment**, pick or create
   an environment (providing SLURM options like `--gpus`/`--time` if needed), and
   the extension registers/selects the kernel and connects the session.

## Requirements

- VS Code with the Jupyter extension installed.
- The Calkit CLI available on your `PATH`. If it's missing or too old, the
  extension prompts with install/upgrade options.

## How environments are stored in `calkit.yaml`

Selecting an environment for a notebook writes it to `calkit.yaml`, updating
either `notebooks` or `pipeline.stages` depending on whether the notebook is part
of a pipeline stage.

```yaml
# Standalone notebook
notebooks:
  - path: my-notebook.ipynb
    environment: my-env

# Notebook that is a pipeline stage
pipeline:
  stages:
    my-notebook:
      kind: jupyter-notebook
      notebook_path: my-notebook.ipynb
      environment: my-env
```

## Settings

- `calkit.autoRefreshStatus`: Automatically run `calkit status` to refresh
  pipeline staleness when project files change (disable if frequent status
  checks interfere with Git operations; you can still refresh manually).
- `calkit.notebook.defaultJupyterPort`: Default port for Calkit-backed Jupyter
  servers.
- `calkit.sidebar.hiddenSections`: Sidebar sections to hide (managed via the
  sidebar's **Manage Sections** action).

## Commands

Most actions are available from the sidebar, notebook toolbar, and editor
context menus. Highlights, all under the **Calkit** category in the command
palette:

- Project: **Initialize Calkit Project**, **Open calkit.yaml**, **Save**,
  **Refresh**, **Filter** / **Clear Filter**, **Manage Sections**
- Pipeline: **Run Pipeline**, **Run Stage**, **New Stage**, **Edit Stage**,
  **Show Pipeline DAG**, **Open Rendered PDF**, **Show Source**, **Go to Figure
  Source**
- Environments: **Create Environment**, **Edit Environment**, **Select Notebook
  Environment**, **Edit Notebook Environment**
- Notebook sessions: **Start Jupyter SLURM Job**, **Stop Jupyter SLURM Job**,
  **Restart Notebook Server**, **Open Executed HTML**
- Figures: **Browse Figures**, **Open Plotly Preview**
- Artifacts: **Define Pipeline Stage**, **Define Import**, **View File History**
