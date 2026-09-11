# Making a README runnable

This tutorial turns an ordinary README into a pipeline whose examples are
run, and whose printed output is kept up to date, by Calkit.
For the full reference, see [Runnable Markdown](../pipeline/markdown.md).

## Start with a README

Make a new directory with a README in it, say `README.md`:

````md
# Wave statistics

Install the dependencies:

```sh
pip install numpy
```

Then compute the RMS of a damped wave:

```python
import numpy as np

t = np.linspace(0, 10, 401)
u = np.exp(-0.3 * t) * np.cos(2 * t)
print(f"rms: {np.sqrt(np.mean(u**2)):.4f}")
```
````

Nothing here is Calkit-specific yet.

## Run it

```sh
calkit xr README.md
```

Calkit annotates the Python block as a stage named `py`,
reads the `pip install` block as an environment named `readme`,
initializes the project if this directory isn't one already,
adds a `markdown` stage for the file to `calkit.yaml`,
builds the environment, and runs the stage.
Open the README and you'll see the fences now read:

````md
```sh calkit environment name=readme python=3.13
pip install numpy
```

```python calkit stage name=py environment=readme

```
````

Everything else is untouched.

## Show the output

Add a block for the stage's output anywhere in the file:

````md
```text calkit output stage=py

```
````

and run again:

```sh
calkit run README.md
```

The block now contains what the stage printed, e.g., `rms: 0.2933`.
Change the damping in the code block and run again, and the number
changes with it; edit the number by hand and the stage becomes stale,
since the README would otherwise be claiming something untrue.

## Give things better names

The generated names are placeholders.
Rename the stage and environment on the fences to whatever reads well,
e.g., `name=rms` and `name=py`, then run again;
Calkit removes the derived files and environment entry for the old
names.

## Commit it

```sh
calkit save -am "Make README runnable"
```

The environment spec and lock under `.calkit/envs/` are committed,
so anyone cloning the project gets the same environment.
The scripts extracted from the README are not;
they're regenerated on every run.

## Where to go from here

- Declare inputs and outputs on blocks so Calkit knows what depends on
  what, and so figures the README shows are the ones the code produced.
- Narrate one example across several blocks by giving them the same name.
- Add the [GitHub Action](github-actions.md) to run the README on every
  push.
