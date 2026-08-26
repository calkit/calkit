# Project management

Research projects accumulate work from everywhere.
Your advisor's comments on the manuscript, reviewer 2's report, the thing
you noticed about the boundary conditions on Tuesday, and the discussion
section nobody has written yet are all work,
and they all need to end up in the same place if any of them are going to
get done.

Calkit keeps them as **tasks**:
one card per unit of human work, on one board per project.
Most tasks arrive as feedback on a
[contribution request](collaboration.md)--that's where the bulk of them
come from--but a task doesn't need an origin.
"Write the discussion section" is the same kind of card as "reviewer 2
wants the axes logarithmic," and putting them on two different boards
guarantees neither is the one people actually use.

<!-- prettier-ignore -->
!!! note
    A task here is a unit of *human* work.
    Computational work is a pipeline
    [stage](pipeline/index.md), which is a different thing with a
    different lifecycle.

## Marked-up documents become tasks

Emailing a Word document to your PI is only worth it if what comes back
doesn't land on you as a merge chore.
Retyping forty tracked changes into a `.tex` file by hand is worse than
the problem it solved.

It doesn't have to work that way, because tracked changes and comments in
a `.docx` aren't prose--they're structured data.
Every insertion, deletion, and comment is a separate, addressable record
with its own author, timestamp, and anchor in the text.
Calkit pulls them out and turns each one into a single item in a queue:
what was said, where it applies, and what it proposes.

Since the document was generated from the project's own source, each item
carries enough surrounding context to be matched back to the LaTeX or
Markdown it came from.
When the match is unambiguous, the item becomes a suggestion you accept
or reject like any other, and accepting writes it to the source.
When it isn't--and it won't always be--the item stays in the queue with
its context attached, for you to place by hand.

<!-- prettier-ignore -->
!!! warning
    Sentence-level edits and comments round-trip well.
    Structural surgery does not:
    reordered sections, rebuilt tables, rewritten equations, and anything
    touching generated figures will come back as items that need a human.
    The goal isn't a perfect automatic merge, it's never having to hunt
    through a document for what changed.

The queue is the point.
Working through feedback one item at a time, checking each off, is what
people already do by hand--exporting a marked-up PDF's comments into
GitHub issues so there's a list to grind through.
Calkit makes that the default, and it's the same queue no matter how the
feedback arrived:
tracked changes from Word, highlights on a PDF, or comments typed
directly in the hub.
If the project is on GitHub, items can be mirrored to issues so they sit
alongside the rest of the project's work.

## The board

A flat list is the right shape for forty tracked changes you click
through in an afternoon.
It's the wrong shape for _"redo Figure 3 with log axes and rerun the
sweep,"_ which is a week of work that arrived in the same review as the
typos.

Those need two different questions asked about them, and it's worth
keeping them apart:

- **Do I agree with this?** Accept or reject. A verdict on the feedback.
- **Have I done it?** To do, in progress, blocked, done. Progress on the
  work.

For a typo the two collapse into one click--accepting applies it and
it's finished.
For anything real, agreeing to a change is where the work _starts_.
A queue that only knows accepted and rejected has nowhere to put the
three weeks in between, which is exactly where a paper revision lives.

So the hub renders the queue as a **board**.
Accepted items that could be applied automatically go straight to done;
everything else lands in to do as a card, to be assigned, moved, and
worked through.

The board is per project, not per review, because that's how the work
actually arrives:
a student revising a manuscript is holding their advisor's comments,
reviewer 2's report, and their own notes at the same time, and wants one
place to see what's left rather than three.
Cards carry where they came from, so "everything from the PI's review"
stays a filter rather than a separate list.

<!-- prettier-ignore -->
!!! tip
    Because the items are repo data rather than rows in the hub's
    database, the board is a view over something you already have.
    It can be mirrored to GitHub Issues or Projects,
    rendered by a Git-native tracker like git-bug,
    or listed by the CLI on a plane with no wifi--and they're all
    looking at the same cards.

## Working without the hub

A hub is optional in Calkit, and this feature shouldn't be the exception.
If a student gets a marked-up `.docx` back from their advisor by email,
they should be able to turn it into a work queue on their own laptop,
in a project that was never pushed to a hub at all.

So the queue is **data in the repo**, not a row in somebody's database.
Ingestion is a local operation:

```sh
calkit task ingest advisor-review.docx
```

This reads the tracked changes and comments out of the document, matches
them against the project's source, and writes one item per change into
the repo, where they're committed alongside everything else.
From there the queue is worked through locally:

```sh
calkit task list
calkit task show 7
calkit task apply 7
calkit task start 7
calkit task done 7
```

`calkit task list` is the same board the hub renders, printed as
columns.

Nothing about this requires a network.
The items are plain, readable, diffable files--the same choice
`calkit.yaml` makes--so they can be inspected with `git log`, edited in a
text editor, or read by tooling that has never heard of Calkit.
Someone who walks away from Calkit entirely still has their review
history, in their repo, in a format they can parse.

<!-- prettier-ignore -->
!!! note
    This splits cleanly along a real line.
    *Sending* a request needs a hub: there has to be something to receive
    an email, host a link, and check a token.
    *Everything that comes back* is repo data, and needs nothing.
    The hub renders the queue and makes it pleasant to work with--which
    on the web will always be the easiest path--but it doesn't own it.

Because the queue lives in Git, the other places it could show up are
mirrors rather than copies:
GitHub issues via the API or a webhook, a hub project board, or a
Git-native issue tracker like
[git-bug](https://github.com/git-bug/git-bug), which already stores
issues in refs and has bridges to the major forges.

### Where GitHub actually comes in

Following this through, it's fair to ask whether it ends in Calkit
hosting Git itself.
It's worth being precise about where the pressure is real, because most
of it isn't.

Queue items are repo content, so they work on any host, or none.
A responder doesn't need a GitHub account:
the hub already commits with the responder's identity as the author and
pushes with the project owner's credentials, which is how GitHub-less
collaborators work today.

The one new pressure this feature could create is an open call with a
hundred respondents.
Turning each submission into a branch would mean a hundred branches on a
repo, most of which will be declined--noise pushed somewhere the project
may not fully control, and cleanup afterward.

The design avoids that by construction:
**a response is data, not a branch.**
Suggestions are held as items until somebody accepts them, and a branch
or commit is a _product_ of acceptance rather than a precondition for
submitting.
Nothing has to be pushed anywhere for a hundred people to contribute and
for ninety of those contributions to be turned down.

What remains is a pre-existing constraint rather than one this feature
introduces:
a project has to be on GitHub for the hub to hold its Git at all,
which is why several places in the codebase are already marked
"until git hosting is decoupled from GitHub."
That decision stands on its own merits, and contribution requests are built so
they don't depend on which way it goes:
GitHub issues and pull requests are mirrors here, pointed at by nullable
fields, never the place the data lives.

<!-- prettier-ignore -->
!!! warning "Under construction"
    The task board is in design.
    Open questions:

    - Whether patch selection is presented hunk-by-hunk with checkboxes,
      or at the level of individual commits.
    - Whether task records live as files in the working tree or in Git
      refs, e.g., `refs/calkit/tasks/`.
      Files are readable by anything and show up in `git log`; refs keep
      the working tree clean and are what git-bug already does.
      Both are cloneable and offline-first, which is the requirement.
    - Exactly which CLI commands exist and what they're called.
      The names above are a sketch, not a decision.
    - Whether board columns are fixed or per project.
    - How far document ingestion should go beyond `.docx`, e.g., PDF
      annotations exported from Acrobat or Preview, or an emailed reply
      quoting the text it's about.
