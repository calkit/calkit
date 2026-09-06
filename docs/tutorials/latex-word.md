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

However, converting from LaTeX to Word with something like
[Pandoc](https://pandoc.org)
produces
a Word document that doesn't look like the final output,
and migrating the contributions back into LaTeX is a manual process.
For these situations, Calkit supports a workflow where the source of
truth is LaTeX, but Word documents can be sent out for review,
and the project lead can merge the comments and edits from the `.docx` files
back into the TeX source.

<!-- prettier-ignore -->
!!! note
    Exporting and reviewing require Microsoft Word, on macOS or Windows,
    However, merging changed back into LaTeX does not.

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
It that's not correct, it can be passed in with the `--source` option.
If the PDF if built as part of a `latex` stage in the Calkit pipeline,
the source (`target_path`) will be looked up there.
If the document is not part of the pipeline, it's up to you so ensure
the compiled PDF is up-to-date.
Otherwise, Calkit will run the stage before export if necessary.

By default, the Word document is written next to the PDF, e.g.,
`paper/main-for-review.docx`, but this can be controlled with the `-o` flag.
It will look very similar to the PDF, except that
equations are pictures, which they can comment on but not edit,
and tables are tab-separated text rather than native Word tables.

By default the Word document has "track changes" enabled,
and if you export with `--comment-only`
the document cannot be edited.

After export, you can email to your collaborators, put on a shared drive,
etc.

## Reacting and responding to the feedback

It's possible to deal with a review copy either in Word or from the CLI.
If using Word, you can simply accept/reject changes, reply to comments, etc.
Anything unresolved in Word will cause the CLI to prompt the user at
merge time.

## Merging back into the project

When you're done in Word, merge it back into LaTeX with:

```sh
calkit latex merge-docx reviews/main-for-review-PI-comments.docx
```

This command assumes we've saved the `.docx` we got back into a
`reviews` folder inside the project,
which is just a convention; the file can be anywhere as it retains
information about the LaTeX source from which it came.
It may be a good idea to keep the `.docx` around for posterity.
You can save to DVC
(better for tracking binary files,
but Git can be okay if the file isn't large from many embedded figures)
with:

```sh
calkit save reviews/main-for-review-PI-comments.docx --to dvc -m "Add review"
```

Changes you accepted in Word are applied to the LaTeX source.
Remaining tracked changes that were not rejected will throw a warning.

Comments are written into the source as LaTeX comments,
just above the paragraph they were left on, e.g.:

```latex
% COMMENT author="A. Reviewer"
% Quantify this: give an RMS error.
%   REPLY author="T. Author"
%   Will add RMS error to Table 2.
The model in Eq.~\eqref{eq:wake} fits the data in Sec.~\ref{sec:methods}
reasonably well.
```

It's possible to disable comments merging back into LaTeX with `--no-comments`.

Note that merging is idempotent, meaning it can be called over again
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
