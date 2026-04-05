# Home

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

- Quality comes from iteration. Automation helps reduce the time and effort
  needed to iterate, thereby increasing the number of iterations done on
  any given project.
- Automating a step usually takes the same amount of time as doing it once
  manually, therefore it's almost always worth it.

## Features

- A simplified [version control](version-control.md)
  interface that unifies Git and DVC (Data Version Control),
  so all materials can be kept in the same project repository.
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
  [cloud platform](https://github.com/calkit/calkit-cloud)
  to facilitate backup, collaboration,
  and sharing throughout the entire research lifecycle.
- [Overleaf integration](https://docs.calkit.org/overleaf/), so
  analysis, visualization, and writing can all stay in sync
  (no more manual uploads!)
- Support for running on high performance computing (HPC) systems that use
  [SLURM schedulers](pipeline/slurm.md).
- Support for running with [GitHub Actions](tutorials/github-actions.md).
- Extensions for doing all of the above graphically in
  [JupyterLab](jupyterlab.md) and
  [VS Code](https://marketplace.visualstudio.com/items?itemName=Calkit.calkit-vscode).
