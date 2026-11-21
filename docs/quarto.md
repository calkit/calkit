# Quarto documents

<!-- TODO: needs human review -->

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

## Where Quarto comes from

Quarto is part of the environment, like any other tool a stage runs,
so a document renders with the same version on every machine:
add `quarto` to a Conda or Pixi environment,
or `quarto-cli` to a uv or pip one.
The stage renders with `calkit quarto render`,
which checks that the environment provides it,
and fails rather than quietly using whatever version is installed on the
machine.
Run by hand, it's given the environment every time,
e.g., `calkit quarto render -e main index.qmd`.
`calkit check app quarto -e <environment>` makes the same check on its own,
for Quarto or any other app.
A stage in the `_system` environment uses the one installed on the
machine.
To use one installed outside another environment on purpose,
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

A document can show values from a results file a stage writes,
with the `ckvalue` shortcode,
which reads like its [Markdown](pipeline/markdown.md#values) and
[LaTeX](latex.md#including-project-components) counterparts:
a results file, or the name of a declared result, a key, and optionally a
Python format spec, positionally or by name.

```markdown
---
shortcodes:
  - _calkit/calkit.lua
---

The RMS is {{< ckvalue results/metrics.json rms .3f >}}
over {{< ckvalue results/metrics.json key=fit.n >}} samples.
```

Paths are relative to the project.
Results files can be JSON, YAML, or TOML,
and keys are separated by dots to reach into nested values.

Calkit writes the shortcode to `_calkit/calkit.lua` beside the document
when the pipeline is compiled,
and the values the document shows to `_calkit/values/` each time the stage
runs, which Quarto skips when rendering a project, since they start with an
underscore.
Both are kept in Git,
so the document renders the same without Calkit, e.g., when a site is
published by `quarto publish` or a CI workflow.
The results files are inputs to the stage,
so a change to a value renders the document again.
