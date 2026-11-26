# MyST documents

<!-- TODO: needs human review -->

[MyST](https://mystmd.org) builds websites and documents, e.g., a
notebook publication, from Markdown and notebooks.
Calkit builds a MyST project with `calkit myst build`,
run where its `myst.yml` is, in one of the project's environments,
with any arguments for `myst build` after `--`:

```sh
calkit myst build -e _system -- --html
```

<!-- TODO: needs human review -->

There's no MyST stage kind yet,
so a site is built by a `command` stage running `calkit myst build`
in the folder with its `myst.yml`,
listing what it's built from as `inputs`,
including the files its documents show:

```yaml
pipeline:
  stages:
    site:
      kind: command
      wdir: site
      command: calkit myst build -e _system -- --html
      environment: _system
      inputs:
        - index.md
        - myst.yml
        - ../figures/fit.png
      outputs:
        - _build/html
```

<!-- TODO: needs human review -->

MyST is part of an environment, like any other tool a stage runs,
e.g., `mystmd` in a Conda, Pixi, uv, or pip environment,
and `calkit myst build` fails rather than quietly using one installed on
this machine,
unless the project lists `myst` as a [requirement](requirements.md)
or the environment is `_system`.

## Showing where figures and tables came from

<!-- TODO: needs human review -->

As in a [Quarto document](quarto.md#showing-where-figures-and-tables-came-from),
a `ckprovenance` directive shows a figure or table with a panel saying
which stage made it, in which environment, what it read,
and whether it's up to date per `dvc.lock`,
so readers can see where it came from without Calkit:

```markdown
:::{ckprovenance} ../figures/fit.png
:label: fig-fit
:width: 80%
The fit, with its residuals.
:::

As [](#fig-fit) shows, ...

:::{ckprovenance} ../results/fits.csv
:label: tbl-fits
:rows: 10
Each run's fit.
:::
```

<!-- TODO: needs human review -->

The file is relative to the document,
and shown as MyST would show it, numbered and referred to by its label,
with the directive's content as its caption:
an image as a figure, a CSV or TSV file as a table,
up to `:rows:` rows (25 by default),
and anything else by its path, unless `:kind:` says otherwise, i.e.,
`figure`, `table`, or `file`.
With no file, it shows a panel about the document itself,
listing each pipeline output it's made from and whether each is up to
date, with a graph of the stages that make them,
which `:table: false` or `:graph: false` leaves out.
The panels say the same as they do in a Quarto document,
since Calkit works out what they say the same way for both.

<!-- TODO: needs human review -->

The directive comes from a MyST plugin Calkit writes beside `myst.yml`,
in `_extensions/calkit/myst.mjs`, which `myst.yml` lists:

```yaml
project:
  plugins:
    - _extensions/calkit/myst.mjs
```

`calkit myst build` fails if it's not listed, saying so.
Each time it builds, it works out what every panel says from
`calkit.yaml`, `dvc.lock`, and `.calkit/stage-runs.json`,
and writes it to `.calkit/local/provenance`, which isn't kept in Git,
for the plugin to read.
The document's own outputs, i.e., those of the stage that runs
`calkit myst build` in its folder, aren't checked,
since it can't say whether what's being built is up to date.
Building with MyST directly, e.g., with `myst start`,
shows the panels as of the last time Calkit built the project,
and `myst start` doesn't notice when a script or data file changes,
so a panel can say a figure is up to date when it isn't anymore
until the project is built again.
