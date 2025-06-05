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

To install Calkit, [Git](https://git-scm.com) and Python must be installed.
If you want to use [Docker](https://docker.com) containers,
which is typically a good idea,
that should also be installed.
For Python, we recommend
[uv](https://docs.astral.sh/uv/).

With uv installed, install Calkit with:

```sh
uv tool install calkit-python
```

Alternatively, but less ideally, you can install with your system Python:

```sh
pip install calkit-python
```

For Windows users, the
[Calkit Assistant](https://github.com/calkit/calkit-assistant)
app is the easiest way to get everything set up and ready to work in
VS Code, which can then be used as the primary app for working on
all scientific or analytical computing projects.

## Cloud integration

The Calkit Cloud ([calkit.io](https://calkit.io)) serves as a project
management interface and a DVC remote for easily storing all versions of your
data/code/figures/publications, interacting with your collaborators,
reusing others' research artifacts, etc.

After signing up, visit the
[settings](https://calkit.io/settings?tab=tokens)
page and create a token for use with the API.
Then run

```sh
calkit config set token ${YOUR_TOKEN_HERE}
```

## Quickstart

After installing Calkit and setting your token as described above, run:

```sh
calkit new project calkit-project-1 \
    --title "My first Calkit project" \
    --template calkit/example-basic \
    --cloud \
    --public
```

This will create a new project from the
[`calkit/example-basic`](https://github.com/calkit/example-basic)
template,
creating it in the cloud and cloning to `calkit-project-1`.
You should now be able to run:

```sh
cd calkit-project-1
calkit run
```

This will reproduce the project's pipeline.
Next, you can start adding stages to the pipeline,
modifying the Python environments and scripts,
and editing the paper.
All will be kept in sync with the `calkit run` command.

To back up all of your work, execute:

```sh
calkit save -am "Run pipeline"
```

This will commit and push to both GitHub and the Calkit Cloud.

## Get involved

We welcome all kinds of contributions!
See [CONTRIBUTING.md](CONTRIBUTING.md) to learn how to get involved.

## Design/UX principles

1. Be opinionated. Users should not be forced to make unimportant decisions.
   However, if they disagree, they should have the ability to change the
   default behavior. The most common use case should be default.
   Commands that are commonly executed as groups should be combined, but
   still available to be run individually if desired.
1. Commits should ideally be made automatically as part of actions that make
   changes to the project repo. For
   example, if a new object is added via the CLI, a commit should be made
   right then unless otherwise specified. This saves the trouble of running
   multiple commands and encourages atomic commits.
1. Pushes should require explicit input from the user.
   It is still TBD whether or not a pull should automatically be
   made, though in general we want to encourage trunk-based development, i.e.,
   only working on a single branch. One exception might be for local
   experimentation that has a high likelihood of failure, in which case a
   branch can be a nice way to throw those changes away.
   Multiple branches should probably not live in the cloud, however, except
   for small, quickly merged pull requests.
1. Idempotency is always a good thing. Unnecessary state is bad. For example,
   we should not encourage caching pipeline outputs for operations that are
   cheap. Caching should happen either for state that is valuable on its
   own, like a figure, or for an intermediate result that is expensive to
   generate.
1. There should be the smallest number of
   frequently used commands as possible, and they should require as little
   memorization as possible to know how to execute, e.g., a user should be
   able to keep running `calkit run` and that's all they really need to do
   to make sure the project is up-to-date.
