# LaTeX documents

Calkit builds LaTeX documents with `latexmk`, in whichever
[environment](environments.md) the project defines:

```sh
calkit latex build paper/main.tex --env tex
```

Without `--env`, `latexmk` runs directly if it's installed, and in a TeX Live
container if it isn't.

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
        - [submitted-v1, revision-1] # what the referees were sent
```

`calkit run` builds each one alongside the document.
They're stage outputs, so they're tracked, pushed, and pulled with the rest
of the project, and the
[browser extension](browser-extension.md) can show them on the pull request
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

### For journal referees

A revision round is a comparison between two tags, so name both:

```yaml
diffs:
  - [submitted-v1, revision-1]
```

Neither end can move, so it's built once and then left alone.
That matters for a file you've already sent someone: LaTeX writes a
timestamp into every PDF, so rebuilding from identical sources would produce
a different file.

Before sending back for the next round of reviews,
create a [release](releases.md) for the document with a name like `v2`,
with its diff as part of the release.
A release stores a frozen copy named `{project}-{document}-{release}.pdf`,
which is what you want on a file about to be emailed to an editor.
For a DVC-tracked file that copy is a pointer to content already stored, so
keeping it costs nothing.

### Where they go

Each comparison gets a directory named after what it compares, with the
document's own path inside it:

| Diff                 | File                                                         |
| -------------------- | ------------------------------------------------------------ |
| `main`               | `.calkit/latex-diffs/main/pubs/paper-1/main.pdf`             |
| `[submitted-v1, v2]` | `.calkit/latex-diffs/submitted-v1..v2/pubs/paper-1/main.pdf` |

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
