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

Calkit is a framework and toolkit for reproducible research projects.
It acts as a top-level layer to integrate and simplify the use of enabling
technologies such as
[Git](https://git-scm.com/),
[DVC](https://dvc.org/),
[Conda](https://docs.conda.io/en/latest/),
and [Docker](https://docker.com).
Calkit also adds a domain-specific data model
such that all aspects of the research process can be fully described in a
single repository and therefore easily consumed by others.

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

## Why does reproducibility matter?

If your work is reproducible, that means that someone else can "run" it and
calculate the same results or outputs.
This is a major step towards addressing
[the replication crisis](https://en.wikipedia.org/wiki/Replication_crisis)
and has some major benefits for both you as an individual and the research
community:

1. You will avoid mistakes caused by, e.g., running an old version of a script
   and including a figure that wasn't created after fixing a bug in the data
   processing pipeline.
2. Since your project is "runnable," it's more likely that someone else will be
   able to reuse part of your work to run it in a different context, thereby
   producing a bigger impact and accelerating the pace of discovery.
   If someone can take what you've done and use it to calculate a
   prediction, you have just produced truly useful knowledge.

## Why another tool/platform?

Git, GitHub, DVC, Docker et al. are amazing tools/platforms, but their
use involves multiple fairly difficult learning curves,
and tying them together might mean developing something new for each project.
Our goal is to provide a single tool and platform to unify all of these so
that there is a single, gentle learning curve.
However, it is not our goal to hide or replace these underlying components.
Advanced users can use them directly, but new users aren't forced to, which
helps them get up and running with less effort and training.
Calkit should help users understand what is going on under the hood without
forcing them to work at that lower level of abstraction.

## How it works

Calkit creates a simple human-readable "database" inside the `calkit.yaml`
file, which serves as a way to store important information about the project,
e.g., what question(s) it seeks to answer,
what files should be considered datasets, figures, publications, etc.
The Calkit cloud reads this database and registers the various entities
as part of the entire ecosystem such that if a project is made public,
other researchers can find and reuse your work to accelerate their own.

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
