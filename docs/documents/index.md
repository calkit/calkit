# Documents and presentations

<!-- TODO: needs human review -->

Calkit builds papers, reports, and slides as pipeline stages,
so they stay current with the results they show.
The pages in this section cover each tool:
[LaTeX](../latex.md), with [Overleaf](../overleaf.md) and a
[round trip through Word](../tutorials/latex-word.md),
[Quarto](../quarto.md),
and [Office](../tutorials/office.md).
This page covers what they share, and where they differ.

## Citing project components

<!-- TODO: needs human review -->

LaTeX, Quarto, and Markdown documents cite values from results files by
their path in the project with the same `ckvalue` vocabulary:
`\ckvalue` in [LaTeX](../latex.md#including-project-components),
the `ckvalue` shortcode in [Quarto](../quarto.md#values-from-the-pipeline),
and value markers in [Markdown](../pipeline/markdown.md#values),
with `ckrefval` for values quoted from references.
LaTeX also includes figures, tables, and other LaTeX by path with
`\ckfigure`, `\cktable`, and `\ckinclude`.

## Dependencies

<!-- TODO: needs human review -->

A LaTeX or Quarto document's stage depends on what it cites,
found by reading it,
so `calkit run` builds it after the stages that produce those,
and again whenever one changes.
A Word document's stage depends on the document and the inputs declared
for it.

## Environments

<!-- TODO: needs human review -->

LaTeX and Quarto documents build in the project's
[environments](../environments.md),
e.g., a TeX Live environment, or one providing Quarto,
so every machine builds them the same way.
Word documents are converted with Word on this machine.
PowerPoint decks are exported with LibreOffice or PowerPoint,
from this machine by default, or LibreOffice in a Docker environment.

## Checks

<!-- TODO: needs human review -->

`calkit check references` checks that the
[references](../references.md) a document cites are real,
and `calkit check repro -c numbers` lists numbers typed into a document
that look like results but have nothing recorded behind them.

## The `calkit doc` commands

<!-- TODO: needs human review -->

`calkit doc` picks the tool from the document's path and runs that tool's
command, passing it the options after the path:

```sh
calkit doc build paper/main.tex
calkit doc diff paper/main.tex --from main
calkit doc to-docx paper/main.tex
calkit doc merge-docx paper/main-for-review.docx
```

`calkit doc build` builds a LaTeX document, Word document, or PowerPoint
deck as a PDF, and renders a Quarto document or notebook to the format
its metadata names.
A document a pipeline stage builds is built as that stage does,
in its environment and with its options,
and a Quarto project folder, e.g., `calkit doc build .`,
builds the documents its stages render.
The other commands work with LaTeX for now.
Tool-specific commands live under `calkit doc latex` and `calkit doc quarto`
(see the [CLI reference](../cli-reference.md) for their options).

<!-- TODO: needs human review -->

To send a built document to someone along with what made it,
bundle a [kit](../kits.md) into a copy of its PDF or HTML,
e.g., `calkit kit bundle paper/main.pdf`.
