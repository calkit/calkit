# Collaborating on a LaTeX document using Microsoft Word for feedback

Teams have a variety of tolerance for markup languages and complex
system setup.
Thus, despite its limitations for technical writing,
Microsoft Word remains an important tool.
In some projects, the lead may want to use LaTeX or some other
text-first typesetting system like Quarto since those make it easier
to ensure document components like figures, tables, and values remain
up-to-date with the analysis,
but the rest of the team does not want to engage in that way.
They prefer a WYSIWYG experience without needing to sign up for a web
app like Overleaf (or Calkit for that matter).

However, converting from LaTeX to Word with something like Pandoc produces
a Word document that doesn't look like the final output,
and migrating the contributions back into LaTeX is a tedious manual process.
For these situations, Calkit supports a workflow where the source of
truth is LaTeX, but Word documents can be sent out for review,
and the project lead can merge the comments and edits from the `.docx` files
back into the main project as to-do items and LaTeX changes,
respectively.

Nothing about the process is stored in the project:
the Word document carries everything Calkit needs to merge it back,
so you export it, email it, and merge whatever comes back,
whenever it comes back.

<!-- prettier-ignore -->
!!! note
    Producing a Word document that looks like the PDF requires
    Microsoft Word itself, on macOS or Windows, on the machine that
    exports it.
    Reviewers only need Word, or anything that can edit a `.docx`,
    and merging the result back needs neither.
    Nothing else needs installing: the document is built in the
    project's own LaTeX environment, as usual.

## Exporting the document for review

Assuming we have a LaTeX document in our Calkit project at `paper/main.tex`,
already set up to build in the project pipeline,
we can export a Word copy of it with:

```sh
calkit latex to-docx paper/main.tex
```

The export is pinned to a commit,
so Calkit will ask you to commit any outstanding changes first,
then rebuild the document to make sure the PDF matches the source.
It then compiles a copy of the document with invisible paragraph
markers, opens that PDF in Word to convert it to `.docx`,
and turns the markers into bookmarks that record which line of which
source file each paragraph came from.
The result is written next to the document as `paper/main-review.docx`.
It doesn't need to be committed:
its document properties record the commit it was built from,
the source file it came from, and a fingerprint of its text,
and those survive editing and saving in Word.

By default the document has tracked changes forced on,
so nobody has to remember to turn them on,
and the reviewer's edits and comments both come back in the same file.
With `--permission comment` the document is locked to comments only,
for the reviewer you want opinions from but not rewrites.

Email the file to your reviewers.
Nothing about their side of the process involves Calkit.

## Merging a marked-up document back

When a marked-up document comes back, merge it:

```sh
calkit latex merge-docx ~/Downloads/main_advisor_comments.docx
```

Calkit reads the commit from the document,
takes the text as sent and the text as edited from the tracked changes
in the file itself,
and finds every insertion, deletion, and comment.
Each is anchored to a source line at that commit,
then carried forward to your current source the way a patch is:
by line number first, and by matching text when the file has moved on.

Calkit then walks you through each edit:

```
[1/14] paper/methods.tex:31 (A. Reviewer)
  - We measured the velocity field with a two-component laser Doppler
  - velocimeter~\citep{lee2018}. The sampling frequency was $f_s = 1$~kHz
  - and the integral time scale was estimated from the autocorrelation.
  + We measured the velocity field with a two-component laser Doppler
  + velocimeter~\citep{lee2018}.
  Apply, skip, or edit? [a/s/e]
```

Applying writes the change to the LaTeX source in your working tree.
Skipping leaves the source alone.
Comments are written into the source as LaTeX comments,
just above the paragraph they were left on,
where they stay until you delete them:

```latex
% REVIEW (A. Reviewer, 2026-09-14): Quantify this: give an RMS error.
The model in Eq.~\eqref{eq:wake} fits the data in Sec.~\ref{sec:methods}
reasonably well.
```

Some edits can't be applied mechanically,
e.g., a change inside an equation, a citation, or a table,
since the reviewer was editing rendered text rather than the LaTeX that
produced it.
Those are shown with the reviewer's version alongside the source line,
and you can apply them by hand with `e` or skip them.

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
Since each document is compared against the text it was sent with,
never against another reviewer's copy or against your current source,
they can arrive and be merged in any order, weeks apart.

When an edit no longer fits,
because you took a different version from someone else
or edited the paragraph yourself since the export,
it's shown three ways:
the paragraph as it was sent, as it is now, and as this reviewer wants
it.
You pick one or edit the result.

A reviewer who turns protection off and edits without tracking makes
their edits indistinguishable from the original.
Calkit detects this from the text fingerprint and,
if Word is available, rebuilds the sent copy from the recorded commit
to compare against.
Otherwise it says so and merges only the comments.

## What comes later

Everything above is stateless:
the only record of a review is the diff it produced.
That's enough to ship, and the Word document is the contract that
keeps it extensible.
Each export carries a unique ID alongside the commit and source path,
so later layers can refer to an export without changing the file or
the merge command:

- **Review sessions** that remember who was sent what and when,
  which edits were skipped, and which paragraphs more than one reviewer
  touched, stored in the repo under `.calkit/reviews/`.
- **Sending through the hub**, with a reply address per reviewer,
  so a returned document lands in the project without passing through
  your inbox.
- **Comments as tasks** rather than source comments,
  with threads that show up on the hub,
  ingested from the same `% REVIEW` lines.

## TODO

These are some design decisions we need to make:

- [ ] Fully distributed or brokered by the hub? Do we want these interactions to actually live in the repo?
  - Feasible to keep them in the repo; see the
    [design notes](../dev/latex-word.md).
    Only rendering (needs Word) and receiving replies (needs a mailbox)
    can't be repo-local.
- [ ] How important is it that the Word doc look like the LaTeX PDF?
  - Word's own PDF import gets us nearly identical for free, so we don't
    have to trade this off against editability. A Pandoc fallback is
    possible but not worth shipping in v1; see the design notes.
- [ ] Is Word a requirement?
  - Only for the high-fidelity render on the lead's machine. Reviewers
    need anything that edits `.docx`. `docx2pdf` already automates
    Word on Mac and Windows.
- [ ] Integrate git-bug now for conversations around comments?
- [ ] Can it be more stateless, i.e., do we need review sessions, or can we simply try to merge a docx back into tex source idempotently?
  - Yes, and that's now the MVP above. With tracked changes forced on,
    the returned `.docx` contains both what we sent (reject all) and
    what the reviewer wants (accept all), and bookmark names encode the
    source anchor, so nothing has to be stored. Sessions become an
    optional layer on top; see [what comes later](#what-comes-later).
- [ ] Comment threads in document or in review database? If in review database how do we keep them attached to the content? I suppose the start of a review is at a pinned version, so line numbers synctex-ish workflow works. We also want these comments to show up on the hub though, and we have a database table for these.
  - Where a thread is anchored and where it lives are separate
    questions. The anchor (bookmark, source file and line, quoted
    text) is valid at the pinned revision however the source moves
    afterward, the same way a patch hunk is, so it can sit in the
    review directory. The conversation can live wherever tasks end up,
    git-bug eventually, with the hub table as a mirror synced on push.
  - Tension: putting human interaction in a repo that may one day be
    public could scare off users. The reviewer's raw comments and the
    returned `.docx` are in `.calkit/reviews/` under this design, and
    history keeps them even if they're deleted later. GitHub keeps a
    clear border between the repo and communication about it.
    Transparency and distributed operation are still worth having.
  - Git itself has that border: worktree files are the work, and refs
    outside the default push refspec (git-bug's approach) are
    communication about it, not cloned or shown by GitHub unless asked
    for. So threads and possibly the raw responses could be
    distributed without being in the tree, while decisions, which
    must move in lockstep with the source, stay in the worktree.
