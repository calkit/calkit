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

## Comments

These show up in the raw TeX source like:

```tex
% COMMENT author=user@email.com resolved=false
% This is the comment body.
%%%% REPLY author=replier@other.net
%%%% As you can see, we indent for thread.
This is the text being commented on.

% COMMENT author=reviewer-2
% This is something you should change.
```

The objective is to make it readable in TeX.
These comments will make their way out into the docx,
and docx comments will make their way back into TeX.
Deleting is okay, but it's probably a good idea to do this in the Git
commit history.
