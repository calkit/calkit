# Quickstart

## From an existing project

If you want to use Calkit with an existing project,
navigate into its working directory and run:

```sh
calkit new project --public --cloud .
```

Note that the `--public` and `--cloud` options can be omitted,
but then you'll need to configure your own DVC remote or use Git to store
pipeline outputs.

Next, create your [environment(s)](environments.md).
In this example, imagine we have a `requirements.txt` file we want to use to
define a uv virtual environment, or venv:

```sh
calkit new uv-venv --name main --path requirements.txt --python 3.13
```

If you're using Conda for environment management,
e.g., with an `environment.yml` file,
you can use the `calkit new conda-env` command.

Next, we can start building our [pipeline](pipeline/index.md).
Let's say we have a Jupyter notebook called `collect-data.ipynb`
that produces raw data at `data/raw.h5`.
We can add a pipeline stage to run this notebook in the `main` environment
we just created with:

```sh
calkit new jupyter-notebook-stage \
    --name collect-data \
    --environment main \
    --notebook-path collect-data.ipynb \
    --output data/raw.h5
```

We can then run the pipeline with:

```sh
calkit run
```

and save and back up our results with:

```sh
calkit save -am "Run pipeline"
```

After that,
you can add more environments, pipeline stages,
[start a publication with LaTeX](tutorials/adding-latex-pub-docker.md),
or [link a publication with Overleaf](overleaf.md).

## Fresh from a Calkit project template

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

This will run the project's pipeline.
Next, you can start adding stages to the pipeline,
modifying the Python environments and scripts,
and editing the paper.
All will be kept in sync with the `calkit run` command.

To back up all of your work, execute:

```sh
calkit save -am "Run pipeline"
```

This will commit and push to both GitHub and the Calkit Cloud.
