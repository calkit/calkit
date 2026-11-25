<!-- TODO: needs human review -->

# Quarto example

A Quarto project whose documents show results from other stages,
each in its own language and environment:

1. `scripts/simulate.jl` simulates a damped oscillator in Julia,
   writing `data/sim.csv` and `results/sim.json`.
2. `analysis.ipynb` fits the damping ratio from the simulation in Python,
   writing `results/fit.json`,
   and shows the fit with Quarto's inline `{python}` expressions.
3. `report.qmd` plots the simulation in R,
   shows values from both results files with the `ckvalue` shortcode,
   and embeds the notebook's figure with Quarto's `embed` shortcode,
   which makes those files inputs to its stage automatically.

Run it with:

```sh
calkit run
```

Change the damping ratio in `scripts/simulate.jl` and run again:
the notebook and report render again with the new values.
The shortcode's extension is kept in Git, in `_extensions/calkit/`,
and reads values from the results files,
so `quarto render report.qmd` gives the same report without Calkit.
