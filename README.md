# Calkit

[Calkit](https://calkit.io) makes reproducible research easy,
acting as a layer on top of
[Git](https://git-scm.com/) and [DVC](https://dvc.org/), such that all
all materials involved in the research process can be fully described in a
single repository.

## Installation

Simply run

```sh
pip install calkit
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
