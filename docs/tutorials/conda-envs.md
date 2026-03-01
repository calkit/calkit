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
you can add it to the project's environments in `calkit.yaml`:

```yaml
environments:
  my-conda:
    kind: conda
    path: environment.yml
```

Then, any time a command is run in that environment, e.g., with:

```sh
calkit xenv -n my-conda -- python -c "print('hello world')"
```

the environment on your local machine will be rebuilt if it doesn't
match the spec,
or it will be created if it doesn't exist.
Note that this will delete the existing environment and rebuild from scratch,
so make sure you don't have any unsaved changes in there.
Also note that for some combinations of `pip` dependencies,
it may not be possible to arrive at an environment that matches the spec,
so it is recommended to only put the "top-level" dependencies in
`environment.yml` rather than a full export.

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

Calkit will create an environment definition in `calkit.yaml`
and a corresponding `environment.yml` file.
If you need multiple conda environments,
you can run this command multiple times, changing the `--path` option.
