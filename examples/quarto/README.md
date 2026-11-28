<!-- TODO: needs human review -->

# Quarto example

A Quarto project whose documents show results from other stages,
each in its own language and environment:

1. `scripts/simulate.jl` simulates a damped oscillator in Julia,
   writing `data/sim.csv` and `results/sim.json`.
2. `scripts/energy.py` works out the oscillator's energy from the
   simulation in Python, writing `results/energy.json` and
   `figures/energy.svg`.
3. `analysis.ipynb`, the main notebook, fits the damping ratio from the
   simulation in Python,
   writing `results/fit.json`, the peaks it fits in `results/peaks.csv`,
   and a plot of them in `figures/peaks.svg`.
   It shows the fit with Quarto's inline `{python}` expressions,
   and, in its Markdown cells, the simulation's first steps with
   `cktable`, the simulated damping ratio and the energy lost each cycle
   with `ckvalue`, and the energy's plot with `ckfigure`.
4. `report.qmd` plots the simulation in R,
   shows values from both results files with the `ckvalue` shortcode,
   embeds the notebook's figure with Quarto's `embed` shortcode,
   and shows the peaks' plot and table with `ckfigure` and `cktable`
   divs, which makes those files inputs to its stage automatically.

Run it with:

```sh
calkit run
```

Change the damping ratio in `scripts/simulate.jl` and run again:
the notebook and report render again with the new values.

The shortcode's extension is kept in Git, in `_extensions/calkit/`,
and reads values from the results files,
so `quarto render report.qmd` gives the same report without Calkit.

<!-- TODO: needs human review -->

In `analysis.html` and `report.html`, look under the figures and
tables shown with `ckfigure` and `cktable` for a collapsed
"Provenance" line:
opened, it shows how each came to be,
a graph of the stages it's made from, starting from the Julia
simulation,
and each stage's environment, script, last run, and inputs,
with links to them on GitHub.
Each value shown with `ckvalue` is underlined;
selecting it shows the same for the value.
Edit `scripts/simulate.jl` and render the report with
`calkit doc build report.qmd`, without running the
pipeline, to see them say they're out of date while collapsed.

<!-- TODO: needs human review -->

## Starting a project from this example

```sh
calkit new project my-project --from calkit/calkit/examples/quarto
```
