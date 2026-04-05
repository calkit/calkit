<p align="center">
  <a href="https://calkit.org" target="_blank">
    <img width="40%" src="docs/img/calkit-no-bg.png" alt="Calkit">
  </a>
</p>
<p align="center">
  <a href="https://docs.calkit.org" target="_blank">
    Documentation
  </a>
  |
  <a href="https://docs.calkit.org/tutorials" target="_blank">
    Tutorials
  </a>
  |
  <a href="https://github.com/orgs/calkit/discussions" target="_blank">
    Discussions
  </a>
</p>

<!-- INCLUDE: docs/index.md -->

Calkit helps you manage and automate research projects like a software
engineer.

Define computational environments,
steps that process your data, create figures,
presentations, and publications, connect to external tools,
then iterate quickly and painlessly until your research questions are
answered, tracking changes to all files along the way.
At the end, deliver your entire project as a self-contained, self-documenting,
version-controlled, and
[single button reproducible](https://doi.org/10.1190/1.1822162)
"calculation kit" so you and others can easily verify
and build upon the results.

## Guiding principles

- Quality comes from iteration. Automation reduces the time and effort
  needed to iterate, thereby increasing iteration and quality.
- Automating a step usually takes the same amount of time as doing it once
  manually, therefore it's almost always worth it.

## Features

- A simplified [version control](https://docs.calkit.org/version-control)
  interface that unifies Git and DVC (Data Version Control),
  so all materials can be kept in the same project repository.
  This way, code doesn't need to be siloed away from other
  important artifacts like datasets, models, figures, or article PDFs,
  allowing you to work on all parts of a project without hopping around to
  different tools.
- [Computational environment management](https://docs.calkit.org/environments) with support for many
  languages and environment managers: Conda, Docker, uv, Julia, Renv, and more.
  No need to create and update environments on your own. Calkit will handle
  them as needed.
- An environment-aware build system or [pipeline](https://docs.calkit.org/pipeline) with
  a simple declarative syntax and
  output caching so you don't need to think about which steps or stages
  need to be rerun after changing any part of the project.
  Simply call `calkit run`.
  Compose your pipeline from many different kinds of stages,
  including simple scripts, commands, Jupyter Notebooks, LaTeX, and more.
- A complementary self-hostable and GitHub-integrated
  [cloud platform](https://github.com/calkit/calkit-cloud)
  to facilitate backup, collaboration,
  and sharing throughout the entire research lifecycle.
- [Overleaf integration](https://docs.calkit.org/overleaf/), so
  analysis, visualization, and writing can all stay in sync
  (no more manual uploads!)
- Support for running on high performance computing (HPC) systems that use
  [SLURM schedulers](https://docs.calkit.org/pipeline/slurm).
- Support for running with [GitHub Actions](https://docs.calkit.org/tutorials/github-actions).
- Extensions for doing all of the above graphically in
  [JupyterLab](https://docs.calkit.org/jupyterlab) and
  [VS Code](https://marketplace.visualstudio.com/items?itemName=Calkit.calkit-vscode).

<!-- END INCLUDE -->

## Installation

<!-- INCLUDE: docs/installation.md +1 -->

On Linux, macOS, or Windows Git Bash,
install Calkit and [uv](https://docs.astral.sh/uv/)
(if not already installed) with:

```sh
curl -LsSf install.calkit.org | sh
```

Or with Windows Command Prompt or PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm install-ps1.calkit.org | iex"
```

If you already have uv installed, install Calkit with:

```sh
uv tool install calkit-python
```

You can also install with your system Python:

```sh
pip install calkit-python
```

To effectively use Calkit, you'll want to ensure [Git](https://git-scm.com)
is installed and properly configured.
You may also want to install [Docker](https://docker.com),
since that is the default method by which LaTeX environments are created.
If you want to use the [Calkit Cloud](https://calkit.io)
for collaboration and backup as a DVC remote,
you can [set up cloud integration](https://docs.calkit.org/cloud-integration).

### Use without installing

If you want to use Calkit without installing it,
you can use uv's `uvx` command to run it directly:

```sh
uvx calk9 --help
```

### Calkit Assistant

For Windows users, the
[Calkit Assistant](https://github.com/calkit/calkit-assistant)
app is the easiest way to get everything set up and ready to work in
VS Code, which can then be used as the primary app for working on
all scientific or analytical computing projects.

![Calkit Assistant](https://github.com/calkit/calkit-assistant/blob/main/resources/screenshot.png?raw=true)

<!-- END INCLUDE -->

## Quickstart

<!-- INCLUDE: docs/quickstart.md +1 -->

### From an existing project

If you want to use Calkit with an existing project,
navigate into its working directory and use the `xr` command to start
executing and recording your scripts, notebooks, LaTeX files, etc.,
as reproducible pipeline stages.
For example:

```sh
calkit xr scripts/analyze.py

calkit xr notebooks/plot.ipynb

calkit xr paper/main.tex
```

Calkit will attempt to detect environments, inputs, and outputs and
save them in `calkit.yaml`.
If successful,
you'll be able to run the full pipeline with:

```sh
calkit run
```

Next, make a change to e.g., a script and look at the output of
`calkit status`.
You'll see that the pipeline has a stage that is out-of-date:

```sh
---------------------------- Pipeline ----------------------------
analyze:
        changed deps:
                modified:           scripts/analyze.py
```

This can be fixed with another call to `calkit run`.

You can save (add and commit) all changes with:

```sh
calkit save -am "Add to pipeline"
```

### Fresh from a Calkit project template

Create a new project from the
[`calkit/example-basic`](https://github.com/calkit/example-basic)
template with:

```sh
calkit new project my-research \
    --title "My research" \
    --template calkit/example-basic \
    --cloud
```

Note the `--cloud` flag requires [cloud integration](https://docs.calkit.org/cloud-integration)
to be set up, but can be omitted if the project doesn't need to be backed up to
the cloud or shared with collaborators.
Cloud integration can also be set up later.

Next, move into the project folder and run the pipeline,
which consists of several stages defined in `calkit.yaml`:

<!-- TODO: This takes a long time to pull the image -->

```sh
cd my-research
calkit run
```

Next, make some edits to a script or LaTeX file and run `calkit status` to
see what stages are out-of-date.
For example:

```sh
---------------------------- Pipeline ----------------------------
build-paper:
        changed deps:
                modified:           paper/paper.tex
```

Execute `calkit run` again to bring everything up-to-date.

To back up or save the project, call:

```sh
calkit save -am "Run pipeline"
```

<!-- END INCLUDE -->

## Get involved

We welcome all kinds of contributions!
See [CONTRIBUTING.md](CONTRIBUTING.md) to learn how to get involved.
