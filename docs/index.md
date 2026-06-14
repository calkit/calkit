# Home

It's six months since you submitted your paper,
do you know exactly how your figures and results were generated?

You will if they're part of a Calkit project.

Calkit helps you integrate code, data, figures, results, publications,
and more into a cohesive, traceable, and portable _knowledge creation system_,
so every output can be traced back to its source and reproduced with a
single command.

With industry standard tools combined into a unified and simplified experience
tailored for research,
you can reap the rewards of reproducibility and automation
without the cognitive overhead.

<!-- https://docs.google.com/drawings/d/1XMGnbgYYNFAVUBDyUaCyLfRB7efvJdrnrKmFlNmT19o/edit -->

![pipeline](/img/pipeline.png)

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
  [cloud platform](https://github.com/calkit/calkit-cloud)
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
