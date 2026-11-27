# Documents and presentations

<!-- TODO: needs human review -->

Calkit builds papers, reports, and slides as pipeline stages,
so they stay current with the results they show.
The pages in this section cover each tool:
[LaTeX](../latex.md), with [Overleaf](../overleaf.md) and a
[round trip through Word](../tutorials/latex-word.md),
[Quarto](../quarto.md),
and [Office](../tutorials/office.md).
This page covers what they share.

## Citing project components

<!-- TODO: needs human review -->

Each format cites figures, tables, and values by their path in the project
with the same `ck*` vocabulary, e.g., `\ckvalue` in
[LaTeX](../latex.md#including-project-components),
the `ckvalue` shortcode in [Quarto](../quarto.md#values-from-the-pipeline),
and value markers in [Markdown](../pipeline/markdown.md#values).

## Dependencies

<!-- TODO: needs human review -->

A document's stage depends on what it cites, found by reading it,
so `calkit run` builds it after the stages that produce those,
and again whenever one changes.

## Environments

<!-- TODO: needs human review -->

Documents build in the project's [environments](../environments.md),
e.g., a TeX Live environment for LaTeX, or one providing Quarto,
so every machine builds them the same way.

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
calkit doc build paper/main.tex -e tex
calkit doc diff paper/main.tex --from main
calkit doc to-docx paper/main.tex
calkit doc merge-docx paper/main-for-review.docx
```

`calkit doc build` builds LaTeX, Quarto documents and notebooks,
Word documents, and PowerPoint decks, as a PDF.
The others work with LaTeX for now.
See the [CLI reference](../cli-reference.md) for each tool's own commands,
e.g., `calkit latex build`, and their options.
