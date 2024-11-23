# Using a Jupyter Notebook as a reproducible pipeline

Jupyter Notebooks are great tools for exploration,
but they can cause real headaches when it comes to managing state,
since they can be executed out-of-order.
This can lead to bad practices like only running certain cells
since others are too expensive or failing.
This means it's very possible for a result from a notebook to be
non-reproducible.

Here we're going to show how to use Calkit to turn a Jupyter Notebook
into a DVC pipeline,
as well as label our artifacts.

The natural process would be something like:

1. Prototype a cell by running whatever commands make sense.
2. Convert cells that are working and valuable into pipeline
   stages, and delete anything else.

We should also be using [`nbstripout`](https://github.com/kynan/nbstripout)
to strip notebook outputs before we commit to the repo,
since the important ones will be produced as part of the pipeline
and cached with DVC.

At the end of this process we should be left with a notebook that runs
very quickly after it's been run once,
and all of our important outputs will be cached and pushed to the cloud,
but kept out of our Git repo.

Alright, so let's show how to convert a notebook into a reproducible
DVC pipeline without leaving the notebook interface.

First, let's write a cell to fetch a dataset,
and let's assume this is expensive,
maybe because we had to fetch it from a database.
To simulate that expense we'll use a call to `time.sleep`.

```python
import pandas as pd
import time

time.sleep(10)

df = pd.DataFrame({"col1": range(1000)})
df.describe()
```

In order to convert this cell into a pipeline stage,
we'll need to load the Calkit magics in our notebook.
This only needs to be run once, so it can be at the very top:

```python
%load_ext calkit.magics
```

Next we simply call the `%%stage` magic with the appropriate arguments to
convert the cell into a pipeline stage and run it externally with DVC:

```python
%%stage --name get-data --out df

import pandas as pd
import time

time.sleep(10)

df = pd.DataFrame({"col1": range(1000)})
df.describe()
```

In the magic call, we gave the stage a name and declared an output `df`.
When we run the cell, we'll see it takes at least 10 seconds the first time,
but if we run it a second time,
it will be much faster, since our output is being fetched from the DVC cache.
If we run `calkit status`, we can see we have some new data to commit and
push to the DVC remote.
If we do that, anyone else who clones this project will be able to
pull in the cache, and the cell will run quickly for them.

## Saving outputs in different formats

By default, our output variables will be pickled,
which is not the most portable format.
Let's instead save our DataFrame to Parquet format.
To do this, all we need to do is adjust the `--out` value to add the format
and DataFrame library
(Calkit currently supports both Pandas and Polars DataFrames.)
So change the call to the magic to be:

```python
%%stage --name get-data --out df:parquet:pandas
```

## Using the output of one cell as a dependency in another

Let's imagine that now we want to create a visualization of our data.
Just like if we were creating a typical DVC stage in a `dvc.yaml` file,
we can declare a cell to depend on the output of another cell with the
`--dep` command.
For example:

```python
%%stage --name plot --dep get-data:df:parquet:pandas --out fig

fig = df.plot(backend="plotly")
fig
```

In this case, we need to specify what DataFrame library to use to read in
this dependency.
Here we tell Calkit that it's a Parquet file to be read with Pandas.
Calkit will ensure this dependency is loaded into memory before running the
cell as part of the pipeline.

## Declaring an output as a figure saved to a different path

In the cell above we end up pickling `fig` into the DVC cache,
which is fine if we only ever want to view the figure through the notebook
interface,
but what if we want to declare this as a figure and, e.g.,
use it in a publication?
We can add a line that saves the figure and declare an additional output path
and metadata like (note this requires `plotly` and `kaleido` to be installed):

```python
%%stage --name plot --dep get-data:df:parquet:pandas --out fig --out-path figures/plot.png --out-type figure --out-title "A plot of the data" --out-desc "This is a plot of the data."

import os

os.makedirs("figures", exist_ok=True)

fig = df.plot(backend="plotly")
fig.write_image("figures/plot.png")
fig
```

If we call `calkit list figures`, we'll see our figure,
and after pushing to the cloud, we'll be able to see it there as well.

Note that we could also go back and add `--out-type=dataset` to the
`get-data` cell,
which will similarly add that dataset to our project metadata
for searchability and reuse.

## Running the pipeline outside the notebook

One cool feature about building the pipeline this way is that it actually
creates runnable stages in `dvc.yaml`,
so `calkit run` or `dvc repro` will run all the same operations that
executing the notebook would.

## Further exploration

If you'd like to try this out or explore further,
you can view this project up on
[GitHub](https://github.com/calkit/example-notebook-pipeline)
or the [Calkit cloud](https://calkit.io/calkit/example-notebook-pipeline).
