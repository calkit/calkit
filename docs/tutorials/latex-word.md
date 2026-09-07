# Collaborating on a LaTeX document using Microsoft Word for feedback

Teams have a variety of tolerance for markup languages and complex
system setup.
Thus, despite its limitations for technical writing,
Microsoft Word remains an important tool.
In some projects, the lead may want to use LaTeX or some other
text-first typesetting system like Quarto since those make it easier
to ensure document components like figures, tables, and values remain
up-to-date with the analysis,
but others on the team may not want to engage in that way.
They prefer a WYSIWYG experience without needing to sign up for a web
app like Overleaf (or Calkit for that matter).

Though it is an awesome tool,
converting from LaTeX to Word with something like
[Pandoc](https://pandoc.org)
produces
a Word document that doesn't look like the compiled LaTeX,
and migrating the contributions back into LaTeX is a manual process.
For these situations, Calkit supports a workflow where the source of
truth is LaTeX, but Word documents can be sent out for review,
and the project lead can merge the comments and edits from the `.docx` files
back into the TeX source.

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

This command assumes we've saved the `.docx` we got back into a
`reviews` folder inside the project,
which is just a convention; the file can be anywhere as it retains
information about the LaTeX source from which it came.

<!-- prettier-ignore -->
!!! note
    It's probably a good idea to save copies of the returned `.docx` files
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

## Multiple reviewers

It's okay to send the same copy out to multiple collaborators.
Follow the same process, checking their markup in Word,
then merging in with `calkit latex merge-docx`.

## Multiple rounds

For the next round of review, use the `to-docx` command on the LaTeX PDF
again.
Comments left in the `.tex` that follow the format above will be exported
to `.docx`.
It's probably a good idea to move the old review copies and keep track
of who you sent them to, how, and when.

## Example

For an example project that uses this approach,
see [here](https://github.com/calkit/calkit/tree/main/examples/latex-word).
