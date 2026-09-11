# Examples

Here are some example projects that use Calkit.
If you have one you'd like to be included, please
[✏️ edit this page](https://github.com/calkit/calkit/edit/main/docs/examples.md).

## NACA 0012 2-D RANS with OpenFOAM

[Project page](https://calkit.io/petebachant/nacafoil-openfoam) |
[GitHub repo](https://github.com/petebachant/NACAFoil-OpenFOAM)

Features:

- A Docker environment for simulation
- A uv venv environment
- Interactive Plotly figures saved as JSON
- Interactive HTML figures generated with PyVista
- An interactive marimo app hosted on HF spaces for interacting with the
  results

## A basic research project

[Project page](https://calkit.io/calkit/example-basic) |
[GitHub repo](https://github.com/calkit/example-basic)

Features:

- An automatically-managed uv virtual environment for data processing and
  visualization
- A LaTeX publication built with a Docker container
- A dev container spec to enable editing and collaboration with GitHub
  Codespaces

## Runnable README

[GitHub repo](https://github.com/calkit/calkit/tree/main/examples/markdown)

Features:

- A pipeline declared entirely in the README's code blocks,
  with Python, Julia, and R stages
- Environments declared by the install commands the README shows
- Output printed by each stage written back into the README

Create a copy with:

```sh
calkit new project my-readme \
    --from https://github.com/calkit/calkit/examples/markdown
```

See [Runnable Markdown](pipeline/markdown.md) for how it works.

## MATLAB

[Project page](https://calkit.io/calkit/example-matlab) |
[GitHub repo](https://github.com/calkit/example-matlab)

Features:

- Dependency checking before pipeline execution
- MATLAB scripts run in batch mode

## Julia

[Project page](https://calkit.io/calkit/example-julia) |
[GitHub repo](https://github.com/calkit/example-julia)

Features:

- A Julia environment declared with a `Project.toml`
- A flow simulation script run with WaterLily.jl
- A Jupyter notebook run in the same Julia environment
- A LaTeX conference paper built with a Docker container from the script's
  figures

## R

[Project page](https://calkit.io/calkit/example-r) |
[GitHub repo](https://github.com/calkit/example-r)

Features:

- An `renv` environment declared with a `DESCRIPTION` file
- R scripts for analysis and plotting, with the processed data and figures
  versioned in Git

## Analytics

[Project page](https://calkit.io/calkit/example-analytics) |
[GitHub repo](https://github.com/calkit/example-analytics)

Features:

- A Jupyter notebook as the whole pipeline, run in a uv environment
- A dataset imported from Zenodo, with its license recorded
- A notebook adapted from Kaggle, with its provenance and license recorded
- Figures, tables, and results produced by the notebook and shown in the
  project showcase

## Strava analysis

[Project page](https://calkit.io/petebachant/strava-analysis) |
[GitHub repo](https://github.com/petebachant/strava-analysis)

Features:

- OAuth2 authentication with an external API
- Environmental variable dependencies
- A pipeline designed to be run periodically to accumulate new data
- A project showcase with interactive Plotly figures
- A uv project-based environment and dedicated Python package

## OpenFOAM RANS boundary later validation

[Project page](https://calkit.io/petebachant/rans-boundary-layer-validation) |
[GitHub repo](https://github.com/petebachant/rans-boundary-layer-validation)

Features:

- OpenFOAM simulations run in a Docker container
- A LaTeX document built with a Docker container
- A direct numerical simulation dataset for validation imported from a
  different project, derived from the Johns Hopkins Turbulence Database

## SSH

[Project page](https://calkit.io/calkit/example-ssh) |
[GitHub repo](https://github.com/calkit/example-ssh)

Features:

- An SSH environment for running a remote command over SSH and copying back
  results to the local machine

## Overleaf integration

[Project page](https://calkit.io/calkit/example-overleaf) |
[GitHub repo](https://github.com/calkit/example-overleaf)

Features:

- A publication linked to an Overleaf project, which syncs changes to the
  text from Overleaf, and pushes figures generated locally to Overleaf.

## LaTeX with Word review

[GitHub repo](https://github.com/calkit/calkit/tree/main/examples/latex-word)

Features:

- A LaTeX paper split across multiple source files, built with a Docker
  container from a figure generated in a uv environment
- A Word copy exported for reviewers, whose edits and comments merge back
  into the LaTeX source

Create a copy with:

```sh
calkit new project my-paper \
    --from https://github.com/calkit/calkit/examples/latex-word
```

See the [LaTeX and Word tutorial](tutorials/latex-word.md) for the workflow.
