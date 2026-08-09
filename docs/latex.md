# LaTeX documents

Calkit builds LaTeX documents with `latexmk`, in whichever
[environment](environments.md) the project defines:

```sh
calkit latex build paper/main.tex --env tex
```

Without `--env`, `latexmk` runs directly if it's installed, and in a TeX Live
container if it isn't.

## Seeing what a change did

A rebuilt PDF is a DVC-tracked artifact, so a pull request shows its pointer
file changing and nothing about the document itself.
`calkit latex diff` marks up the current document against an earlier revision
with `latexdiff`, so additions and deletions appear where they happen:

```sh
calkit latex diff paper/main.tex --env tex
```

By default this compares against the merge base with the default branch,
which is what a reviewer of the branch would see.
Work that landed on the default branch after the branch started isn't part
of the change, so comparing against the branch tip instead would show it as
deletions.
Pass `--from` to compare against any other ref.

The marked-up document is built in the working tree, so it uses the current
figures and bibliography: what's marked is what changed in the text.
Multi-file documents are handled, since `latexdiff` inlines `\input` and
`\include` on both sides before comparing.
The result is written to `.calkit/latex-diff/<document>/<ref>.pdf`, beside
the project's other derived files rather than next to the document,
following the same convention as executed notebooks.
It's named after what it's a diff against, so a document can keep several of
them:

```sh
calkit latex diff paper/main.tex --from submitted-v1
# .calkit/latex-diff/paper/main/submitted-v1.pdf
```

Retaining the diff for each round of journal revisions is the case this is
meant for.
A PDF is tracked with DVC when the project is saved, so these are versioned
and pushed with everything else rather than living somewhere with no tie
back to the project.
Pass `--output` to put one somewhere else.

`latexdiff` ships with TeX Live, so an environment that can build the
document can usually diff it too.

<!-- prettier-ignore -->
!!! note

    Nothing produces these automatically.
    A diff against a *moving* ref, like the default branch, doesn't belong in
    the pipeline: its result changes whenever that branch moves, and since DVC
    hashes files rather than Git history, `calkit run` has no way to know it
    went stale.
    A diff against a tag is a different matter -- its base can't move, so it
    is a function of the files -- which is what makes retained revision-round
    diffs worth keeping.

Once saved and pushed, the diff is an artifact like any other, so the
[browser extension](browser-extension.md) can show it alongside the
document it describes.

## Creating diffs in the pipeline

In a `latex` stage, you can list off the diffs you'd like generated like:

```yaml
pipeline:
  stages:
    paper-1:
      kind: latex
      environment: tex
      target_path: pubs/paper-1/main.tex
      diffs:
        - [v1, v2] # Ensure a frozen diff of v1 vs v2 is cached in the project
        - [main, _merge_branch]
      diff_pdf_storage: dvc # Default is DVC
```
