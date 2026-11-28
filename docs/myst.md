# MyST documents

<!-- TODO: needs human review -->

[MyST](https://mystmd.org) builds websites and documents, e.g., a
notebook publication, from Markdown and notebooks.
Calkit builds a MyST project with `calkit doc build`,
given its folder, i.e., where its `myst.yml` is, or the `myst.yml` itself,
in one of the project's environments,
with any arguments for `myst build` after `--`:

```sh
calkit doc build site -e _system -- --html
```

Given a document in the project instead, e.g., `site/index.md`,
it builds only that document's exports, as `myst build` does given a file.
Either way it runs `calkit doc myst build` from the project's folder.

<!-- TODO: needs human review -->

In the pipeline, a `myst` stage builds its `target_path`,
which, as for `calkit doc build`, is the project's folder, its `myst.yml`,
or a document in it:

```yaml
pipeline:
  stages:
    site:
      kind: myst
      target_path: site
      environment: _system
      args: [--html]
      outputs:
        - site/_build/html
```

Its documents, their `myst.yml`, and the files and results files they
show or include are found when the pipeline compiles,
so they're inputs without being listed,
and the site is built again when they change.
`calkit doc build site` with no `-e` builds it as the stage does,
in its environment and with its arguments.

<!-- TODO: needs human review -->

MyST is part of an environment, like any other tool a stage runs,
e.g., `mystmd` in a Conda, Pixi, uv, or pip environment,
and `calkit doc build` fails rather than quietly using one installed on
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
and `ckinclude` a Markdown file's content, with its images found
relative to it, or any other file by its path.
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

Calkit reads and formats the values when it builds the project,
as Quarto and LaTeX documents format them,
so MyST doesn't read results files itself.
A `myst` stage depends on everything shown this way,
including results files, and a notebook's saved values, e.g.,
`.calkit/notebooks/outputs/fit.ipynb/values.json`.
A `command` stage running `calkit doc myst build` from the project's
folder has to list them as `inputs`,
and the build fails, naming what to add, when it doesn't.
Directives and roles in a file a document `{include}`s,
or shows with `ckinclude`, count for the document,
with an `{include}` inside an included file read relative to that file,
as MyST reads it, and those files are inputs too.
Roles aren't read in inline code, comments, or files included with
`:literal: true`, and are in a directive's argument, e.g., an
admonition's title.
The documents read are the ones MyST builds:
those `myst.yml`'s `toc` lists, or without one, every Markdown file and
notebook in its folder, except in `_build` and hidden folders,
either way leaving out what its `exclude` patterns match.

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
A value is followed by a small † mark, or a ! when it's out of date,
which names where it came from when it's hovered and links to that
value's view, collapsed, in a block at the end of the page,
which MyST also previews when the mark's hovered.
The marks are plain characters so every export can show them.
`:provenance: false`, or `provenance=false` in a role, turns it off for
one, and `show_provenance: false` in `calkit.yaml` for the whole project.
What's shown is worked out the same way it is for Quarto.
See [`examples/myst`](https://github.com/calkit/calkit/tree/main/examples/myst)
for a site that shows a figure, table, and values this way,
from three stages in Python.

<!-- TODO: needs human review -->

The directives and roles come from a MyST plugin Calkit writes beside
`myst.yml`, in `_extensions/calkit/myst.mjs`, which `myst.yml` lists:

```yaml
project:
  plugins:
    - _extensions/calkit/myst.mjs
```

The build fails if it's not listed, saying so.
Keep the plugin in Git, as with Quarto's extension,
since without it MyST builds the site anyway,
without what the directives and roles show.
It isn't an input of the build stage,
since Calkit writes it when the pipeline compiles and when it builds.
Calkit also writes `_extensions/calkit/myst.css`, which makes
book-theme show each collapsed section as a small, muted line, as in
Quarto, keeping what's wrong in a warning color, if `myst.yml` lists it:

```yaml
site:
  options:
    style: _extensions/calkit/myst.css
```

Each time it builds, it works out where everything came from,
and the values, and writes them to `.calkit/local/provenance`,
which isn't kept in Git, for the plugin to read.
The document's own outputs, i.e., those of the stage that builds the
project, aren't checked,
since it can't say whether what's being built is up to date.
Building with MyST directly, e.g., with `myst start`,
shows what was recorded the last time Calkit built the project,
saying so while collapsed if a document or a file it shows has changed
since, e.g., "Recorded before data/clean.csv changed".
A table's rows are read from its file as it's built,
so they're always current,
but a value is shown as Calkit last read and formatted it,
with a ! when its file has changed since,
since MyST doesn't read results files, and formatting them as Quarto and
LaTeX do would take reimplementing Python's formatting in the plugin.
A document Calkit hasn't built on this machine says nothing is recorded,
and shows `??` for its values.
`myst start` also doesn't notice when a script or data file changes,
so a view can say a figure is up to date when it isn't anymore
until the project is built again.
MyST doesn't tell its plugins which format it's building,
so other formats get the same collapsed sections:
its Word and LaTeX exports leave components' sections out,
reporting each as a node they can't show,
and include the values' views at the end, as boxes,
with emoji, e.g., ✅, that `pdflatex` may not typeset.
Its PDF and Typst exports haven't been checked yet.
`myst build --strict` reports the links in the views as unresolved,
and a link to a file at a commit that hasn't been pushed isn't made.
