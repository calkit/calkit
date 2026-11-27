# Quarto documents

[Quarto](https://quarto.org) is a document publishing system and
literate programming tool that allows you to execute
code inside documents, e.g., for doing calculations, creating figures, etc.
Because it might be unintuitive to write heavy data processing or simulation
code into a document,
Calkit enables those steps to be done with other kinds of pipeline stages that
reproducibly integrate and feed a Quarto stage derived artifacts like reduced
datasets, results, or figures,
so that cheap calculations and transformations can stay in Quarto.

A [`quarto` stage](pipeline/index.md#quarto) renders a Quarto document,
`.qmd` or `.ipynb`, in one of the project's environments:

```yaml
pipeline:
  stages:
    report:
      kind: quarto
      target_path: index.ipynb
      environment: main
      args: [--execute]
```

## Which Quarto is used?

Quarto is part of a stage's environment,
like any other tool a stage runs,
so a document renders with the same version on every machine:
add `quarto` to a Conda or Pixi environment,
or `quarto-cli` to a uv or pip one.
The stage renders with `calkit quarto render`,
which checks that the environment has it included, i.e.,
that it's not actually on the path from a system-wide install,
and fails rather than quietly using whatever version is installed on the
machine.
To use Quarto installed outside an environment on purpose,
list it in the project's [requirements](requirements.md):

```yaml
requirements:
  - quarto
```

## Notebooks

Rendering a notebook with `--execute` writes its outputs back into it,
which is what a site built from it shows.
The stage depends on the notebook with its outputs stripped,
as a [notebook stage](notebooks.md) does,
so re-running cells interactively doesn't make it out of date,
while editing a cell's code or prose does.
Without `--execute`, Quarto shows the outputs saved in the notebook,
so the stage depends on them too.

## Values from the pipeline

A document can show values from a results file written by another stage
with the `ckvalue` shortcode,
which reads like its [Markdown](pipeline/markdown.md#values) and
[LaTeX](latex.md#including-project-components) counterparts:
a results file, or the name of a declared result, a key, and optionally a
Python format spec, positionally or by name.

```markdown
The RMS is {{< ckvalue results/metrics.json rms .3f >}}
over {{< ckvalue results/metrics.json key=fit.n >}} samples.
```

Paths are relative to the project.
Results files can be JSON, YAML, or TOML,
and keys are separated by dots to reach into nested values.
Formats take a sign, a `,` or `_` separator, and a precision and type,
e.g., `.2f`, `,d`, or `.1%`, or a template, e.g., `{value:.1f} m/s`.
The results files are inputs to the stage,
so a change to a value renders the document again.

<!-- TODO: needs human review -->

<!-- TODO: needs human review -->

A value quoted from a reference is shown with
`{{< ckrefval citation-key name format >}}`, from what `calkit.yaml`
records for the reference.
See [quoting values from references](references.md#quoting-values-from-references).

To show a value saved from a notebook cell, use the notebook's path
instead of a results file, e.g., `{{< ckvalue fit.ipynb k_25 .3f >}}`.
See [saving values from cells](notebooks.md#saving-values-figures-and-tables-from-cells)
for more info.

<!-- TODO: needs human review -->

`calkit check repro -c numbers` lists numbers typed into a Quarto document
that has a stage, including a notebook's Markdown cells,
that look like results but have nothing recorded behind them,
so they can be read from the pipeline instead.
Numbers in shortcodes, inline expressions, and code are left out,
as is a line with a `<!-- calkit: ignore -->` comment.

<!-- TODO: needs human review -->

When the pipeline is compiled,
Calkit writes the shortcode as a Quarto extension in `_extensions/calkit/`,
in the Quarto project's folder, i.e., where `_quarto.yml` is,
or beside the document if there isn't one,
so documents can use it without listing it.
It reads each value from its results file when the document renders,
so with the extension kept in Git,
the document renders the same without Calkit, e.g., when a site is
published by `quarto publish`,
as long as its results files are on this machine.
Before the stage renders, Calkit checks each value can be shown,
naming the line of any that can't.

<!-- TODO: needs human review -->

A document that runs code can also show values with Quarto's inline
expressions, e.g., `` `{python} f"{rms:.3f}"` ``,
but then its results files have to be listed as the stage's `inputs`,
and Calkit can't trace the numbers back to them.

<!-- TODO: needs human review -->

A figure or table from a notebook can go in another document with
Quarto's `embed` shortcode, e.g.,
`{{< embed analysis.ipynb#fig-decay >}}`,
which shows the output saved in the notebook for the cell with that label.
The notebook is an input to the document's stage,
and if another stage renders it with `--execute`,
the document renders after that stage.

See [`examples/quarto`](https://github.com/calkit/calkit/tree/main/examples/quarto)
for a project that does all of these:
a Julia simulation, a Python notebook that fits it,
and an R report that shows values from each and the notebook's figure.

## Figures, tables, and other files from the pipeline

<!-- TODO: needs human review -->

A document can show a figure, table, or other file from anywhere in the
project by its path, as LaTeX's `\ckfigure`, `\cktable`, and `\ckinclude`
do, with a fenced div whose content is its caption,
so citations and cross-references in it work:

```markdown
::: {.ckfigure src="figures/fit.png" #fig-fit width="80%"}
The fit, with its residuals.
:::

As @fig-fit and @tbl-fits show, ...

::: {.cktable src="results/fits.csv" #tbl-fits rows="10"}
Each run's fit.
:::

::: {.ckinclude src="results/summary.md"}
:::
```

<!-- TODO: needs human review -->

A notebook a Quarto stage renders can use them in its Markdown cells too.
Paths are relative to the project, as for `ckvalue`.
`ckfigure` shows an image as a numbered figure,
with Quarto's figure options and classes, e.g., `width`, `fig-pos`, or
`.lightbox`.
`cktable` shows a CSV or TSV file as a numbered table,
up to `rows` rows (25 by default), read from the file as it renders.
`ckinclude` includes a Markdown file's content,
and shows any other file by its path.
Each is an input to the document's stage, whether or not it's shown,
so the document renders after the stages that make them,
and again whenever one changes.

<!-- TODO: needs human review -->

Quarto only runs the extension's filter if the document lists it,
in its front matter or `_quarto.yml`,
and it has to run before Quarto numbers figures and builds callouts:

```yaml
filters:
  - at: pre-ast
    path: calkit
```

`calkit quarto render` fails if it's not listed, saying so,
rather than rendering the divs as plain ones.

## Showing where figures, tables, and values came from

<!-- TODO: needs human review -->

Readers of a rendered document can see where each figure, table, file,
and value came from, and whether it's up to date, without Calkit.
Under each component is a quiet, collapsed "Provenance" line,
which says what's wrong instead when something is, e.g.,
"Out of date: scripts/clean.py modified", "Missing",
or "Incomplete provenance: origin not defined for data/raw.csv",
so it's seen without opening it.
A value reads as normal text, with a dotted underline, and a ⚠ after it
when it's out of date;
selecting it, with a mouse or the keyboard, opens the same view in a
popover, except in a heading, a link, or the document's title, where it's
only text.
This changes how values shown with `ckvalue` and `ckrefval` look in HTML
in documents that already use them.

<!-- TODO: needs human review -->

Opened, the view shows how it came to be:
a graph of the stages it's made from, however far back, and nothing else,
then each of those stages, upstream first, with its kind, environment,
script or command, when and where it last ran if that's recorded,
and the commit it ran after,
every file it reads, with where each came from and whether it changed,
and what it makes on the way.
A file in Git links to it on GitHub or GitLab, at the commit the stage
last ran at, or else the current one, as long as a remote-tracking branch
has it, if the project's `git_repo_url` or `origin` remote is on one,
a file the document shows links to it there,
and a file DVC stores is shown with its hash.
A value quoted from a reference shows what `calkit.yaml` records for it,
e.g., its page, and whether it matched the reference's PDF,
if there's one on the machine that rendered it,
rather than a pipeline.
See [`examples/quarto`](https://github.com/calkit/calkit/tree/main/examples/quarto)
for a notebook and a report that show figures, tables, and values this
way, made from a Julia simulation.

<!-- TODO: needs human review -->

In other formats, e.g., PDF, nothing is shown while it's up to date,
and otherwise one line saying what's wrong;
a value shows only the value.
`provenance=false` turns it off for one component or value,
e.g., `{{< ckvalue results/fit.json slope .2f provenance=false >}}`,
which is still an input to the stage,
and `show_provenance: false` in `calkit.yaml` turns it off for the whole
project.
It's set in `calkit.yaml` rather than a document's front matter,
so it's the same for Quarto and MyST documents,
since MyST warns about front matter it doesn't know.

<!-- TODO: needs human review -->

What each view says is worked out each time the stage renders the
document, from `calkit.yaml`, `.calkit/stage-runs.json`,
and whether each stage is up to date as `calkit status` would say,
and written to `.calkit/local/provenance`,
which isn't kept in Git, for the extension to read,
with the SHA-1 of each file shown and of the document.
The document's own outputs aren't checked,
since it can't say whether what's being rendered is up to date,
and a stage that ran earlier in the same `calkit run` is shown as having
run then, from the run's log, before its run is recorded.
Rendering with Quarto directly, e.g., with `quarto preview` or
`quarto publish`, shows what was recorded the last time Calkit rendered
the document, saying so, while collapsed, if a file it shows or a `.qmd`
document has changed since, e.g.,
"Recorded before data/clean.csv changed",
and a document Calkit hasn't rendered on this machine says nothing is
recorded, still showing its figures and tables.
A view's graph is drawn with Quarto's Mermaid, loaded when the view is
first opened, so a document with everything embedded, e.g., with
`embed-resources`, shows the graph's source instead.
`quarto preview` also doesn't notice when a script or data file changes,
since it only watches the document's own files,
so a view can say a figure is up to date when it isn't anymore
until the document is rendered again.
