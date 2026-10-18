# Calkit multi-HPC example

This example shows how to run a Calkit project on multiple HPC clusters,
optionally using different schedulers, i.e.,
one that uses SLURM and one that uses PBS.

With this setup, the simulation can be run from either cluster depending
on where it's being run from.
Anywhere else, e.g., on a laptop, it's skipped and stays out of date in
`calkit status`, so it never runs there by accident.
The plotting stage runs anywhere uv is installed, including either
cluster.
Elsewhere, it uses the simulation's results once `calkit pull` has
fetched them.

To try it without a cluster, change one option's `hostname_matches` to
match this machine, e.g., `"*"`, and run:

```sh
calkit run --mock-scheduler
```

which runs scheduler jobs directly on this machine.

A mocked run is recorded in the switch's lock,
`.calkit/env-locks/either-cluster/switch.json`,
so results from a mocked run are never taken for ones from a real
cluster:
the next real run reruns its stages,
and so does a mocked run after a real one.
That's also why `calkit status` lists the simulation as out of date
after a mocked run.
