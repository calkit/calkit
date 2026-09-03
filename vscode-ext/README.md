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
- **Figure source links**: right-click a figure reference for **Go to Figure
  Source**. (From a compiled PDF, LaTeX Workshop's reverse-SyncTeX takes you to
  the `\includegraphics` line, where these actions take over.) The CodeLens
  that used to sit above each reference is now part of the components lens
  below, so a line carries one lens rather than two.
- **Document components**: In a LaTeX document that uses project content
  (`\result[…]`, an `\includegraphics` of a pipeline output, `\ckfindings`),
  hover any of it to see the
  value, the file and key it came from, the stage and script behind it, the
  pages it lands on, and whether it is still current, with links to open the
  file, its script, and the thing itself or its stage in the Calkit sidebar. **Go to Definition**
  (F12) opens the results file at that key or the figure itself; **Go to
  Declaration** opens the producing script, so the loop is: hover a number,
  jump to the script, tweak, come back. A CodeLens flags a line whose content
  needs a rerun, has drifted from the project since the document was built, or
  came from nowhere at all, and offers to run the stage. Beside it, a second
  lens names the stage the line came from and opens it in the Calkit sidebar,
  where its script, inputs and outputs are. A third names what the line uses,
  and opens that: the figure, the results file, or the question, wherever the
  project declares it. A figure nothing accounts for says so on that lens,
  since its sidebar entry is where its origin gets recorded. The lens also works in
  Quarto and Markdown, where there is no provenance record to read and it falls
  back to naming the stage behind each figure reference. The same readings go
  into **Problems**, so a value that moved on page nine is counted rather than
  waiting to be scrolled to: an error for content the project no longer has, a
  warning for content out of date, and a warning for content nothing accounts
  for, which no rerun will fix. Questions are reported there too, on the line in `calkit.yaml` that
  declares them, since a placeholder that fills from nothing, or evidence that
  has moved since the answer was written, is about the question rather than the
  paper that typesets it. The editor reports what changed, not whether the
  answer is still right, which is a question about the sentence.
- **Clickable paths**: Every value in `calkit.yaml` that names something in the
  project is a link. A file opens in the editor; a directory, such as a stage
  input that names a whole folder, is focused and expanded in the file tree the
  way the sidebar's own input and output rows do it. Which strings are paths is
  decided by what is on disk, not by a list of keys, so a path a new stage kind
  introduces works without the extension knowing about it.
- **Stage definitions**: The Calkit sidebar's stage rows open `calkit.yaml`
  scrolled to where the stage is written, since its script, notebook or target
  is already listed under the stage's own properties. A stage a Markdown file
  declares opens that file at its block.
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
