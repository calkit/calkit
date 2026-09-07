# LaTeX documents

Calkit builds LaTeX documents with `latexmk`, in whichever
[environment](environments.md) the project defines:

```sh
calkit latex build paper/main.tex --env tex
```

Without `--env`, `latexmk` runs directly if it's installed, and in a TeX Live
container if it isn't.

## Adding a document to the pipeline

A one-off build isn't reproducible on its own.
Add the document to the [pipeline](pipeline/index.md) as a `latex` stage, and
`calkit run` rebuilds it whenever the source or any of its inputs change,
and skips it when nothing has:

```sh
calkit new latex-stage --name paper --target paper/paper.tex --environment tex
```

which writes into `calkit.yaml`:

```yaml
pipeline:
  stages:
    paper:
      kind: latex
      environment: tex
      target_path: paper/paper.tex
```

The compiled PDF is an output of the stage without being declared, so there's
nothing to add for it.
Use `--output` only for the extras a build produces, and see the
[pipeline docs](pipeline/index.md) for the attributes every stage shares.

To start a document from scratch instead, `calkit new publication` writes the
source files, the environment, and the stage in one go:

```sh
calkit new publication paper --template latex/jfm --stage paper \
    --environment tex --kind journal-article --title "A cool paper"
```

Available templates are `latex/article` (generic), `latex/ieee-conference`
(IEEEtran), `latex/jfm` (Journal of Fluid Mechanics), and `latex/report`
(chapters, for a thesis or technical report). Each uses packages that ship
with TeX Live, so the `texlive/texlive:latest-full` Docker environment
builds all of them.

## Inputs

A document's class, style, bibliography, and figure files are inputs to
building it, but LaTeX resolves those itself, so the pipeline can't see them
unless the stage declares them.
`calkit new latex-stage` and `calkit new publication` read the document and
add the ones that live in the project, following `\input`, `\include`, and
any class or style file that loads others.
Anything that comes from TeX Live is left alone, since it isn't the project's
to track, and anything an already-declared directory covers is left off
rather than listed again underneath it.
Pass `--no-detect-inputs` to turn this off, and `--input` to add more.
`calkit xr` detects the same inputs when the command it wraps builds a
document.

In the web app, clicking a stage in the pipeline diagram opens it for
editing, with a button to re-run this detection against the current source.

Undeclared inputs mean editing the class file doesn't rebuild the paper, and
the web app's in-browser editor, which loads exactly what the stage declares,
can't compile the document at all.

## Comparing revisions

A rebuilt PDF is a DVC-tracked artifact, so a pull request shows its pointer
file changing and nothing about the document itself.
Calkit can mark up one revision of a document against another with
`latexdiff`, so additions and deletions appear where they happen.

List the comparisons a document should keep in its `latex` stage:

```yaml
pipeline:
  stages:
    paper-1:
      kind: latex
      environment: tex
      target_path: pubs/paper-1/main.tex
      diffs:
        - main # what this branch changes, for reviewers of the PR
        - [paper-1-submitted, paper-1-v2] # what the referees were sent
```

`calkit run` builds each one alongside the document.
They're stage outputs, so they're tracked, pushed, and pulled with the rest
of the project, and the
[browser extension](browser-ext/index.md) can show them on the pull request
they belong to.

`latexdiff` ships with TeX Live, so an environment that can build the
document can usually diff it too.

### For pull request reviewers

A bare revision compares it against `HEAD`, so `- main` means "what this
branch has committed, against the branch it will merge into".
That's the diff a PR reviewer wants, and it's rebuilt whenever either end
moves.

On the default branch, `main` and `HEAD` are the same commit, so the
comparison comes out empty and the marked-up document is simply the
document.
That's a result rather than an error: a stage shouldn't fail depending on
which branch it runs from.

It does mean the tracked diff keeps showing a merged branch's changes until
the pipeline runs on the default branch again, which rebuilds it as the
plain document.
Running the pipeline in CI on pushes to the default branch keeps it current;
the [run action](https://github.com/calkit/calkit/tree/main/actions/run) does that
in its example workflow, and saves the result.

<!-- prettier-ignore -->
!!! note

    Comparing revisions needs those revisions in the clone, and
    `actions/checkout` fetches a single commit by default, which leaves
    `calkit run` reporting `Git ref 'main' was not found`.
    Set `fetch-depth: 0` on the checkout step for a project that builds
    diffs.

### For journal referees

A revision round is a comparison between two tags, so name both:

```yaml
diffs:
  - [paper-1-submitted, paper-1-v2]
```

Neither end can move, so it's built once and then left alone.
That matters for a file you've already sent someone: LaTeX writes a
timestamp into every PDF, so rebuilding from identical sources would produce
a different file.

Before sending the paper back for the next round of reviews, create a
[release](releases.md) for the document:

```sh
calkit new release pubs/paper-1/main.pdf --name paper-1-v2
```

A release name becomes a Git tag, and tags belong to the whole repo, so name
them after the document as well as the round.
A project with two papers in it can't have both call their second round
`v2`.

A release stores a frozen copy named `{project}-{document}-{release}.pdf`,
which is what you want on a file about to be emailed to an editor.
For a DVC-tracked file that copy is a pointer to content already stored, so
keeping it costs nothing.

A release covers one path, so archiving the diff means a second release
naming its directory.
The tag pins both either way, since the diff is tracked with the project
like any other output.
Bundling everything a publication needs into a single release is
[issue #1026](https://github.com/calkit/calkit/issues/1026).

### Where they go

Each comparison gets a directory named after what it compares, with the
document's own path inside it:

| Diff                              | File                                                                      |
| --------------------------------- | ------------------------------------------------------------------------- |
| `main`                            | `.calkit/latex-diffs/main/pubs/paper-1/main.pdf`                          |
| `[paper-1-submitted, paper-1-v2]` | `.calkit/latex-diffs/paper-1-submitted..paper-1-v2/pubs/paper-1/main.pdf` |

`diff_pdf_storage` on the stage chooses between DVC and Git for them, like
`pdf_storage` does for the document itself.

### Comparing against uncommitted work

`calkit latex diff` runs a comparison on demand, and with no `--to` the
newer side is the working tree:

```sh
calkit latex diff pubs/paper-1/main.tex --from main --env tex
# .calkit/local/latex-diffs/main..working/pubs/paper-1/main.pdf
```

That one can't be reproduced from two revisions, so it isn't tracked: it
goes under `.calkit/local`, which is private to the machine.
With no `--from` it compares against the merge base with the default branch.

## Interoperability with Microsoft Word

For projects to be as inclusive as possible towards collaborators who
prefer Microsoft Word, Calkit has the ability to export Word documents
from LaTeX using Word's PDF converter to make them look as faithful as
possible using the `calkit latex to-docx` command.
After they've been marked up and commented on,
those contributions can be merged back into the .tex source,
including comments,
with `calkit latex merge-docx`.

See [this tutorial](tutorials/latex-word.md) for more.

## Comments

The Calkit LaTeX comment schema is designed to be portable and interoperable,
easy to read as plain text but simple enough to be written by and interacted
with graphically in any application.

A comment thread is delineated with a LaTeX comment starting with `COMMENT`
and the thread persists until the next non-commented line.
The first line contains metadata about the comment such as
whether or not it's resolved and if it's referring to a highlighted region
of text in the following block.
Each comment has an author name and optional email and timestamp.
Indentation is used to denote where each message starts and ends, and the
comment thread initiation metadata can span multiple lines if needed.
For example:

```latex
% COMMENT resolved=false highlight={text: "something", occ: 0}
%   Someone Name <email@mail.com> (2025-01-01 01:00):
%     This is a comment.
%   Person, Other:
%     That's a very good comment.
```
