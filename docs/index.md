# Home

Typical research workflows are horizontally-siloed, i.e.,
various stages--data collection, analysis, writing--are performed in
disconnected systems,
turning research into a slow, error-prone, and tedious
[waterfall](https://en.wikipedia.org/wiki/Waterfall_model) process.

Calkit helps you integrate code, data, figures, results, publications,
and more into a cohesive, traceable, and portable _knowledge creation system_,
so every output can be traced back to its source (provenance)
and reproduced with a single command.

With industry standard tools combined into a unified and simplified experience
tailored for research,
you can reap the rewards of reproducibility and automation
without the cognitive overhead.

<!-- https://docs.google.com/drawings/d/1XMGnbgYYNFAVUBDyUaCyLfRB7efvJdrnrKmFlNmT19o/edit -->

![pipeline](img/pipeline.png)

## Why Calkit?

For a small project, you don't need Calkit to be single-button reproducible.
A Makefile, a uv-managed environment, Git, and a LaTeX build will get you
there, and if that's your situation, it's a fine setup.

Projects rarely stay small, though.
Reproducibility gets hard when a project gets fragmented,
i.e., when the context needed to regenerate a result stops living in one
place.
That usually starts with one of these:

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

Each of these has a known fix: DVC for data and caching, Docker or Conda for
environments, CI for running on a clean machine, a script to sync figures to
Overleaf.
But each fix is another tool to learn, configure, and keep in step with the
others, and most researchers, reasonably, don't.
The project ends up as a mix of automated and manual steps,
and reproducing it means reproducing the manual steps too.
The single button becomes many buttons, with people in between.

Calkit exists to make the integrated version the easy version.
One `calkit.yaml` describes the environments, the pipeline, and the artifacts,
so all of the context is in one place.
`calkit run` builds environments as needed and runs only what changed,
`calkit clone` pulls cached outputs so expensive stages never need to be rerun,
`calkit save` handles Git and DVC together,
and the paper is a pipeline stage like any other, so the button covers it.
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
