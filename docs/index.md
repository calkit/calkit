# Home

Calkit makes it easy to create
["single button"](https://doi.org/10.1190/1.1822162)
reproducible research projects.
Instead of a loosely related collection of files and manual instructions,
your project becomes a version-controlled, self-contained "calculation kit"
tying together data collection, analysis, visualization, and writing,
so you, your collaborators, and your readers can go from raw data to
research article with a single command.
That means faster iteration, fewer mistakes,
and no more wondering how a figure was made six months after submitting
the paper.

<!-- https://docs.google.com/drawings/d/1XMGnbgYYNFAVUBDyUaCyLfRB7efvJdrnrKmFlNmT19o/edit -->

![pipeline](img/pipeline.png)

## Why Calkit?

The parts of a research project are tightly coupled.
The data feeds the analysis, the analysis makes the figures,
the figures go in the paper,
and all of it exists to answer one question.
No piece is worth much on its own.
The whole kit is, and the paper is just the entrypoint to it.

When tightly coupled things are kept in separate places,
iteration gets slow and mistakes creep in.
Software teams learned this and responded by pulling development, testing,
and infrastructure into the same repo.
Research projects tend to drift the other way,
and it usually starts with one of these:

- **Large datasets.** They don't fit in Git, so they end up on a shared drive
  or a laptop, and the repo is no longer a complete record of the project.
- **Expensive computations.** A simulation that took a week on a cluster is not
  something a clean build should rerun, so it's left out of the pipeline and
  its outputs are copied around by hand.
- **Multiple environments.** A Python analysis, an R script, a Docker
  container for a solver, and the paper build all need different environments,
  and "works on my machine" creeps in.
- **Writing.** Figures are uploaded to Overleaf manually, so the paper is
  reproducible only up to the last time someone remembered to update it.
- **Collaboration.** Each collaborator has their own copy of the data, their
  own environment, and their own idea of which version of a figure is current.

Each of these has a known fix: DVC for data and caching, Make or Snakemake
for the rebuild logic, Docker or Conda for environments, CI for running on a
clean machine, a script to sync figures to Overleaf.
For a small project, a Makefile and uv may be all you need.
But past that, it means shopping around for each tool, learning it,
and wiring it to the others,
i.e., building your own kit before you can put anything in it.
Most researchers, reasonably, don't.
The project ends up as a mix of automated and manual steps,
and reproducing it means reproducing the manual steps too.
The single button becomes many buttons, with people in between.

Calkit is the kit, already assembled.
It has a slot for each concern: environments, datasets, notebooks and
scripts, figures, publications, and a pipeline connecting them,
all described in one `calkit.yaml`.
You put your pieces in the slots.
`calkit run` builds environments as needed and runs only what changed,
`calkit clone` pulls cached outputs so expensive stages never need to be rerun,
`calkit save` handles Git and DVC together,
and the paper is a pipeline stage like any other, so the button covers it.

Having the whole project described in one place also makes it checkable.
Every figure, dataset, and number in the paper can be traced to the stage
that produced it or the source it was imported from,
and a rerun shows whether that record is true.
With AI agents doing more of the work, this matters more than it used to.
An agent can produce a plausible figure as easily as a real one,
and a cheap rerun is what makes checking its work affordable.

Underneath, it's still Git, DVC, Docker, Conda, uv, and LaTeX,
so nothing is hidden and nothing is locked in.

## Features

- A simplified [version control](version-control.md)
  interface that unifies Git and DVC (Data Version Control),
  so everything can be kept in the same project repository.
  This way, code doesn't need to be siloed away from other
  important artifacts like datasets, models, figures, or article PDFs,
  allowing you to work on all parts of a project without hopping around to
  different tools.
- [Computational environment management](environments.md) with support for many
  languages and environment managers: Conda, Docker, uv, Julia, Renv, and more.
  No need to create and update environments on your own. Calkit will handle
  them as needed.
- An environment-aware build system or [pipeline](pipeline/index.md) with
  a simple declarative syntax and
  output caching so you don't need to think about which steps or stages
  need to be rerun after changing any part of the project.
  Simply call `calkit run`.
  Compose your pipeline from many different kinds of stages,
  including simple scripts, commands, Jupyter Notebooks, LaTeX, and more.
- A complementary self-hostable and GitHub-integrated
  [hub](https://github.com/calkit/calkit/tree/main/hub)
  to facilitate backup, collaboration,
  and sharing throughout the entire research lifecycle.
- [Overleaf integration](https://docs.calkit.org/overleaf/), so
  analysis, visualization, and writing can all stay in sync
  (no more manual uploads!)
- Support for running on [high performance computing (HPC)](hpc.md) systems
  that use PBS or SLURM schedulers.
- Support for automated running with
  [GitHub Actions](tutorials/github-actions.md).
- Extensions for doing all of the above graphically in
  [JupyterLab](jupyterlab.md) and
  [VS Code](https://marketplace.visualstudio.com/items?itemName=Calkit.calkit-vscode).
- A [browser extension](browser-ext/index.md) for collecting references
  directly to BibTeX (optionally synced with Zotero),
  viewing DVC-stored files on GitHub,
  and syncing figures and results with Overleaf directly in Chrome,
  Microsoft Edge, and more.
