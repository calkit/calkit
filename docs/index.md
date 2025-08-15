# Home

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

- A declarative pipeline that forces users to define an environment
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

See [installation](installation.md).
