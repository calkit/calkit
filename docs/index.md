# Home

Calkit's mission is to make every scientific study reproducible.
That is,
it should be possible to go from raw data to research article
by "pressing a single button"
([Claerbout and Karrenbach (1992)](https://doi.org/10.1190/1.1822162)).

Calkit makes this level of automation possible without extensive software
engineering expertise by providing a project framework and toolset that unifies
and simplifies the use of enabling technologies like Git,
DVC, Conda, Docker, and more,
while guiding users away from common reproducibility pitfalls.

When your project is reproducible,
you'll be able to iterate more quickly and more often,
easily onboard collaborators,
make fewer mistakes,
and feel confident sharing all of your project materials
with your research articles,
because you'll know the code will actually run!
This will allow others to reuse parts of your project in their own research,
accelerating the pace of discovery.

## Features

- A declarative pipeline that forces users to define an environment
  for every stage, so long lists of instructions in a README and
  "but it works on my machine" are things of the past.
- A CLI to run the project's pipeline to verify it's reproducible,
  regenerating outputs as needed and
  ensuring all
  computational environments (e.g., [Conda](https://docs.conda.io/en/latest/), [Docker](https://docker.com)) match their specification.
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
