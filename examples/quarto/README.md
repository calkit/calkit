<!-- TODO: needs human review -->

# Quarto example

A Quarto project whose documents show results from other stages,
each in its own language and environment:

1. `scripts/simulate.jl` simulates a damped oscillator in Julia,
   writing `data/sim.csv` and `results/sim.json`.
2. `analysis.ipynb` fits the damping ratio from the simulation in Python,
   writing `results/fit.json`, the peaks it fits in `results/peaks.csv`,
   and a plot of them in `figures/peaks.svg`,
   and shows the fit with Quarto's inline `{python}` expressions.
3. `report.qmd` plots the simulation in R,
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

In `report.html`, look under Figure 2 and Table 1 for a collapsed
"Provenance" line:
opened, it shows how each came to be,
a graph of the stages it's made from, from the Julia simulation through
the notebook,
and each stage's environment, script, last run, and inputs,
with links to them on GitHub.
The number of peaks in the first paragraph is underlined;
selecting it shows the same for the value.
Edit `scripts/simulate.jl` and render the report with
`calkit quarto render -e quarto report.qmd`, without running the
pipeline, to see them say they're out of date while collapsed.
