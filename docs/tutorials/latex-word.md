# Collaborating on a LaTeX document using Microsoft Word for feedback

<!-- prettier-ignore -->
!!! tip
    If you want to try Calkit without [installing](../installation.md),
    you can use it directly from [`uv`](https://docs.astral.sh/uv/) with
    (use in place of `calkit` in any command below):

    ```sh
    uvx ck9
    ```

Teams have a variety of tolerance for markup languages and complex
system setup.
Thus, despite its limitations for technical writing,
Microsoft Word remains an important tool.
In some projects, the lead may want to use LaTeX or some other
text-first typesetting system like Typst or Quarto since those
play more nicely with version control systems like
Git and make it easier
to ensure document components like figures, tables, and values remain
up-to-date with the analysis,
but others on the team may not want to engage in that way.
They prefer a WYSIWYG experience, and many would prefer to not need to
sign up for a web app like Overleaf.
They simply find it most intuitive to email Word documents.

[Pandoc](https://pandoc.org)
provides one solution to this problem since it can convert .tex to .docx.
However, Pandoc produces
a Word document that doesn't look like the compiled LaTeX unless a custom
template is provided,
and migrating the contributions back into LaTeX is a manual process.
Calkit, on the other hand, uses Word's built in PDF converter and inserts
special bookmarks into the .docx file to enable merging changes and comments
back into the original .tex source idempotently,
allowing teams to work in both systems without painful manual merges.

<!-- prettier-ignore -->
!!! note
    Exporting and reviewing require Microsoft Word, on macOS or Windows.
    However, merging changes back into LaTeX does not.

## Exporting the document for review

Assuming we have an up-to-date compiled LaTeX document in our project at
`paper/main.pdf`,
we can export a Word copy for review with:

```sh
calkit latex to-docx paper/main.pdf
```

Calkit needs the LaTeX source as well as the PDF,
since again, we are treating that as the source of truth.
The `to-docx` command assumes the `.tex` source is alongside the PDF, i.e.,
`paper/main.tex`.
If that's not correct, it can be passed in with the `--source` option.
If the PDF is built as part of a `latex` stage in the Calkit pipeline,
the source (`target_path`) will be looked up there,
and Calkit will run the stage before export if necessary.
If the document is not part of the pipeline, it's up to you to ensure
the compiled PDF is up-to-date.

By default, the Word document is written next to the PDF, e.g.,
`paper/main-for-review.docx`, but this can be controlled with the `-o` flag.
It will look very similar to the PDF, except that
equations are pictures, which reviewers can comment on but not edit,
and tables are tab-separated text rather than native Word tables.

By default the Word document has "track changes" enabled,
and if you export with `--comment-only`
the document cannot be edited.

After export, you can email to your collaborators, put on a shared drive,
etc.

## Reacting and responding to the feedback

When you get a reviewed copy back, open it up in Word, reply to or
resolve comments, accept or reject proposed changes,
and optionally make new edits of your own.
Note that your own edits are tracked too,
so be sure to accept them before merging.

## Merging back into the project

When you're done in Word, merge it back into LaTeX with:

```sh
calkit latex merge-docx reviews/main-for-review-pi-comments.docx
```

This command assumes we've saved the .docx we got back into a
`reviews` folder inside the project,
which is just a convention; the file can be anywhere as it retains
information about the LaTeX source from which it came.

<!-- prettier-ignore -->
!!! note
    It's probably a good idea to save copies of the returned .docx files
    to the project repo for posterity. You can do this with:

    ```sh
    calkit save reviews/main-for-review-pi-comments.docx -m "Add review"
    ```

Changes you accepted in Word are applied to the LaTeX source.
Tracked changes you haven't accepted or rejected yet are left alone
with a warning,
as is an edit that no longer fits because the paragraph has changed
since the copy was sent,
e.g., when two reviewers changed the same sentence.
Go back into Word, deal with them, and run `merge-docx` again.

Comments are written into the source as LaTeX comments,
just above the paragraph they were left on, e.g.:

```latex
% COMMENT highlight={text: "this is optional highlighted text"}
%   A. Reviewer:
%     Quantify this: give an RMS error. If this goes over 80 characters it will
%     indent.
%   Someone Else:
%     Will add RMS error to Table 2.
%   Another Person:
%     I agree!
The model in Eq.~\eqref{eq:wake} fits the data in Sec.~\ref{sec:methods}
reasonably well.
```

A thread resolved in Word merges back into LaTeX with a `resolved=true`
annotation on the `COMMENT` line.
It's possible to disable comments merging back into LaTeX with `--no-comments`.

Note that merging is idempotent, meaning it can be called again
and content won't be duplicated.

## Merging on the Calkit Hub instead

If the project is on the Calkit Hub, the round trip doesn't need a
laptop with Word on it at the merging end.
Open the publication, and in the **Word reviews** panel upload the
document that came back.
It's saved to the project under `reviews/`, tracked with DVC and
committed, so the review is part of the project's record just as it
would be with `calkit save`.

The hub then shows everything the reviewer did, one item at a time:
each changed paragraph as a word-level diff, and each comment thread.
Tracked changes the reviewer left pending can be accepted or rejected
right there, without opening Word,
and comments can be written to the source or dismissed.
**Merge** writes the decisions to the LaTeX source in one commit.
Rejected edits and dismissed comments are remembered, so they aren't
offered again, and anything left undecided stays open for a later pass.

It's the same merge as `calkit latex merge-docx`, reading the same
document and writing the same record under `.calkit/latex/`,
so a review can be started on the hub and finished on a laptop or the
other way round.

## Multiple reviewers

It's okay to send the same copy out to multiple collaborators.
Follow the same process, checking their markup in Word,
then merging in with `calkit latex merge-docx`.

## Multiple rounds

For the next round of review, use the `to-docx` command on the LaTeX PDF
again.
Comments left in the `.tex` that follow the format above will be exported
to .docx.
It's probably a good idea to move the old review copies and keep track
of who you sent them to, how, and when.

## Example

For an example project that uses this approach,
see [here](https://github.com/calkit/calkit/tree/main/examples/latex-word).

You can use it as a starting point for your own project with:

```sh
calkit new project --from https://github.com/calkit/calkit/examples/latex-word \
    my-project-name
```
