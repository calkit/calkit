# Overleaf integration

[Overleaf](https://overleaf.com) is a cloud-based web application designed for
collaborating on LaTeX documents.
It helps lower the barrier to entry as users don't need to
get their local machine
or a [GitHub Codespace](tutorials/latex-codespaces.md)
set up with Git, Docker, LaTeX, etc.

One downside to using Overleaf is that it is intended only for writing,
not general computing, e.g., data processing or figure generation,
so it encourages treating writing as a separate phase or project.
Any figures or tables created from automated scripts
typically need to be manually uploaded to update the Overleaf document,
which introduces complexity and a potential source of
non-reproducibility, e.g.,
if this manual figure copying process is mistakenly omitted.
It also makes it difficult to work offline.

With Calkit it's possible to link an Overleaf project to a publication
so you can use Overleaf for collaborating on the writing,
without losing the ability to work more holistically on the project.
Calkit can sync bidirectionally with Overleaf,
ensuring edits propagate both directions,
so users who prefer to work locally can do so.
Calkit can also ensure files like figures are always sent from
the local project (where they are generated) up to Overleaf,
so the PDF output looks the same in either system.

## Generating and storing an Overleaf token

In order for Calkit to interact with Overleaf,
you'll need to set a token in the config.
To do this,
visit the
[Overleaf user settings page](https://www.overleaf.com/user/settings)
and scroll down to the
"Your Git authentication tokens" section.
Generate a token, copy it, and then set it in your Calkit config with:

```sh
calkit config set overleaf_token {paste your token here}
```

## Importing an Overleaf project

To import an Overleaf project as a Calkit publication,
use the `calkit import overleaf` command.
For example:

```sh
calkit overleaf import \
    https://www.overleaf.com/project/68000059d42b134573cb2e35 \
    paper \
    --title "My paper title" \
    --kind journal-article \
    --sync-path paper.tex \
    --push-path figures
```

If necessary, this will create a TeXlive Docker [environment](environments.md)
and a build stage in the [pipeline](pipeline/index.md),
which will build and cache the PDF upon calling `calkit run`.

## Syncing an Overleaf project

To sync a publication linked to an Overleaf project, simply call:

```sh
calkit overleaf sync
```

After syncing, you'll probably want to ensure the local PDF is up-to-date
by calling `calkit run`, and if anything has changed,
commit and push those changes to the cloud with
`calkit save -am "Run pipeline"`.

## Example

You can view an example project that uses Overleaf integration on
[GitHub](https://github.com/calkit/example-overleaf)
and the [Calkit Cloud](https://calkit.io/calkit/example-overleaf).
This project syncs the document text bidirectionally,
and pushes figures up to Overleaf.
