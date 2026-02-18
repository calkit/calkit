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

Calkit makes it easy to create
["single button"](https://doi.org/10.1190/1.1822162)
reproducible research projects.

Instead of a loosely related collection of files
and manual instructions,
turn your project into a version-controlled,
self-contained "calculation kit,"
tying together all phases or stages of the project:
data collection, analysis, visualization, and writing,
each of which can make use of the latest and greatest computational
tools and languages.
In other words, you, your collaborators, and readers will be able to go
from raw data to research article with a single command,
improving efficiency via faster iteration cycle time,
reducing the likelihood of mistakes,
and allowing others to more effectively build upon your work.

Calkit makes this level of automation possible without extensive software
engineering expertise by providing a project framework and toolset that unifies
and simplifies the use of powerful enabling technologies like Git,
DVC, Conda, Docker, and more,
while guiding users away from common reproducibility pitfalls.

## Features

- A declarative pipeline that guides users to define an environment
  for every stage, so long lists of instructions in a README and
  "but it works on my machine" are things of the past.
- A CLI to run the project's pipeline to verify it's reproducible,
  regenerating outputs as needed and
  ensuring all
  computational environments
  (e.g., [Conda](https://docs.conda.io/en/latest/),
  [Docker](https://docker.com), uv, Julia)
  match their specification.
- A schema to store structured metadata describing the
  project's important outputs (in its `calkit.yaml` file)
  and how they are created
  (its computational environments and pipeline).
- A command line interface (CLI) to simplify keeping code, text, and larger
  data files backed up in the same project repo using both
  [Git](https://git-scm.com/) and [DVC](https://dvc.org/).
- A complementary self-hostable and GitHub-integrated
  [cloud system](https://github.com/calkit/calkit-cloud)
  to facilitate backup, collaboration,
  and sharing throughout the entire research lifecycle.
- [Overleaf integration](https://docs.calkit.org/overleaf/), so code,
  data, and LaTeX documents can all live in the same repo and be part of a
  single pipeline (no more manual uploads!)

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
navigate into its working directory and run:

```sh
calkit new project --public --cloud .
```

Note that the `--public` and `--cloud` options can be omitted,
but then you'll need to configure your own DVC remote or use Git to store
pipeline outputs.

Next, create your [environment(s)](https://docs.calkit.org/environments).
In this example, imagine we have a `requirements.txt` file we want to use to
define a uv virtual environment, or venv:

```sh
calkit new uv-venv --name main --path requirements.txt --python 3.13
```

If you're using Conda for environment management,
e.g., with an `environment.yml` file,
you can use the `calkit new conda-env` command.

Next, we can start building our [pipeline](https://docs.calkit.org/pipeline).
Let's say we have a Jupyter notebook called `collect-data.ipynb`
that produces raw data at `data/raw.h5`.
We can add a pipeline stage to run this notebook in the `main` environment
we just created with:

```sh
calkit new jupyter-notebook-stage \
    --name collect-data \
    --environment main \
    --notebook-path collect-data.ipynb \
    --output data/raw.h5
```

We can then run the pipeline with:

```sh
calkit run
```

and save and back up our results with:

```sh
calkit save -am "Run pipeline"
```

After that,
you can add more environments, pipeline stages,
[start a publication with LaTeX](https://docs.calkit.org/tutorials/adding-latex-pub-docker),
or [link a publication with Overleaf](https://docs.calkit.org/overleaf).

### Fresh from a Calkit project template

After installing Calkit and setting your token as described above, run:

```sh
calkit new project calkit-project-1 \
    --title "My first Calkit project" \
    --template calkit/example-basic \
    --cloud \
    --public
```

This will create a new project from the
[`calkit/example-basic`](https://github.com/calkit/example-basic)
template,
creating it in the cloud and cloning to `calkit-project-1`.
You should now be able to run:

```sh
cd calkit-project-1
calkit run
```

This will run the project's pipeline.
Next, you can start adding stages to the pipeline,
modifying the Python environments and scripts,
and editing the paper.
All will be kept in sync with the `calkit run` command.

To back up all of your work, execute:

```sh
calkit save -am "Run pipeline"
```

This will commit and push to both GitHub and the Calkit Cloud.

<!-- END INCLUDE -->

## Get involved

We welcome all kinds of contributions!
See [CONTRIBUTING.md](CONTRIBUTING.md) to learn how to get involved.
