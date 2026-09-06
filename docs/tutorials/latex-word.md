# Collaborating on a LaTeX document using Microsoft Word for feedback

Teams have a variety of tolerance for markup languages and complex
system setup.
Thus, despite its limitations for technical writing,
Microsoft Word remains an important tool.
In some projects, the lead may want to use LaTeX or some other
text-first typesetting system like Quarto,
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

The whole process is recorded in the project repo,
so it works the same whether you drive it from the CLI,
from the Calkit web app, or a bit of both.

<!-- prettier-ignore -->
!!! note
    Producing a Word document that looks like the PDF requires
    Microsoft Word itself, on macOS or Windows, on the machine that
    starts the review.
    Reviewers only need Word, or anything that can edit a `.docx`.
    Without Word, Calkit falls back to Pandoc, which produces a clean
    but plainer document.

## Starting a review session

Assuming we have a LaTeX document in our Calkit project at `paper/main.tex`,
already set up to build in the project pipeline,
we can start a review session for it with:

```sh
calkit new review-session paper/main.tex \
    --to advisor@university.edu \
    --to coauthor@elsewhere.org \
    --due 2026-09-20
```

A review session is pinned to a commit,
so Calkit will ask you to commit any outstanding changes first,
then rebuild the document to make sure the PDF matches the source.
It then compiles a copy of the document with invisible paragraph markers,
opens that PDF in Word to convert it to `.docx`,
and turns the markers into bookmarks that let the edits find their way
back to the right lines of LaTeX later.
Finally, it writes the session to `.calkit/reviews/main-2026-09-06/`:

```
.calkit/reviews/main-2026-09-06/
├── review.yaml       # document, commit, reviewers, due date, status
├── original.pdf      # what the reviewers were sent
├── original.docx     # the Word copy, tagged with the session ID
├── sourcemap.json    # paragraph bookmark -> source file and line
├── responses/        # returned documents, one per reviewer
└── decisions.yaml    # what you did with each change
```

These files are committed to the project,
which is what makes the session portable:
a teammate who clones the repo, or the web app looking at it,
sees exactly the same session.

## Sending it out

The simplest way to send the document is to email
`original.docx` yourself.
The file carries the session ID in its document properties,
which survives editing and saving in Word,
so Calkit can tell which session a returned file belongs to
no matter what it has been renamed to.

If the project is connected to the Calkit hub,
you can instead let it do the sending:

```sh
calkit review send main-2026-09-06
```

This pushes the session and creates one contribution request per
reviewer, each with an email containing the document and a reply address
unique to that request.
The reviewer marks up the document in Word and replies with it attached.
Nothing about their side of the process involves Calkit.

## Ingesting the responses

When a marked-up document comes back by email, ingest it:

```sh
calkit review ingest ~/Downloads/main_advisor_comments.docx
```

If the hub sent the requests, the replies land in the session's inbox
instead, and pulling the project brings them into `responses/`.
Either way, ingestion is the same:
Calkit stores the returned file in `responses/`,
compares its text paragraph by paragraph against `original.docx`,
and finds every insertion, deletion, and comment.
Reviewers who forgot to turn on tracked changes are handled the same
way, since the comparison doesn't depend on Word's revision marks.

Calkit then walks you through each change:

```
[1/14] paper/methods.tex:31 (A. Reviewer)
  - We measured the velocity field with a two-component laser Doppler
  - velocimeter~\citep{lee2018}. The sampling frequency was $f_s = 1$~kHz
  - and the integral time scale was estimated from the autocorrelation.
  + We measured the velocity field with a two-component laser Doppler
  + velocimeter~\citep{lee2018}.
  Apply, reject, defer, or edit? [a/r/d/e]
```

Applying writes the change to the LaTeX source in your working tree.
Rejecting records the decision and moves on.
Deferring creates a task with the proposed change attached,
for the ones that need more thought than a keystroke.
Comments from the document always become tasks,
anchored to the paragraph they were left on:

```
[9/14] Comment on paper/main.tex:58 (A. Reviewer)
  "Quantify this: give an RMS error."
  Created task 12.
```

Some edits can't be applied mechanically,
e.g., a change inside an equation, a citation, or a table,
since the reviewer was editing rendered text rather than the LaTeX that
produced it.
Those are shown with the reviewer's version alongside the source line,
and you can apply them by hand with `e` or defer them.

Every decision is recorded in `decisions.yaml`,
and the applied changes are ordinary edits to the `.tex` files,
which you commit like any other.

## Multiple reviewers

Responses rarely arrive together,
and there's no need to wait for them.
Each one is compared against the same `original.docx`,
never against another response or against your current source,
so they can be ingested in any order and weeks apart,
and a change proposed by one reviewer is never disturbed by ingesting
another.

Accepting a change writes it to your source right away
and the session stays open,
so you can keep writing while the other reviewers take their time.
When a later response touches a paragraph another reviewer already
changed, Calkit says so before asking what to do,
showing the other reviewer's version and what you decided about it:

```
[3/11] paper/main.tex:24 (B. Coauthor)
  A. Reviewer also changed this paragraph (accepted).
  ...
```

If you'd rather hear from everyone before touching a paragraph,
defer it.
`calkit review show` groups deferred changes by paragraph across
reviewers, so once the last response is in you can settle each one with
all the opinions in front of you.

A change that no longer fits,
because you accepted a different version from someone else
or edited the paragraph yourself since the session started,
is shown three ways:
the paragraph as it was sent out, as it is now, and as this reviewer
wants it.
You pick one or edit the result.
Accepted changes can be reversed while the session is open,
provided nothing else has been written over them since.

A session closes when every reviewer has responded and every change
is decided.
You can also close it early with responses outstanding,
e.g., if a reviewer never sends theirs back,
and anything that comes in later is ingested against the session it
was sent from all the same.

## Reviewing the session later

To see where a session stands, e.g., who has responded and what is still
undecided:

```sh
calkit review show main-2026-09-06
```

You can rerun `calkit review ingest` on a response at any time to
revisit the changes you deferred or rejected.
The web app shows the same session from the same files,
with the same accept and reject controls,
so a decision made in the browser is committed to the repo just like one
made at the terminal.

When you've revised the document and want another round,
start a new session at the new revision and link it to the last one:

```sh
calkit new review-session paper/main.tex --supersedes main-2026-09-06
```

## TODO

These are some design decisions we need to make:

- [ ] Fully distributed or brokered by the hub? Do we want these interactions to actually live in the repo?
  - Feasible to keep them in the repo; see the
    [design notes](../dev/latex-word.md).
    Only rendering (needs Word) and receiving replies (needs a mailbox)
    can't be repo-local.
- [ ] How important is it that the Word doc look like the LaTeX PDF?
  - Word's own PDF import gets us nearly identical for free, so we don't
    have to trade this off against editability. Pandoc is the plainer
    fallback.
- [ ] Is Word a requirement?
  - Only for the high-fidelity render on the lead's machine. Reviewers
    need anything that edits `.docx`. `docx2pdf` already automates
    Word on Mac and Windows.
- [ ] Integrate git-bug now for conversations around comments?
- [ ] Can it be more stateless, i.e., do we need review sessions, or can we simply try to merge a docx back into tex source idempotently?
  - The diff needs the original we sent, pinned to a revision, so at
    minimum that file and the source map have to be kept somewhere. A
    session is just a name for that directory; the ingest itself is
    idempotent given those files.
