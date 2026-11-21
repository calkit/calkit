# Calkit subprojects example

This example shows how to use subprojects.

Each subproject is a complete Calkit project,
with its own `calkit.yaml`, environment, and pipeline,
so it can be worked on and run from its own directory.
The project at the top holds nothing but its subprojects,
and running or checking it covers all of them:

```text
.
├── calkit.yaml          # Declares experiment and analysis
├── experiment/
│   ├── calkit.yaml      # Declares calibration
│   ├── calibration/     # A subproject of a subproject
│   └── scripts/collect.py
└── analysis/
    ├── calkit.yaml
    └── scripts/fit.py
```

The calibration fits a sensor's gain,
the experiment collects measurements with that gain applied,
and the analysis fits and plots those measurements.
Since the experiment's stage takes the calibration's results as an input,
and the analysis's stage takes the experiment's measurements,
the stages run in that order,
even though they're declared in three different projects.

## Running it

From here, run everything with:

```sh
calkit run
```

A subproject's stages are named by its path,
as `calkit status` and `calkit list stages` show them,
and a subproject can be run as a whole:

```sh
calkit run experiment/calibration:calibrate
calkit run experiment
```

A subproject can also be named by its directory alone,
as long as no other subproject has the same one:

```sh
calkit run calibration:calibrate
```

Requirements and environments are checked for every subproject too,
before anything runs:

```sh
calkit check reqs
calkit check environments
```

To see the subprojects and what each one declares, run:

```sh
calkit list subprojects
calkit describe subprojects
```

## Sharing a DVC repo

These subprojects have no `.dvc` directory of their own,
so they share this project's DVC repo,
and their stages run as part of its pipeline.
A subproject with its own `.dvc` directory is isolated instead:
it keeps its own DVC repo, and runs as a single stage of the project
above it.

See the [subprojects docs](https://docs.calkit.org/subprojects/)
for more.
