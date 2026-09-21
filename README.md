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

Calkit makes it easy to create
[single-button reproducible](https://doi.org/10.1190/1.1822162)
research projects.
Instead of a loosely related collection of files
split across multiple systems or apps,
"integrated" via manual steps,
your project becomes a version-controlled, self-contained "calculation kit"
tying together literature review, planning, data collection,
analysis, and writing,
so you, your collaborators, and your readers can verify the full
chain from raw data to
research article with a single command.
This enables faster, more confident, and more frequent iteration,
which in turn produces
[higher quality results](https://doi.org/10.1145/1640233.1640260).
It also makes it easy to check the work of an AI agent,
i.e., that the outputs it produced as evidence to answer research questions
came from a transparent,
deterministic pipeline, not hallucinations.

Calkit also makes it natural to keep all stages of a research project
together in the
same repository, providing full context to both humans and AI agents.
This is important because the stages are tightly coupled.
A change in a dataset requires reanalyzing,
which creates a change in a figure,
which creates a change in a research article.
Coupled components belong close together and connected,
and cross-stage iteration is enabled by _integration_.

Software teams learned the importance of integration long ago,
unifying design, development, testing, deployment, and infrastructure
in the same repo, often within the same team,
with automation across the entire lifecycle.
Research can benefit in similar ways.

<!-- https://docs.google.com/drawings/d/1h-OvPG0-PMIaayMNnQvERMjXTebFBhKQeDnIC9z_jp8/edit -->

![pipeline](https://docs.calkit.org/img/pipeline.png)

## Why Calkit?

The tools to create single-button reproducible
research projects already exist, e.g.,
version control with Git,
environment management with uv,
Make for a build system or pipeline,
and LaTeX for document compilation.
If you and your team can work effectively with a system like that,
there's no need for any additional complexity.

However, these practices are still not common,
resulting in most compendiums
[failing to reproduce](https://doi.org/10.1038/s41597-022-01143-6).
Many still silo the code away from the data,
and the analysis from the writing.
Many are instead "multi-button"
and irreproducible because their stages are not connected
and important setup or execution information is omitted.

There are additional challenges:

1. Computationally expensive steps may need to be run on a high-performance
   computing (HPC) cluster.
   Automating the transfer of data to and from there requires additional
   work,
   and it becomes important to use a
   content-aware pipeline system, otherwise steps are inefficiently repeated
   or mistakenly skipped.
2. Large data files need to be kept in version control along with the rest.
   A typical solution may involve siloing data files away on a shared cloud
   or physical hard drive,
   requiring custom syncing scripts to avoid manual uploads and downloads.

Again,
the tools to solve these problems do exist:
Snakemake, Nextflow, or DVC for pipelines;
Git LFS, git-annex, or DVC for data version control,
but they all require significant setup and training.
At this point, you're looking at half a dozen subsystems to integrate
and upskill the team to use,
essentially requiring many to become de facto software engineers
to contribute.
What happens in reality is that the costs are deemed too high
and the benefit too low, so
workflows remain manual and fragmented,
and many team members are not able to contribute to
their full potential.

Calkit solves these by providing a fully integrated experience
built from the open source components that would typically
comprise such a workflow.
Everything is connected right out of the box,
with a command line interface (CLI), web app, and more
to reduce friction for every task and team member involved.
The integration is transparent without lock-in,
so the underlying software engineering-oriented
tools can be used directly by
team members more comfortable with them,
and others can contribute at a higher level
while maintaining single-button reproducibility and frictionless,
seamless iteration.

Additionally, the Calkit project information format,
saved in `calkit.yaml`,
gives a full picture of the project:
its research questions, artifacts
generated as evidence to answer them,
and a way to fully verify everything back to its origin.
There's no mystery about where a certain figure or table came from,
and whether or not it's stale with respect to its input data,
which is a critical feature to have when using generative AI.

## Features

- A simplified [version control](https://docs.calkit.org/version-control)
  interface that unifies Git and DVC (Data Version Control),
  so everything can be kept in the same project repository.
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
- Tools for automatically building reproducible pipelines from work you're
  already doing.
  Run a script, notebook, or LaTeX document with
  [`calkit xr`](https://docs.calkit.org/pipeline#automatic-stage-and-environment-detection)
  and it becomes a pipeline stage,
  with its environment, inputs, and outputs detected and recorded,
  so an existing project becomes reproducible one command at a time rather
  than all at once.
- A complementary self-hostable and GitHub-integrated
  [hub](https://github.com/calkit/calkit/tree/main/hub)
  web app to facilitate backup, collaboration,
  and sharing throughout the entire research lifecycle.
- [Overleaf integration](https://docs.calkit.org/overleaf/), so
  analysis, visualization, and writing can all stay in sync
  (no more manual uploads!).
- Support for running on [high performance computing (HPC)](https://docs.calkit.org/hpc) systems
  that use PBS or SLURM schedulers.
- Support for automated running with
  [GitHub Actions](https://docs.calkit.org/tutorials/github-actions).
- Extensions for doing all of the above graphically in
  [JupyterLab](https://docs.calkit.org/jupyterlab) and
  [VS Code](https://marketplace.visualstudio.com/items?itemName=Calkit.calkit-vscode).
- A [browser extension](https://docs.calkit.org/browser-ext) for collecting references
  directly to BibTeX (optionally synced with Zotero),
  viewing DVC-stored files on GitHub,
  and syncing figures and results with Overleaf directly in Chrome,
  Microsoft Edge, and more.

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
If you want to use a [Calkit hub](https://docs.calkit.org/hub)
for collaboration and backup as a DVC remote,
you can [connect to the hub](https://docs.calkit.org/hub) with:

```sh
calkit hub login
```

If you use AI agents like Claude, Copilot, or Codex,
see [AI tools](https://docs.calkit.org/ai-tools)
to learn how to install agent skills for working with Calkit.

### Use without installing

If you want to use Calkit without installing it,
you can use uv's `uvx` command to run it directly:

```sh
uvx ck9 --help
```

### Nix

Calkit ships a [flake](https://nixos.wiki/wiki/Flakes) at the root of
its repo, so [Nix](https://nixos.org/) users can pull the CLI into their
environments alongside their other tools.

Run it ad hoc without installing:

```sh
nix run github:calkit/calkit -- --help
```

Drop into a shell that has `calkit`, `git`, and `uv` on `PATH`:

```sh
nix shell github:calkit/calkit
```

Add it to your own `flake.nix` as an input:

```nix
{
  inputs.calkit.url = "github:calkit/calkit";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs, calkit }: {
    devShells.x86_64-linux.default =
      nixpkgs.legacyPackages.x86_64-linux.mkShell {
        packages = [ calkit.packages.x86_64-linux.default ];
      };
  };
}
```

Then `nix develop` will give you a shell with the Calkit CLI ready to
use. To pin a specific Calkit release inside the shell, set the
`CALKIT_VERSION` environment variable (e.g. `CALKIT_VERSION=0.41.0`)
before invoking `calkit`.

The flake is currently a thin wrapper around `uvx --from calkit-python
calkit`. It depends on `uv` from `nixpkgs` and fetches the published
wheel from PyPI on first use. This trades a fully Nix-native build for
zero version-drift maintenance, and avoids the macOS `docx2pdf` /
`appscript` and JupyterLab labextension build issues that block a pure
nixpkgs derivation today. If you want a fully nixpkgs-native build,
see the community [`calkit-nix`](https://github.com/dwinkler1/calkit-nix)
flake.

Nix isn't supported natively on Windows; run Calkit inside
[WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) and use
the flake there.

### Running against a specific version

If a project requires a Calkit version other than the one you have
installed, use the top-level `--use-version` flag to re-invoke the CLI
under that release without changing your installation:

```sh
calkit --use-version 0.38 run
```

This re-execs the CLI via `uvx --from calkit-python@<version> calkit`,
so it requires [uv](https://docs.astral.sh/uv/) on `PATH`.
You can also declare a minimum version in `calkit.yaml`;
see
[Pinning the Calkit CLI version](https://docs.calkit.org/requirements#pinning-the-calkit-cli-version).

### Calkit Assistant

For Windows users, the
[Calkit Assistant](https://github.com/calkit/calkit/tree/main/assistant)
app is the easiest way to get everything set up and ready to work in
VS Code, which can then be used as the primary app for working on
all scientific or analytical computing projects.
Download the executable from the latest
[assistant release](https://github.com/calkit/calkit/releases?q=assistant%2Fv&expanded=true).

![Calkit Assistant](https://github.com/calkit/calkit/blob/main/assistant/resources/screenshot.png?raw=true)

<!-- END INCLUDE -->

## Quickstart

<!-- INCLUDE: docs/quickstart.md +1 -->

<!-- prettier-ignore -->
> [!NOTE]
> `ck` is an abbreviated alias for the `calkit` executable.
> All `calkit` commands can be run as `ck` instead, e.g., `ck save -am "..."`.

This walks through a small but complete project: a question, the data
collected to answer it, a figure and a number computed from that data,
and a paper that shows both.
It takes about a minute, and the point isn't the example's findings.
It's that from here on, changing anything upstream tells you what
downstream is now out of date, and one command brings it all back into
line.

### Create a project

```sh
calkit new project my-research \
    --title "My research" \
    --template calkit/example-basic
```

This gives you a working project rather than an empty one, so there is
something to run before there is something to write.

Add `--hub` to also create it on [a Calkit hub](https://docs.calkit.org/hub), which is
how projects get backed up and shared.
It needs an account, and can be set up later, so leave it off for now if
you just want to see the thing work.

### Look at the question

Open `calkit.yaml`.
Near the top is what this project is for:

```yaml
questions:
  - question: How does the system respond to increasing $x$?
    hypothesis: The value of $y$ increases linearly with $x$.
    answer: $y$ increases quadratically with $x$, not linearly.
    evidence:
      - kind: figure
        path: figures/x-vs-y.png
      - kind: result
        path: results/summary.json
        key: r_squared_quadratic
```

The answer names the files that back it up.
Those files are produced by the pipeline, so the claim and the evidence
for it can't drift apart: if the data changes, the figure and the number
are stale, and so is the answer that rests on them.

This is the part worth copying into your own work.
Writing the question down first makes it obvious what evidence you owe.

### Run it

```sh
cd my-research
calkit run
```

```
💻 Getting system information
🔗 Checking system-level requirements
📦 Checking environments
🔀 Compiling DVC pipeline
Running stage 'collect-data':
Running stage 'analyze':
Running stage 'figs-to-paper':
Running stage 'results-to-tex':
Running stage 'build-paper':
Pipeline completed successfully ✅
```

Five stages ran: data was collected, analyzed into a figure and a
results file, the figure was copied into the paper's folder, the results
were turned into LaTeX, and the paper was compiled.
You now have `paper/main.pdf`.

Calkit created the Python environment and pulled the TeX image itself.
If something it needs isn't installed, Docker most often, it says so,
shows you the command, and offers to run it:

```
App 'docker' is not installed.
  brew install --cask docker
Run this to install 'docker'? [Y/n]
```

You can ask for that check at any time with `calkit check reqs`.

### Change something

Edit `scripts/analyze.py`, then ask what that affected:

```sh
calkit status
```

```
---------------------------- Pipeline ----------------------------
Stale stages:
        analyze:
          stale outputs:
            figures/x-vs-y.png
            results/summary.json
          modified inputs:
            scripts/analyze.py
```

The figure and the results file are stale because the script that makes
them changed.
Nothing else is, because nothing else depends on it yet in a way that
has been invalidated.

```sh
calkit run
```

Only what needed to run runs again, and the paper is rebuilt with the
new figure and the new numbers in it.
That loop, edit and run, is the whole working rhythm.
The document is never out of step with the analysis, because it can't
be.

### Save it

```sh
calkit save -am "Tweak the fit"
```

This stages, commits, and pushes in one step, sending code to Git and
data and outputs to DVC storage, so you don't have to decide which goes
where.

### Where to go next

Add your own data and a script to process it with
[`calkit xr`](https://docs.calkit.org/pipeline), which runs a command and records it as
a pipeline stage.
To bring an existing project into Calkit instead of starting from a
template, see
[the tutorial on existing projects](https://docs.calkit.org/tutorials/existing-project).

A project grows by adding questions.
`questions` is a list, and each entry names its own evidence, so a
second study is another entry and the stages that answer it rather than
a second project.

### With an AI coding agent

Simply tell the [AI agent](https://docs.calkit.org/ai-tools):

> Turn this folder into a Calkit project

or

> Create me a new Calkit project for investigating...

<!-- END INCLUDE -->

## Get involved

We welcome all kinds of contributions!
See [CONTRIBUTING.md](CONTRIBUTING.md) to learn how to get involved.

## Acknowledgements

<!-- INCLUDE: docs/acknowledgements.md +1 -->

Calkit is supported by the
[Caltech Schmidt Academy of Software Engineering](https://sase.caltech.edu).

<p align="center">
  <a href="https://sase.caltech.edu" target="_blank">
    <img width="40%" src="docs/img/caltech.png" alt="Caltech SASE">
  </a>
<a href="https://schmidtsciences.org/" target="_blank">
    <img width="40%" src="docs/img/schmidt-sciences.png" alt="Schmidt Sciences">
  </a>
</p>

<!-- END INCLUDE -->
