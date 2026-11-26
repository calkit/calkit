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

## Showing where figures and tables came from

<!-- TODO: needs human review -->

A reader of a rendered document can see where each figure or table came
from, and whether it's up to date, without Calkit,
by showing it with a `ckprovenance` div rather than an image or a table:

```markdown
::: {.ckprovenance src="figures/fit.png" #fig-fit width="80%"}
The fit, with its residuals.
:::

As @fig-fit shows, ...

::: {.ckprovenance src="results/fits.csv" #tbl-fits rows="10"}
Each run's fit.
:::
```

<!-- TODO: needs human review -->

The file is shown as Quarto would show it, numbered and cross-referenced
by its id, with the div's content as its caption,
and under it a panel saying which stage made it,
in which environment, when and where it last ran,
what it read, and whether it's up to date per `dvc.lock`.
An image is shown as a figure, a CSV or TSV file as a table,
up to `rows` rows (25 by default),
and anything else by its path, unless `kind` says otherwise, i.e.,
`figure`, `table`, or `file`.
Like an image's, `src` is relative to the document,
or to its Quarto project with a leading `/`.
The panel is collapsed when everything is up to date,
and otherwise says what's wrong in its title, e.g.,
an input modified since the stage ran,
an input made by a stage that's out of date itself,
or an input with no recorded origin, which leaves the figure with
incomplete provenance.
A file no stage makes says where it came from if `calkit.yaml` records it,
e.g., with `imported_from`.

<!-- TODO: needs human review -->

A div with no `src` shows a panel about the document itself:
each pipeline output it's made from, however far back,
whether each is up to date,
and a graph of the stages that make them,
drawn with Quarto's Mermaid in HTML and shown as source in other formats.
`table="false"` or `graph="false"` leaves either out.
The document's own outputs aren't checked,
since it can't say whether what's being rendered is up to date;
`calkit status` checks them.

```markdown
::: {.ckprovenance}
:::
```

<!-- TODO: needs human review -->

Quarto only runs the extension's filter if the document lists it,
in its front matter or `_quarto.yml`,
and it has to run before Quarto numbers figures and builds callouts:

```yaml
filters:
  - at: pre-ast
    path: calkit
```

`calkit quarto render` fails if it's not listed,
saying so, rather than rendering the divs as plain ones.

<!-- TODO: needs human review -->

What each panel says is worked out from `calkit.yaml`, `dvc.lock`, and
`.calkit/stage-runs.json` each time the stage renders the document,
and written to `.calkit/local/provenance`,
which isn't kept in Git, for the extension to read.
Rendering with Quarto directly, e.g., with `quarto preview`,
shows the panels as of the last time Calkit rendered the document,
and a document Calkit hasn't rendered on this machine says no provenance
is recorded.
`quarto preview` also doesn't notice when a script or data file changes,
since it only watches the document's own files,
so a panel can say a figure is up to date when it isn't anymore
until the document is rendered again.
The files the divs show are inputs to the document's stage,
so it renders after the stages that make them.
