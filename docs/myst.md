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
including the files and results files its documents show,
which `calkit myst build` fails without, so the site is built again when
they change:

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

## Figures, tables, files, and values from the pipeline

<!-- TODO: needs human review -->

A document can show a figure, table, or other file from anywhere in the
project by its path, as LaTeX's `\ckfigure`, `\cktable`, and `\ckinclude`
and [Quarto's](quarto.md#figures-tables-and-other-files-from-the-pipeline)
divs do, with directives like MyST's own `figure`,
whose content is the caption:

```markdown
:::{ckfigure} figures/fit.png
:label: fig-fit
:width: 80%
The fit, with its residuals.
:::

:::{cktable} results/fits.csv
:label: tbl-fits
:rows: 10
Each run's fit.
:::

:::{ckinclude} results/summary.md
:::
```

<!-- TODO: needs human review -->

Paths are relative to the project.
`ckfigure` shows an image as a numbered figure, with `figure`'s options,
e.g., `width`, `cktable` a CSV or TSV file as a numbered table,
up to `:rows:` rows (25 by default),
and `ckinclude` a Markdown file's content, or any other file by its path.
`:name:` works as `:label:` does, and options can be lines or a YAML
block.

<!-- TODO: needs human review -->

Values are shown with the `ckvalue` and `ckrefval` roles,
whose content reads as Quarto's shortcodes' arguments do,
e.g., a results file or a declared result's name, a key, and a format,
or a notebook and the variable a cell saved:

```markdown
The slope is {ckvalue}`results/fit.json fit.slope .3f`,
and k is {ckvalue}`fit.ipynb k_25 .3f`,
as in {ckrefval}`liu2025 noise-sigma`.
```

<!-- TODO: needs human review -->

`calkit myst build` reads and formats the values, as Quarto and LaTeX
documents format them, so MyST doesn't read results files itself.
Everything shown this way has to be among the build stage's `inputs`,
including results files, and a notebook's saved values, e.g.,
`.calkit/notebooks/outputs/fit.ipynb/values.json`;
`calkit myst build` fails, naming what to add, when it isn't.
That's checked when the stage runs,
so a stage set up before an input was missing is caught the next time it
runs.
Directives and roles in a file a document `{include}`s count for the
document.

## Showing where they came from

<!-- TODO: needs human review -->

As in a [Quarto document](quarto.md#showing-where-figures-tables-and-values-came-from),
each component is shown with where it came from collapsed under it,
saying what's wrong while it's collapsed, e.g.,
"Out of date: scripts/clean.py modified",
and, opened, a graph of the stages it's made from and nothing else,
then each of them, with its kind, environment, script or command,
last run, every input, and what it makes on the way,
with links to files on GitHub or GitLab and to components shown in the
document.
A value is followed by a small mark, or a ⚠ when it's out of date,
linking to where it came from, which MyST shows when the mark's hovered,
in a collapsed section at the end of the document.
`:provenance: false`, or `provenance=false` in a role, turns it off for
one, and `show_provenance: false` in `calkit.yaml` for the whole project.
What's shown is worked out the same way it is for Quarto.

<!-- TODO: needs human review -->

The directives and roles come from a MyST plugin Calkit writes beside
`myst.yml`, in `_extensions/calkit/myst.mjs`, which `myst.yml` lists:

```yaml
project:
  plugins:
    - _extensions/calkit/myst.mjs
```

`calkit myst build` fails if it's not listed, saying so.
Keep the plugin in Git, as with Quarto's extension,
since without it MyST builds the site anyway,
without what the directives and roles show.
Each time it builds, it works out where everything came from,
and the values, and writes them to `.calkit/local/provenance`,
which isn't kept in Git, for the plugin to read.
The document's own outputs, i.e., those of the stage that runs
`calkit myst build` in its folder, aren't checked,
since it can't say whether what's being built is up to date.
Building with MyST directly, e.g., with `myst start`,
shows what was recorded the last time Calkit built the project,
saying so if a document has changed since;
a document Calkit hasn't built on this machine says nothing is recorded,
with each table shown only by its path, keeping its label,
and shows `??` for its values.
`myst start` also doesn't notice when a script or data file changes,
so a view can say a figure is up to date when it isn't anymore
until the project is built again.
MyST doesn't tell its plugins which format it's building,
so other formats get the same collapsed sections:
its Word export leaves them out, reporting each as a node it can't show,
and its other exports haven't been checked yet.
