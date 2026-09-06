# Design notes: LaTeX review via Word

Feasibility notes behind the
[LaTeX and Word tutorial](../tutorials/latex-word.md).
Not user-facing.
Complements the ingestion notes in PR #1580 (`docs/dev/docx-ingestion.md`),
which cover the diffing side in more depth; this covers the rendering side,
the stateless first version, and the repo-first session design that can
follow it.

Everything below was checked with a small two-column `article` paper
(natbib citations, an `\input` file, a display equation, inline math, a
PDF figure, a booktabs table, and cross-references) on macOS with Word,
LibreOffice, pdflatex, and pandoc 3.6.4.

## Getting a Word document that looks like the PDF

Four converters were tried on the same PDF or source.

| Path                   | Fidelity                                                                                 | Structure                                                                              | Runs where               |
| ---------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------ |
| Word's own PDF import  | Near identical: two columns, fonts, figure, citations, bibliography, cross-refs all kept | Real paragraphs in reading order; equation becomes a shape, table becomes tabbed lines | Mac or Windows with Word |
| pandoc from `.tex`     | Plain manuscript look, single column; figure and table numbers lost                      | Clean paragraphs, native editable equations, citeproc bibliography                     | Anywhere                 |
| pdf2docx               | Layout roughly kept                                                                      | Inter-word spaces dropped with Computer Modern fonts; paragraphs split by column       | Anywhere                 |
| LibreOffice PDF import | Visual only                                                                              | Every line is a text frame; zero body paragraphs                                       | Anywhere                 |

Word's import is the only path that satisfies "looks like the PDF" and
also yields editable paragraphs a reviewer can track changes in.
It confirms the hunch in #1529.
pdf2docx and LibreOffice are out.
Pandoc from source is genuinely usable, just not pretty:
with a Lua filter it can resolve `\ref` and `\eqref` from the `.aux`
file we already produce, and `--citeproc` with the project's `.bib`
gives a bibliography close to natbib's.
Figures need converting from PDF to PNG first, since Word can't render
PDF images on Windows.

It should not ship as a fallback in the first version, though.
Pandoc isn't part of the Calkit environment, and Calkit's rule is to
ship requirements with Calkit or with the project rather than customize
the system.
Bundling a 30 MB binary with Calkit, or adding a curl-to-`~/.local/bin`
entry to the `calkit install` registry, is a lot for a path nobody
should prefer.
If it's built later it runs the way TeX Live does: in a Docker
environment declared in the project, e.g., the `pandoc/latex` image,
which bundles pandoc with a TeX Live, so the render runs in the
document's own environment via `--env` exactly as `calkit latex diff`
does.
That's also what the hub would run.
Without Word, the honest first-version answer is that the Word copy
can't be produced on this machine.

So: Word is a requirement, and that's acceptable.
The Word path itself adds no dependency:
`docx2pdf` is already present for the automation, and the `.docx`
post-processing is zip and XML from the standard library.
`docx2pdf` is already a dependency and already automates Word through
AppleScript on macOS and COM on Windows, so `calkit office word-to-pdf`
is the precedent.
PDF import is the same call in the other direction:
`Documents.Open` on a `.pdf` triggers Word's reflow, then save as
`.docx`.
Suppress the "Word will now convert your PDF" alert with
`display alerts to alerts none` (macOS) or `DisplayAlerts = 0` (COM).

Known fidelity gaps in Word's import, none of which block the workflow:

- Display equations come through as drawings, not OMML, so a reviewer
  can't edit them.
  They can comment on them, which is what a Word-only collaborator would
  do anyway.
- Inline math is flattened to text, e.g., `$f_s = 1$~kHz` reads as
  `fs = 1 kHz`.
  This matters for anchoring, see below.
- Tables become tab-separated paragraphs rather than Word tables.
- Fonts are substituted, so line breaks shift slightly.

## Markers survive the trip

The ingestion notes say a source map only exists if we control the
render, and that if we don't, inject markers into the source and find
them in the output.
That works through Word's import.

In the marked build, each text-mode paragraph start gets a macro that
typesets a short letters-only token in a 2pt font, zero width, with the
PDF text render mode set to invisible:

```latex
\newcommand{\ckp}[1]{\rlap{\pdfliteral{3 Tr}%
  {\fontsize{2}{2}\selectfont ckx#1xkc}\pdfliteral{0 Tr}}}
```

`\pdfliteral` is pdfTeX's spelling.
The marked build runs in the project's own environment and engine, so
the macro needs the `iftex` three-way switch:
`\pdfextension literal` for LuaTeX and `\special{pdf:literal ...}`
for XeTeX.

The token is in the PDF's text layer (`pdftotext` finds it), invisible
on the page, and Word's import carries it into the `.docx` as a tiny
paragraph of its own immediately before the paragraph it marks.
Word also restored reading order across the two columns, so markers
came out in source order even though `pdftotext` did not.
A post-processing pass then deletes each marker paragraph and inserts a
`w:bookmarkStart`/`w:bookmarkEnd` pair named `ck_p0001` etc. at the
start of the following paragraph.
Underscores in the token render as spaces, hence the letters-only
form.

The marked build is a separate compile into a temporary directory, the
way `calkit latex diff` builds its worktree copies, so the project's
own source is never touched.
The sidecar map records bookmark name to flattened source line, and the
flattening is `latexpand`, which `calkit latex diff` already uses, so
line numbers can be mapped back to the original `\input` files.

The bookmarks then survived a Word editing session with tracked changes
and a save, as did document core properties (`identifier` and
`keywords`), which is where the session ID goes so an ingested file
identifies its own session regardless of file name.

Marker placement is a heuristic over the flattened source:
after a blank line, outside environments, not on a line starting with a
command like `\section` or `\begin`.
The prototype missed paragraphs that start right after `\end{equation}`
and the first paragraph inside `abstract`.
That's fine, since the sidecar plus sequence alignment is the baseline
and bookmarks are the bonus, but the heuristic should be tested against
a few real papers before it ships.

## Ingesting the marked-up document

A prototype of the diff side, on a document edited in Word with tracked
changes and a comment, produced exactly what the ingestion notes
predict:

- Final-view text per body paragraph (skip `w:del`, keep `w:ins`, skip
  text boxes), aligned against our original with `difflib` at paragraph
  granularity and then word granularity.
- A deleted sentence in Methods resolved via its bookmark to the source
  line and the longest common substring found the span in the `.tex`.
- A paragraph the reviewer added showed as an insert with no bookmark,
  positioned by the neighboring paragraphs.
- The comment came out of `word/comments.xml` with author and text.
  Its anchor is the paragraph containing the comment range.

Pandoc's docx reader with `--track-changes=all` sees the same
insertions, deletions, and comments, and could serve as the normalizer
on both sides instead of hand-written XML walking.
It's worth weighing:
it's less code, but it's a large binary dependency for something a
hundred lines of standard-library XML does, and we already need the
`.docx` XML for bookmarks and properties.
The dependency rule above settles it: no pandoc.

The hard residual is edits that land on text that doesn't exist in the
source verbatim: inline math, `\cite` keys, `~` and `--`, `\emph`.
A change to "the flow is turbulent" applies mechanically because the
words are in the `.tex`.
A change to "fs = 1 kHz" doesn't, because the source says
`$f_s = 1$~kHz`.
The plan is:

1. Try to locate the reviewer's _original_ span in the paragraph's
   source lines.
   If it's found verbatim, replace it.
2. If it isn't, tokenize the source line into words and markup, align
   the words against the rendered text, and apply the change to the
   word tokens only if every changed word maps to a plain-text token.
3. Otherwise show the reviewer's version next to the source and let the
   lead apply it by hand or defer it as a task.

Step 3 is the honest floor and it must stay cheap in the UI.

## The stateless first version

Sessions aren't needed to ship, because of one property of the returned
file: with `w:documentProtection w:edit="trackedChanges"` the `.docx`
contains both the text we sent (reject all) and the text the reviewer
wants (accept all).
Ingest is therefore XML on one file, needs no stored original and no
Word, and the source map isn't needed either if bookmark names carry
the anchor.
Comments go back into the source as `% REVIEW (...)` lines above the
paragraph, where the lead resolves them by deleting them.
The only record of a review is the diff it produced.

The `.docx` is the contract, and the parts that must not change later:

- **Core properties.**
  `identifier` holds `calkit-review:<uuid>:<rev>:<tex path>`, and
  `keywords` a text fingerprint of the sent body, so untracked edits
  are detectable.
  The UUID is unused in v1 and exists so sessions and hub delivery can
  key on it without touching the file format.
  Both properties survived a Word edit-and-save in testing.
- **Bookmark names.**
  Word allows 40 characters, letters and digits and underscores,
  starting with a letter.
  `ck_<8-char hash of the source path>_<line>` fits, and the path
  resolves against the file list at the pinned rev.
  Encoding the anchor beats an index into a sidecar precisely because
  there is no sidecar.
- **The comment line format**, so later tooling can ingest existing
  ones into tasks.

What stateless can't do, and what sessions add later:
memory of what was skipped, "another reviewer changed this paragraph",
who was sent what and when, and hub delivery.
Idempotency has to be designed in from the start regardless:
an edit already applied shows the new text where the old was expected,
and a comment already present matches by content, so a rerun on the
same file skips both.

The protection was tested in Word for Mac by driving it with
AppleScript:

- `<w:documentProtection w:edit="trackedChanges" w:enforcement="1"/>`
  with no password, placed in `settings.xml` between `w:zoom` and
  `w:defaultTabStop`.
  Word is strict about schema order here; out of place, the file opens
  as nothing at all.
- Word reported the protection as "allow only revisions."
  With tracking never turned on, and after an explicit attempt to turn
  it off, two find-and-replace edits came back as two `w:ins` and two
  `w:del`, and the protection survived the save.
- Reject-all on the returned file, i.e., skip `w:ins` and keep
  `w:delText` in document order, reproduced the sent text exactly.
- Unprotecting without a password succeeds, as expected.
  After that, an edit came back untracked and the element was saved
  with `w:enforcement="0"`.

So the enforcement value on the returned file says whether reject-all
can be trusted, before the fingerprint is even needed.
If the reviewer stopped protection and edited untracked, the
fingerprint mismatches, and the fallback is to rebuild the sent copy
from the rev (needs Word) or to warn and merge only the comments.

## Repo-first reviews with the hub as a view (later)

Everything in this section is the layer that can be added on top of the
stateless version, keyed on the export UUID.

The question in #1529 was whether the hub can be a transparent view over
a process that lives in the repo.
Mostly yes, with two exceptions that are inherent rather than design
choices.

Everything the process produces is a file:
the manifest, the two originals, the sidecar, the returned documents,
and the decision log.
Given those files at a commit, the diff and the per-change state are
deterministic, so the CLI and the hub compute the same view from the
same data.
Accepting a change is a text edit to a `.tex` file plus a line in
`decisions.yaml`; the hub can make that commit through its existing
repo access, and the CLI does it in the working tree.
Neither needs the other.

The exceptions:

- **Rendering needs Word**, so the hub can't start the high-fidelity
  session itself.
  Starting a session is a CLI operation, and the hub receives the result
  on push.
  A Docker-based pandoc render for the "I'm on Linux and don't care how
  it looks" case can come later, per the dependency rule above.
- **Receiving responses needs a mailbox.**
  A reviewer replying to an email has to hit a server.
  That's the one thing that is hub-only, and it's the contribution
  request machinery from #1580: the request row, the token, the reply
  address.
  The returned file is held there only until it's pulled into
  `responses/`, at which point the repo is the record again.
  Without a hub, the mailbox is the lead's own inbox and
  `calkit review ingest <file>` does the pull.

### One kind of request

#1580 has a general **contribution request** with a permission ladder
(view, comment, suggest, edit), a submit mode for bulk uploads, inbound
access requests, and public calls, all as hub rows.
A review session looked like a second concept next to that.
It isn't: a review request _is_ the request, and it's the only kind we
need.

- View, comment, and suggest are review requests at three permission
  levels.
  Comment-only is a real case (the PI you want opinions from, not
  rewrites), and the `.docx` can enforce it:
  `w:documentProtection` with `w:edit="comments"` locks Word to
  comments, and `w:edit="trackedChanges"` forces tracked changes on,
  which also settles "the reviewer forgot to turn them on."
  Neither needs a password; a determined reviewer can stop protection,
  and the diff handles that anyway.
- Edit, meaning direct commits to the default branch, is what a
  collaborator invite link already grants.
  It doesn't need to be a request.
- Submit (a hundred authors each uploading a chapter) is a different
  feature with a different shape.
  Defer it rather than generalize for it now.
- Inbound access requests are a pending invite, not a review.
  Public calls are many review requests.

So the repo record is `.calkit/reviews/<session>/`, a session being one
document at one revision sent to one or more recipients, with one
review request per recipient inside it.
The session is the unit that shares a rendered original; the request is
the unit that gets chased, revoked, and superseded.

The split with the hub follows from that:

- **Repo**: everything the lead decided.
  The session, its requests, their permission and identity requirement
  and due date, status changes, pulled responses, and decisions.
  Closing or revoking from the hub UI is a commit, like accepting a
  change.
- **Hub**: delivery and the inbox.
  Token hash, reply key, sent and viewed state, and responses nobody has
  pulled yet.
  A response enters the repo when the lead pulls it, so a public call
  with ninety declined responses puts nothing in `git log`, which is the
  same "a response is data, not a branch" argument #1580 makes.

`ContribRequest` in #1580 therefore becomes two things: the fields
that are the lead's decisions turn into the `review.yaml` schema, and
the hub row keeps the delivery fields plus a pointer to the session and
request in the repo.

### Worktree files, not the Git database

The session could live outside the worktree, in custom refs the way
git-bug stores issues.
It shouldn't, for the same reason `.calkit/overleaf-sync.json` is a
tracked file:
the record has to move in lockstep with the source.
Accepting a change is a `.tex` edit plus a decision, and if both are
worktree files they share a commit, so `git revert` undoes both together
and the log never claims a change was accepted when the source says
otherwise.
Custom refs would put the two in separate histories, need explicit push
refspecs, be invisible to the GitHub UI and VS Code, and be untrackable
by DVC.
Those costs may be fine for comment threads later, which is what git-bug
is for; they're wrong for this.

Consequences:

- One commit per accepted change, made by ingest, referencing the
  session and reviewer.
  Reversal is then `git revert` rather than inverse-patch machinery, and
  "squash into one commit" from #1580 is a `git rebase` the lead can do
  or skip.
- Ingest therefore requires the reviewed `.tex` files to be clean, so
  the lead's in-progress edits don't get swept into an accept commit.
  Other files can be dirty.
- Reverting the session's creating commit cancels the review.
  The hub treats a session missing from the repo on push as revoked and
  closes its requests.
  A document that comes back afterwards still identifies its session
  from its properties, and the original is still in history at the
  pinned commit, so ingest can offer to proceed anyway.
- `original.docx` and the responses go in Git, not DVC, so a session is
  complete in any clone and the hub can render it without a DVC fetch.
  They're tens of kilobytes for a typical paper.
  A paper full of embedded figures could reach megabytes, which is
  still tolerable for something that happens a few times per paper.
- Decisions are one file per response, under `responses/<reviewer>/`,
  so two people ingesting different responses on different branches
  don't conflict on a shared YAML file.

Open decisions:

- Command naming.
  The tutorial uses `calkit new review-session` and `calkit review
ingest|send|show`; #1580 uses `calkit task ingest`.
  The task commands should probably be what ingest creates, not what
  runs it.

## Not needed for a first version

- An Office add-in.
  It would let a reviewer submit from inside Word and could set
  bookmarks natively, but email reply already covers submission, and
  bookmarks are already surviving.
  Revisit if reviewers on Word for the web turn out to matter, since
  the desktop-only PDF import is on the lead's side, not theirs.
- Per-change author attribution from `w:ins`/`w:del`.
  One response file per reviewer already tells us who.
- Handling a file that went through Google Docs.
  Bookmarks are lost, sequence alignment still works, and the
  ingestion notes already say so.

## Journal reviews and the reviewer's side (#1435)

Out of scope for the first version, but the layout should not preclude
it, and it doesn't.

A journal's reviews arrive as text or PDF rather than `.docx`.
They fit the same session model:
a session created at the submitted revision with no recipients, e.g.,
`--external "JFM round 1"`, whose responses are ingested as they
arrive.
Only the reader is format-specific.
The docx reader diffs against our render; a PDF reader takes the text
under each highlight; a text reader parses "Line 33, 'quote': comment"
and anchors by the quote with the line number as a hint.
The pinned `original.pdf` is what makes the line numbers resolvable,
since they refer to the submitted PDF, not the current source.
Text and PDF reviews yield tasks rather than applicable changes, except
where the reviewer wrote suggested wording.

#1435 is the mirror image, us as the reviewer of someone else's paper,
producing a text file to paste into the journal's form.
The text format proposed there is the bridge:
the PDF viewer writes it when we review, the text reader ingests it
when we're reviewed, and a paper between two Calkit users round-trips.
Design that format once, for both directions, when the docx path has
shipped.

Private storage needs nothing new.
A manuscript under review lives in a private project, possibly never
pushed, with the PDF in DVC against a private remote or none, which
already exists.
The distributed-first design already rules out anything that would
require the hub to see the document.
