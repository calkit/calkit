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

However, converting from LaTeX to Word with something like Pandoc produces
a Word document that doesn't look like the final output,
and migrating the contributions back into LaTeX is a tedious manual process.
For these situations, Calkit supports a workflow where the source of
truth is LaTeX, but Word documents can be sent out for review,
and the project lead can merge the comments and edits from the `.docx` files
back into the TeX source, and back out to `.docx` again.

<!-- prettier-ignore -->
!!! note
    This workflow requires Microsoft Word on all collaborators' machines,
    even the project lead who primarily writes in LaTeX.

## Exporting the document for review

Assuming we have an up-to-date compiled LaTeX document in our project at
`paper/main.pdf`,
we can export a Word copy of it with:

```sh
calkit latex to-docx paper/main.pdf -o paper/main-for-review.docx
```

This command assumes the `.tex` source is alongside the PDF, i.e.,
`paper/main.tex`.
It that's not correct, it can be passed in with the `--source` option.

Note that this will be more reliable if it's produced as a `latex` stage
in the Calkit pipeline, but it's not an absolute requirement.
It's also useful if the `.tex` source is committed to Git, since the `.docx`
will get commit information for its corresponding rev.

By default the Word document has tracked changes forced to be enabled,
so nobody has to remember to turn them on,
and the reviewer's edits and comments both come back in the same file.
With `--permission comment` the document is locked to comments only,
for the reviewer you want opinions from but not rewrites.

You can then email the file to your reviewers.
The same file can go to the whole team,
since Word stamps every change and comment with the name of the person
who made it.
Nothing about their side of the process involves Calkit.

## Responding to the review in Word

When a marked-up document comes back,
the natural place to go through it is Word itself.
Accept the changes you want and reject the rest,
reply to comments or resolve them,
and make your own edits.
Word is where the reviewer's reasoning is easiest to see,
and nothing you do there needs to be repeated later.

## Merging back into the project

When you're done in Word, merge it back into LaTeX with:

```sh
calkit latex merge-docx reviews/main-for-review-PI-comments.docx
```

This command assumes we've saved the `.docx` we got back to a `reviews`
folder inside the project.
It may be a good idea to keep the `.docx` around for posterity.
You can save to DVC
(better for tracking binary files,
but Git can be okay if the file isn't large from many embedded figures)
with:

```sh
calkit save reviews/main-for-review-PI-comments.docx --to dvc -m "Add review"
```

Calkit reads the commit from the document,
compares the document as it is now with the copy of the text it
carried when it was sent,
and finds everything that differs.
Each difference is anchored to a source line at that commit,
then carried forward to your current source the way a patch is:
by line number first, and by matching text when the file has moved on.

Changes you accepted in Word are already decided,
so they're applied to the LaTeX source without asking.
Only what's still undecided prompts:
tracked changes you left neither accepted nor rejected,
and edits Calkit can't place on its own:

```
[1/3] paper/methods.tex:31 (A. Reviewer, still tracked)
  - We measured the velocity field with a two-component laser Doppler
  - velocimeter~\citep{lee2018}. The sampling frequency was $f_s = 1$~kHz
  - and the integral time scale was estimated from the autocorrelation.
  + We measured the velocity field with a two-component laser Doppler
  + velocimeter~\citep{lee2018}.
  Apply, skip, or edit? [a/s/e]
```

Pass `--accept-remaining` or `--reject-remaining` to settle those
without being asked,
which makes the merge non-interactive if you decided everything in
Word.

Comments are written into the source as LaTeX comments,
just above the paragraph they were left on,
with any replies in order,
in the form described under [comments](#comments) below:

```latex
% COMMENT author=a.reviewer@uni.edu
% Quantify this: give an RMS error.
%%%% REPLY author=pete@x.edu
%%%% Will add RMS error to Table 2.
The model in Eq.~\eqref{eq:wake} fits the data in Sec.~\ref{sec:methods}
reasonably well.
```

The objective is to make it readable in TeX.
These comments will make their way out into the docx,
and docx comments will make their way back into TeX.
Deleting a thread signals that it's resolved.

Some edits can't be applied mechanically,
e.g., a change inside an equation, a citation, or a table,
since the reviewer was editing rendered text rather than the LaTeX that
produced it.
Those are shown with the reviewer's version alongside the source line,
and you can apply them by hand with `e` or skip them.

Attribution comes from the document.
Each comment keeps the name Word recorded for its author,
and tracked changes keep theirs while they're still tracked.
Accepting a change in Word removes its author,
which is fine, since by then it's your decision.
If a document's author names are unhelpful,
e.g., the reviewer's copy of Word is signed in as "User",
pass `--reviewer "A. Reviewer"` to name them.

If you think you'll eventually want to squash the review into a
single commit, use the `--branch` option.
If you don't provide a name, one will be created for you like
`review/main-2026-09-20`.
Otherwise the applied changes and comments are ordinary edits to the
`.tex` files, which you commit like any other.

## Multiple reviewers, and running it twice

Merging is idempotent.
An edit that's already in the source is recognized and skipped,
and so is a comment that's already there,
so rerunning on the same document is harmless,
and you can merge a second reviewer's copy of the same export the same
way as the first.
Since each document carries the text it was sent with and is compared
against that,
never against another reviewer's copy or against your current source,
they can arrive and be merged in any order, weeks apart.

When an edit no longer fits,
because you took a different version from someone else
or edited the paragraph yourself since the export,
it's shown three ways:
the paragraph as it was sent, as it is now, and as this reviewer wants
it.
You pick one or edit the result.

A reviewer who turns protection off and edits without tracking
loses nothing:
the document still carries the text as sent,
so their edits are found the same way as accepted ones,
only without a name attached.
