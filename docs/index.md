# Home

Calkit makes it easy to create
["single button"](https://doi.org/10.1190/1.1822162)
reproducible research projects.
Instead of a loosely related collection of files
split across multiple systems or apps,
"integrated" via manual steps,
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

The parts of a research project are tightly coupled:
data feeds analysis, analysis makes figures, figures go in the paper,
and all of it exists to answer a question.
No piece is valuable on its own.
The whole kit is, and the paper is just the entrypoint.

Keeping coupled things in separate places makes iteration slow.
Software teams figured this out and pulled development, testing, and
infrastructure into the same repo.
Research projects tend to drift the other way:

- Datasets don't fit in Git, so they live on a shared drive.
- Expensive computations get run once and their outputs copied around by
  hand.
- Each script needs a different environment, and "works on my machine"
  creeps in.
- Figures are uploaded to Overleaf manually.
- Collaborators each have their own copy of the data and their own idea of
  which figure is current.

None of this is inevitable.
Git, uv, Make, and LaTeX will get a project to single-button
reproducible, and some people enjoy assembling that kind of setup.
The trouble usually comes later, when a collaborator who doesn't want to
learn it needs to add a figure or edit the paper.
Without an easier way in, the project drifts back to emailed files and
shared drives, and the single button becomes many buttons with manual
steps in between.

Calkit is a kit with the slots already there:
environments, datasets, notebooks, figures, publications,
and a pipeline connecting them, all described in `calkit.yaml`.
You put your pieces in.
If you've built this kind of setup yourself, it should feel familiar,
and your collaborators get the same project through a browser,
VS Code, or JupyterLab without needing to.
`calkit run` builds environments and runs only what changed,
`calkit clone` pulls cached outputs so expensive stages don't rerun,
`calkit save` handles Git and DVC together,
and the paper is a pipeline stage like any other.

One description of the whole project also makes it checkable.
Every figure and number can be traced to the stage that produced it,
and a rerun shows whether that's true.
With AI agents doing more of the work, this matters:
an agent can make a plausible figure as easily as a real one.

Underneath, it's still Git, DVC, Docker, Conda, uv, and LaTeX.
Nothing is hidden and nothing is locked in.

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
