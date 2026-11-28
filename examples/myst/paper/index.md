---
authors:
  - name: Calkit
abstract: |
  Noisy measurements of an exponential decay, the rate fitted to them,
  and where each came from.
exports:
  - format: typst
    output: paper.pdf
---

# Exponential decay

The measurements decay at a rate of {ckvalue}`results/fit.json rate .3f`
per unit time, a half-life of {ckvalue}`results/fit.json half_life .2f`,
fitted to {ckvalue}`results/fit.json n_points` points
(see [](#fig-fit) and [](#tbl-decay)).

:::{ckfigure} figures/fit.svg
:label: fig-fit
:width: 70%
The measurements, with the fitted decay.
:::

:::{cktable} data/decay.csv
:label: tbl-decay
:rows: 5
The first measurements.
:::
