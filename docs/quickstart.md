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

## Fresh from a Calkit project template

After installing Calkit and setting your token, run:

```sh
calkit new project my-research \
    --title "My research" \
    --template calkit/example-basic
```

This will create a new project from the
[`calkit/example-basic`](https://github.com/calkit/example-basic)
template.
You should now be able to run:

<!-- TODO: This takes a long time to pull the image -->

```sh
cd my-research
calkit run
```

This will run check all of the project's environments and
run the pipeline.
Next, you can start adding stages to the pipeline,
modifying the Python environments and scripts,
and editing the paper.
All will be kept in sync with the `calkit run` command.

To back up all of your work, execute:

```sh
calkit save -am "Run pipeline"
```

This will commit and push to both GitHub and the Calkit Cloud.
