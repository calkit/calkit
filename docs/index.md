# Home

Calkit is a language-agnostic project framework and toolkit
to make your research or analytics project
reproducible to the highest standard,
which means:

> Inputs and process definitions are provided and sufficiently described
> such that anyone can easily verify that they produced the outputs
> used to support the conclusions.

"Easily" means that after obtaining your project files,
it should only require executing a single command
(like "pressing a single button" in
[Claerbout and Karrenbach (1992)](https://doi.org/10.1190/1.1822162)),
which should finish in less than 15 minutes
(suggested by
[Vandewalle et al. (2009)](https://doi.org/10.1109/MSP.2009.932122)).

If the processes are too expensive to rerun in under 15 minutes,
it should be possible to confirm that none of the input data
or process definitions (e.g., environment specifications, scripts)
have changed since saving the current versions of each output artifact
(figure, table, dataset, publication, etc.)

When your project is reproducible,
you'll be able to iterate more quickly and more often,
easily onboard collaborators,
make fewer mistakes,
and feel confident sharing all of your project materials
with your research articles,
because you'll know the code will actually run!
This will allow others to reuse parts of your project in their own research,
accelerating the pace of discovery.

Working at this level of automation, discipline, and rigor may sound like
a lot of effort,
but Calkit makes it easy!

## Features

- A declarative pipeline that forces users to define an environment
  for every stage, so "but it works on my machine" is a thing of the past.
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
- A complementary
  [cloud system](https://github.com/calkit/calkit-cloud)
  to facilitate backup, collaboration,
  and sharing throughout the entire research lifecycle.

## Installation

See [installation](installation.md).
