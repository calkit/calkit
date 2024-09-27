# Calkit

[Calkit](https://calkit.io) simplifies reproducibility,
acting as a layer on top of
[Git](https://git-scm.com/), [DVC](https://dvc.org/),
[Zenodo](https://zenodo.org), and more,
such that all all aspects of the research process can be fully described in a
single repository.

## Why does reproducibility matter?

If your work is reproducible, that means that someone else can "run" it and
get the same results or outputs.
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

Git, GitHub, DVC, Zenodo et al. are amazing tools/platforms, but their
use involves multiple fairly difficult learning curves.
Our goal is to provide a single tool and platform to unify all of these so
that there is a single, gentle learning curve.
However, it is not our goal to hide or replace these underlying components.
Advanced users can use them directly, but new users aren't forced to, which
helps them get up and running with less effort and training.
Calkit should help users understand what is going on under the hood without
forcing them to work at that lower level of abstraction.

## Installation

Simply run

```sh
pip install calkit-python
```

## Cloud integration

The Calkit cloud platform (https://calkit.io) serves as a project
management interface and a DVC remote for easily storing all versions of your
data/code/figures/publications, interacting with your collaborators,
reusing others' research artifacts, etc.

After signing up, visit the [settings](https://calkit.io/settings) page
and create a token.
Then run

```sh
calkit config set token ${YOUR_TOKEN_HERE}
```

Then, inside a project repo you'd like to connect to the cloud, run

```sh
calkit config setup-remote
```

This will setup the Calkit DVC remote, such that commands like `dvc push` will
allow you to push versions of your data or pipeline outputs to the cloud
for safe storage and sharing with your collaborators.

## How it works

Calkit creates a simple human-readable "database" inside the `calkit.yaml`
file, which serves as a way to store important information about the project,
e.g., what question(s) it seeks to answer,
what files should be considered datasets, figures, publications, etc.
The Calkit cloud reads this database and registers the various entities
as part of the entire ecosystem such that if a project is made public,
other researchers can find and reuse your work to accelerate their own.
