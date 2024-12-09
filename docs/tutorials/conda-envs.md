# Keeping track of conda environments

It can be difficult to know if a conda environment present on your machine
matches one in your project's `environment.yml` file.
You may be collaborating with a team on a project and someone adds a
dependency, then all of a sudden things won't run on your
machine.
Or maybe you use multiple machines to run the same project.

Calkit has a feature to make working with conda environments more
reproducible,
without needing to rebuild the environment all the time.
If you're working on a project with a conda `environment.yml` file,
you can simply run:

```sh
calkit check-conda-env
```

and the environment on your local machine will be rebuilt if it doesn't
match the spec,
or it will be created if it doesn't exist.
Note that this will delete the existing environment and rebuild from scratch,
so make sure you don't have any unsaved changes in there.
Also note that for some combinations of `pip` dependencies,
it may not be possible to arrive at an environment that matches the spec,
so it is recommended to only put the "top-level" dependencies in
`environment.yml` rather than a full export.

We can also add an environment check to our DVC pipeline
so if we're running any stages with that environment, we make sure
the environment is correct before doing so.
For example, we could have the following in `dvc.yaml`:

```yaml
stages:
  check-env:
    cmd: calkit check-conda-env
    deps:
      - environment.yml
    outs:
      - environment-lock.yml:
          cache: false
    always_changed: true
  run-my-script:
    cmd: conda run -n my-env python my-script.py
    deps:
      - my-script.py
      - environment-lock.yml
```

In the example above, we use the `always_changed` option so the conda env
will be checked in every call to `calkit run` or `dvc repro`.
If the output file `environment-lock.yml` changes,
DVC will rerun the `run-my-script` stage.
With the pipeline setup this way,
our collaborators (or ourselves on other computers)
can simply call `calkit run` without needing to think about
getting our conda environment into the correct state beforehand.

Note that this pattern can also be expanded to projects that use multiple
conda environments.
For example, if an environment spec is saved to `env-2.yml`,
we can call `calkit check-conda-env -f env-2.yml`.

## Adding a Conda environment to a Calkit project

If you run something like:

```sh
calkit new conda-env \
    -n my-project-py311 \
    python=3.11 \
    pip \
    matplotlib \
    pandas \
    jupyter \
    --pip tensorflow
```

Calkit will create an environment definition in `calkit.yaml`,
which enables running a command in this environment with
`calkit runenv -n my-project-py311 my-command-here`.
That call will automatically create or update the Conda environment on the fly
as needed and export a lock file describing the actual environment.
