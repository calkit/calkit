# Knoki: The knowledge creation kit

Knoki makes reproducibility automatic, because reproducibility means
productivity.

Like Git/GitHub, you don't need a cloud server or host to use knoki,
but it unlocks
some nice features,
such as the ability to backup your work,
offload simulation and/or data processing,
and of course collaborate with others.

In fact, Knoki works as a layer on top of Git,
so the main structure of the project is a Git repo.
The layer on top provides for data and software environment handling.

## Data connectors

Knoki's data storage model takes advantage of the user's local machine when
desired,
and automatically syncs with other storage locations as needed.
The goal is to be able to process data locally or in the cloud with
the same amount of effort, e.g.,
to test a pipeline locally but export to the cloud once it's
trustworthy,
maybe a small chunk of data is processed.

As it's needed, data is cached lazily in the local repository.

Similarly, if new data is created, e.g., from simulations, it can be
pushed to the cloud repository for post-processing, backup, or sharing.

## Building on someone else's work

1. Fork their project on knoki.io.
2. Import someone's figure into your project. You will be able to update.

## Features

Sometimes we may have Jupyter Notebooks with large outputs we want to be able
to save, but not in Git.
We strip output before putting into version control,
but allow the output to be pushed to the Knoki repo and pulled down.
So, if the notebook was run by a collaborator, or in the cloud,
you can view the output without needing to regenerate it,
and of course, it's not inflating the Git repo.

### Parameter sweeps that generate lots of data

For example, doing CFD simulations.
Do we want to be able to restore a full dataset from one run?
Or do we only want to have post-processed data?
