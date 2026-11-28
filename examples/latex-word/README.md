# LaTeX and Word review example

A small paper, split across `paper/main.tex` and
`paper/methods.tex`, for trying the Word review workflow described in
[the tutorial](https://docs.calkit.org/tutorials/latex-word/).
It has a figure, a table, display and inline math, citations, and one
comment thread already in the source, so every case the round trip has to
handle is in here.

Build the PDF, then export a Word copy:

```sh
calkit run
calkit doc to-docx paper/main.pdf
```

Open `paper/main-for-review.docx` in Word, make some edits and leave some
comments, then accept or reject what you like and save it somewhere like
`reviews/`.
Merge it back:

```sh
calkit doc merge-docx reviews/main-for-review.docx
```

Check `git diff` to see what landed in the source, then rebuild and export
again (with `--force` to replace the old copy) for another round.
Records of each export and merge are written under `.calkit/latex/`.

<!-- TODO: needs human review -->

## Starting a project from this example

```sh
calkit new project my-project --from calkit/calkit/examples/latex-word
```
