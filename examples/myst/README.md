<!-- TODO: needs human review -->

# MyST example

A [MyST](https://mystmd.org) site that shows a figure, a table, and values
from the stages before it, with where each came from:

1. `scripts/generate.py` generates noisy measurements of a quantity
   decaying exponentially, writing `data/decay.csv`.
2. `scripts/fit.py` fits the decay rate, writing `results/fit.json`.
3. `scripts/plot.py` plots the measurements with the fit,
   writing `figures/fit.svg`.
4. `paper/index.md` shows the plot with the `ckfigure` directive,
   the first measurements with `cktable`,
   and the fitted rate, half-life, and number of points with the
   `ckvalue` role.

Python and MyST both come from the Pixi environment in `pixi.toml`.
Run it with:

```sh
calkit run
```

The `paper` stage builds the site with `calkit myst build`,
which works out where each figure, table, and value came from,
and writes the MyST plugin that shows them,
in `paper/_extensions/calkit/`, kept in Git,
which `paper/myst.yml` lists along with its stylesheet.
To see the site, run `myst start` in `paper/`,
e.g., with `pixi run --manifest-path ../pixi.toml myst start`.

<!-- TODO: needs human review -->

Look under Figure 1 and Table 1 for a collapsed "Provenance" dropdown:
opened, it shows a graph of the stages each is made from,
from generating the data through the fit to the plot,
and each stage's environment, script, last run, and inputs.
Each value in the first paragraph is followed by a small mark linking to
the same for it, at the end of the page.
Change the decay rate in `scripts/generate.py` and run again:
the site is built again with the new figure, table, and values.
