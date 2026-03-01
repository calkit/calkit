# Quickstart

## From an existing project

If you want to use Calkit with an existing project,
navigate into its working directory and use the `xr` command to start
executing and recording your scripts, notebooks, LaTeX files, etc.,
as reproducible pipeline stages.
For example:

```sh
calkit xr scripts/analyze.py

calkit xr notebooks/plot.ipynb

calkit xr paper/main.tex
```

Calkit will attempt to detect environments, inputs, and outputs and
save them in `calkit.yaml`.
If successful,
you'll be able to run the full pipeline with:

```sh
calkit run
```

Next, make a change to e.g., a script and look at the output of
`calkit status`.
You'll see that the pipeline has a stage that is out-of-date:

```sh
---------------------------- Pipeline ----------------------------
analyze:
        changed deps:
                modified:           scripts/analyze.py
```

This can be fixed with another call to `calkit run`.

You can save (add and commit) all changes with:

```sh
calkit save -am "Add to pipeline"
```

## Fresh from a Calkit project template

Create a new project from the
[`calkit/example-basic`](https://github.com/calkit/example-basic)
template with:

```sh
calkit new project my-research \
    --title "My research" \
    --template calkit/example-basic \
    --cloud
```

Note the `--cloud` flag requires [cloud integration](cloud-integration.md)
to be set up, but can be omitted if the project doesn't need to be backed up to
the cloud or shared with collaborators.
Cloud integration can also be set up later.

Next, move into the project folder and run the pipeline,
which consists of several stages defined in `calkit.yaml`:

<!-- TODO: This takes a long time to pull the image -->

```sh
cd my-research
calkit run
```

Next, make some edits to a script or LaTeX file and run `calkit status` to
see what stages are out-of-date.
For example:

```sh
---------------------------- Pipeline ----------------------------
build-paper:
        changed deps:
                modified:           paper/paper.tex
```

Execute `calkit run` again to bring everything up-to-date.

To back up or save the project, call:

```sh
calkit save -am "Run pipeline"
```
