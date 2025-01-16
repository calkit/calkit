# Home

Calkit is an open source
framework and toolkit for reproducible research projects.
It acts as a top-level layer to integrate and simplify the use of enabling
technologies such as
[Git](https://git-scm.com/),
[DVC](https://dvc.org/),
[Conda](https://docs.conda.io/en/latest/),
and [Docker](https://docker.com).
Calkit also adds a domain-specific data model
such that all aspects of the research process can be fully described in a
single repository and therefore easily consumed by others.

Our goal is to make reproducibility easier so it becomes more common.
To do this, we try to make it easy for users to follow two simple rules:

1. **Keep everything in version control.** This includes large files like
   datasets, enabled by DVC.
   The [Calkit Cloud](https://github.com/calkit/calkit-cloud),
   hosted at [calkit.io](https://calkit.io),
   serves as a simple default DVC remote storage location for those who do not
   want to manage their own infrastructure.
2. **Generate all important artifacts with a single pipeline.** There should be
   no special instructions required to reproduce a project's artifacts.
   It should be as simple as calling `calkit run`.
   The DVC pipeline (in a project's `dvc.yaml` file) is therefore the main
   thing to "build" throughout a research project.
   Calkit provides helper functionality to build pipeline stages that
   keep computational environments up-to-date and label their outputs for
   convenient reuse.

## Features

- A [version control interface](version-control.md)
  that unifies and simplifies interaction with Git and DVC.
- Automated [environment management](environments.md).
- A [project metadata model](calkit-yaml.md)
  to declare global dependencies, environments,
  and artifacts like datasets, figures, notebooks, and publications
  to facilitate searchability and reuse.
- A complementary [cloud platform](https://calkit.io) to interact with
  the project and its artifacts, which also serves as a DVC remote.
- Templates for projects, publications, and more.
- The ability to declare, execute, and track
  [manual procedures](tutorials/procedures.md) and
  pipeline stages with [manual steps](pipeline/manual-steps.md).
- A Jupyter cell magic to
  [use notebook cells as pipeline stages](tutorials/notebook-pipeline.md).
- Tools to help improve the reproducibility of workflows that depend on
  [Microsoft Office](tutorials/office.md).
