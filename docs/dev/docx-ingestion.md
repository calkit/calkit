# Design notes: ingesting an edited DOCX

Notes for implementing the marked-up document round trip described in
[project management](../project-management.md).
Not user-facing.

## Prior art: `docc diff`

[docc](https://github.com/kevinzehnder/docc) is a Markdown-to-DOCX
compiler (MIT).
[PR #41](https://github.com/kevinzehnder/docc/pull/41) added
`docc diff source.md edited.docx`, which compares a document it produced
against an edited copy.
It is worth reading in full before writing any of this,
because it solves the hard half of the problem in a way that isn't
obvious, and the file that does it opens with the sentence that matters:

> This file is deliberately not a DOCX importer.

## The inversion

The naive approach--and the one these docs originally described--is to
convert the returned `.docx` back to LaTeX or Markdown and match the
result against the project's source.
That means owning a faithful DOCX importer,
and it fails in the ordinary case,
because the conversion introduces differences that have nothing to do
with what the reviewer changed.

The better framing is that **we already have both sides**.
We rendered the review copy ourselves, from a pinned revision.
So we can extract canonical visible text from _our_ render and from _the
returned file_, and diff those.
Same producer on both sides, so every difference is either an edit or a
normalization bug--and normalization bugs are findable and fixable in a
way that importer fidelity is not.

Nothing has to be converted back to source to find out what changed.

## Reading tracked changes

`docc` extracts the **final view**: insertions stay, `w:del` and
`w:moveFrom` are skipped.
Diffing that against the original yields the changes without parsing
revision semantics at all.
It also means a reviewer who edited without tracking changes on is
handled by exactly the same path, which is worth having, since half of
them will forget.

The tradeoff: per-change author and timestamp are discarded.
For our case the author is usually known--it's whoever the request was
sent to--but a document that went round several people loses that.
If we need it, read `w:ins`/`w:del` attribution separately;
don't complicate the text extraction to get it.

## Paragraphs are the unit

Content comes out as a list of paragraph strings per "story" (body,
headers, footers).
That granularity is also the right one for us:
**one changed paragraph becomes one task.**
It answers the open question about how to split feedback into items, at
least for this path--prose has no delimiters, but a document has
paragraphs.

## Normalization is the whole game

These are the details that decide whether the diff is usable or full of
noise. Taken from `internal/docx/content.go`:

- Fields (`fldSimple`, `fldChar`/`instrText`) collapse to a
  `{INSTRUCTION}` marker rather than their cached result, so a page
  number or cross-reference doesn't read as an edit.
- `mc:Fallback` is skipped, or alternate content double-counts.
- Trailing hard breaks in a paragraph are trimmed, internal ones kept:
  Word and LibreOffice materialize the final layout break differently.
- Empty paragraphs are dropped.
- Header and footer parts are compared by their distinct text content,
  never by part name--applications rename and duplicate them on save.
- `w:tab` becomes `\t`; `w:br` and `w:cr` become `\n`.
- Per-part size cap and a zip path traversal check, since the input is a
  file someone emailed us.

## The test invariant

`docc` asserts that its fixtures compare **equal** after a LibreOffice
round trip.
That's the right invariant to steal:
normalization has to survive an open-and-save by a foreign application,
because that is exactly what a reviewer does before sending it back.
A test suite that only compares our own output to itself proves nothing.

## Where we need more than docc does

`docc` deliberately stops at reporting differences; it does not write
anything back.
We do, so we need one thing it doesn't:
**a source map emitted at render time**.

When the review copy is generated, record the mapping from each output
paragraph to the source range that produced it.
Ingestion then resolves a changed paragraph to an exact source location
rather than searching for it,
and the fuzzy context matching described in the user docs is only needed
for paragraphs the reviewer added or moved.

This is the difference between "usually finds the right spot" and
"knows", and it's cheap--but only if the renderer emits the map.
Retrofitting it later means rebuilding the ingestion path, so it should
land with the first version.

`Task.anchor_status` already models the residual: `resolved` for
anything the source map covers, `ambiguous` or `unresolved` for
restructuring that no mapping can survive.
See [anchoring](#anchoring-changes-back-to-the-source) for what the map
should actually contain, and why a line number isn't it.

## Anchoring changes back to the source

The open question is how a changed paragraph in the returned `.docx`
finds its place in the `.tex`.
Two traps here.

### Line numbers are a hint, not a coordinate

The obvious move is to record tex line numbers when rendering.
That works right up until the student keeps working, which they will:
the review copy went out at one revision and comes back days later
against a source that has moved.
Line numbers recorded then are stale now.

This is patch application, and `patch` already solved it--a hunk carries
a line hint _and_ surrounding context, and applies with fuzz when the
file has drifted.
Borrow the model rather than inventing one:

- `Task.anchor_line` is the hint, valid at the reviewed revision.
- `Task.original_text` is the verbatim string being replaced, and it's
  what actually decides. Never write on the strength of a line number
  alone--confirm the original still matches at or near it.
- `context_before` / `context_after` widen the search when it doesn't.
- If nothing matches, that's `anchor_status = "unresolved"` and a human
  places it. That outcome is fine and should stay cheap.

The alternative--rebasing each change through intervening commits--is
strictly more correct and much more machinery. Not for the first
version.

### Annotating the document is worth doing, but can't be trusted

Carrying the mapping _inside_ the `.docx` is attractive, because it
survives things a positional map can't: a reviewer who moves a paragraph
to a different section takes the annotation with them, and we still know
where it came from.

The right carrier is a **bookmark** (`w:bookmarkStart`/`w:bookmarkEnd`).
Bookmarks are a real Word feature, invisible to the reader, preserved
across saves, and Word maintains their position as surrounding text is
edited. Custom attributes in our own namespace are simpler but get
stripped on save; content controls are heavier and a user can delete
them. Bookmark names are limited (40 characters, no spaces, must start
with a letter), so something like `ck_p0142` indexing into the sidecar
map beats encoding a range in the name.

What they cannot do is be relied upon:

- A reviewer who pastes into Google Docs, edits, and exports destroys
  all of them.
- Copying a paragraph duplicates or drops bookmarks depending on the
  application.
- Nothing in the format obliges an editor to preserve them.

So: emit both. The sidecar map keyed to the pinned revision is the
baseline that works whatever came back, diff alignment recovers the
correspondence when paragraphs are inserted or deleted, and bookmarks
are an opportunistic bonus that rescues the moved-paragraph case. Verify
against `original_text` regardless of which one produced the answer.

### Granularity, and who renders the document

A paragraph-level map is not obviously enough.
A reviewer changing "the flow is turbulent" to "the flow was turbulent"
is editing rendered text, while the source reads
`The flow is turbulent~\cite{smith2020}.`
The edit has to land inside a line that contains markup the reviewer
never saw.

Paragraph granularity is still sufficient, though, as long as the
sub-paragraph step is a second, narrower search:
diff our rendered paragraph against theirs to isolate the changed span,
then find that span within the few source lines the paragraph maps to.
Searching five lines rather than a whole document makes ambiguity rare.

The real constraint is upstream: **a source map only exists if we
control the render.**
Pandoc's LaTeX reader doesn't track source positions, so a pandoc-driven
render can't emit one without post-hoc matching--which is the problem
this whole approach exists to avoid.

If the review copy is produced through a path we don't control, the
workable trick is to inject markers into the source before rendering,
e.g., a macro at each paragraph boundary that expands to a bookmark or a
zero-width sentinel, then locate the markers in the output. Decide this
before writing the ingestion side, because the answer determines whether
anchoring is exact or best-effort.

## Licensing

docc is MIT, so porting logic is fine with attribution.
Prefer reimplementing from the design--it's Go and ours will be
Python--but if any of it is translated closely, note the origin in the
module and keep the license notice.
