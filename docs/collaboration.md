# Collaboration

Research collaboration doesn't look like software development.
A grad student writes the paper, runs the pipeline, and makes the figures.
Their advisor and co-authors mostly read, comment, and suggest changes.
Those collaborators are rarely going to clone a repo, make a branch,
and open a pull request--and asking them to is how a project ends up
back on email, with `paper_v3_JS_comments_final.docx` as the source of truth
and no link between the reviewed text and the pipeline that produced
the figures in it.

Git makes this worse, not better.
Its model assumes each contributor has complete control of what they're
editing, so any overlap has to be serialized by hand.
That's where the real ceremony comes from--not the merge, but the email
before it:
_"I'm passing the pen to you, please check my section for typos."_
Wanting a co-author to read your draft shouldn't require negotiating
custody of the file.

A **collab request** is Calkit's answer.
It's a request for a specific contribution to a specific artifact,
sent to a specific person, with an explicit scope and deadline.
The recipient gets a link, does the work in the browser,
and sends it back.
The project lead decides what to accept.
Underneath it's still Git, so the provenance survives,
but nobody has to think about branches to participate.

<!-- prettier-ignore -->
!!! note
    Collab requests are the research-native replacement for pull requests.
    A pull request asks "merge branch A into branch B."
    A collab request asks "review Figure 2," "co-author Section 3," or
    "check the hyperparameters on the `train` stage."
    The framing is the deliverable, not the diff.

## Collaborators and requests

There are two ways someone takes part in a Calkit project, and they suit
different people.

**Collaborators** are members of the project.
They have an account, they see all of it, and they work in it
continuously--the people actually building the thing.
Access comes either from the project's Git repo, whose permissions are
mirrored, or from an invite link created on the project's collaboration
page.
An invite link can be scoped to read or write access, given an
expiration and a maximum number of uses, mailed to a specific address,
and revoked.
Redeeming one requires signing in, because being a collaborator means
having an identity in the project over time.

**Collab requests** are for everyone else, and for members whose
involvement in a particular piece of work should be bounded.
They don't imply membership, they don't require an account, and they
grant one specific ability against one specific artifact until they
expire.

The distinction matters because most people who touch a research project
aren't building it.
Making everyone a collaborator to get a co-author's comments is how you
end up with fifteen people who have write access to a repository and one
person who understands it.

The rest of this page is about requests.

## Reviewing a manuscript before you submit it

This is the case to get right.

A student has a draft that's nearly ready.
Before it goes anywhere it has to go around the team:
the PI reads it, two co-authors read the sections they contributed,
a labmate checks the figures.
Today that's a burst of email with attachments,
four differently-marked-up copies coming back over two weeks,
and a merge chore at the end that falls entirely on the student.

As collab requests it's one request per reviewer,
each pinned to the same revision, each scoped to the manuscript,
each with a due date you can see at a glance.
What comes back--tracked changes, PDF highlights, comments typed in the
hub--lands in one queue to work through, not four documents to
reconcile.

The part a shared document can't do is the checking.
A co-author who wants to know where the number in Table 2 came from can
follow it to the stage that computed it, read the code, and see the
inputs, because the manuscript and the pipeline that fed it are pinned
at the same revision.
Nobody has to assemble a package of supplementary material for their own
co-authors, because none of it was ever separated.

Review goes in **rounds**.
Sending v2 around after revisions is a new request at a new revision,
linked back to the one it supersedes,
so the history of a paper's internal review is one chain rather than a
folder of email threads.
A reviewer can also **decline** a request, with a reason, instead of it
sitting open until somebody chases it.

### When the journal's reviews come back

The reverse trip works the same way.
Reviews arriving from a journal are somebody else's marked-up document:
a PDF of reviewer comments, or a block of text in an editor's email.
Dropped into the project, they go through the same ingestion as a Word
document from your PI and come out as the same queue of individual
items, each one addressable, checkable, and linked to the revision it
was written about.

That's the immediate value, and it doesn't require any journal to change
anything.
Whether Calkit could eventually serve as the review system itself is a
much longer bet, and not one this feature is built on.

## Outbound and inbound requests

Requests go both ways.

An **outbound** request is a solicitation:
you're asking someone to review or contribute something.
This is the "send the manuscript to my PI" case,
and the one that has to be as close to frictionless as email.

An **inbound** request is a proposal:
someone is asking to contribute something to your project.
This is the gated equivalent of a pull request from a stranger, e.g.,
"can I tweak the hyperparameters for this stage?"
Inbound requests can stand alone,
or arrive as responses to an outbound one.

A project can also post a **public call for contributions**:
an open request anyone can answer,
optionally requiring the responder to confirm an email address first.

## Anatomy of a request

Every request names:

**A target.**
The whole project, or a specific artifact--a publication, a figure,
the full figure collection, a presentation, a dataset, a notebook--or a
pipeline stage.
Targets are artifacts, not file paths, because that's how researchers
talk about their own work.
Calkit resolves the artifact to the files behind it:
for a review of a paper, the target of any edits is the LaTeX source
that produces the PDF, not the PDF itself.

**A revision.**
The request is pinned to the commit it was created from,
so feedback stays attached to what the recipient actually saw,
even if the project moves on while they have it.

**What the responder may do.**
Most requests should be _suggest_:
the responder marks up the work without taking it over,
and you keep the pen.
That's the mode that removes the coordination email entirely,
because nothing has to be handed back before you can keep writing.

| Permission | What it allows                                          |
| ---------- | ------------------------------------------------------- |
| Review     | Read and comment or annotate. Nothing changes.          |
| Submit     | Upload files to one designated place, and nothing more. |
| Suggest    | Propose edits, accepted or rejected one by one.         |
| Edit       | Commit changes directly to the default branch.          |

**How sure we need to be about who they are.**

| Identity  | What it requires                                     |
| --------- | ---------------------------------------------------- |
| Anonymous | The link is the only credential.                     |
| Email     | The responder confirms an email address with a code. |
| Account   | The responder signs in to the hub.                   |

**An expiration**, and optionally a cap on how many responses it accepts.
Requests can also be closed or revoked at any time.

## Show people only what they need

A request doesn't hand someone the project.
It renders exactly the surface its scope implies, and nothing else.

A co-author asked to review Section 3 sees Section 3 and a way to mark it
up.
They don't see the pipeline, the environments, the data, or the other
twelve source files.
Someone contributing a chapter to a proceedings volume sees an upload
form and a confirm button--not a LaTeX project they have no business
touching and every ability to break.
Scoping this way is what makes it safe to send a request to a hundred
people at once,
and it's why the identity requirement can often stay low:
a link that can only do one narrow thing doesn't need to be defended
like a login.

To send the same ask to many people, e.g., every author in a volume,
give the hub the list of addresses and it creates one request per
recipient.
Each is tracked, chased, and revoked on its own,
so "who hasn't sent theirs in yet" is a column in a table rather than a
search through your sent mail.

## Sending a request

From the project's collaboration page,
or from an artifact's own page, e.g., the publication viewer,
choose the target, write the ask, pick the permission and identity
requirement, and enter the recipient's email address.

They receive an email with a link.
The link carries a token that identifies them,
scopes them to just this request,
and expires.
Following it drops them straight onto the response page--no sign-up,
no account, no repo.

<!-- prettier-ignore -->
!!! tip
    You can attach a file to a request, e.g., a Word version of the
    manuscript, and the recipient can send one back with tracked changes.
    That's the lowest-friction path of all for a collaborator who isn't
    going to leave their word processor,
    and it still lands attached to the pinned revision rather than in an
    inbox.

## Responding to a request

The response page shows what's being asked, the artifact as it stood at
the pinned revision, and a way to answer that matches the permission:
comments and annotations for a review,
an editor for suggestions or direct edits.
Work can be saved as a draft and submitted later.

A single request can collect several responses,
which is what makes public calls and team-wide asks work.
In practice, for a known set of collaborators,
it's usually better to send each person their own request
so they can be tracked and revoked independently.

## Marked-up documents become a task queue

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

## Working the queue as a board

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

## Working the queue without the hub

A hub is optional in Calkit, and this feature shouldn't be the exception.
If a student gets a marked-up `.docx` back from their advisor by email,
they should be able to turn it into a work queue on their own laptop,
in a project that was never pushed to a hub at all.

So the queue is **data in the repo**, not a row in somebody's database.
Ingestion is a local operation:

```sh
calkit review ingest advisor-review.docx
```

This reads the tracked changes and comments out of the document, matches
them against the project's source, and writes one item per change into
the repo, where they're committed alongside everything else.
From there the queue is worked through locally:

```sh
calkit review list
calkit review show 7
calkit review apply 7
calkit review start 7
calkit review done 7
```

`calkit review list` is the same board the hub renders, printed as
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
That decision stands on its own merits, and collab requests are built so
they don't depend on which way it goes:
GitHub issues and pull requests are mirrors here, pointed at by nullable
fields, never the place the data lives.

## Accepting contributions

Everything that comes back is **gated and atomic**.
A reviewer who suggests twenty changes to a paper doesn't force an
all-or-nothing decision:
the project lead takes the ones they want and declines the rest.
Accepted changes are squashed into a single commit that references the
request, so the project's main timeline stays clean and auditable.

For contributions that touch pipeline outputs,
Calkit can re-run the associated stage before the change is accepted,
verifying that the figure or dataset still renders cleanly from the
proposed inputs.
This is the step a code review can't do and a research review needs.
It's also what a reviewer wants for themselves:
checking that a result reproduces is the review, not a formality after
it.

## Avoiding conflicts

Two people changing the same artifact at once is a real problem,
but it's worth being precise about when it actually arises.
It doesn't arise for review or suggestion:
a suggestion is a proposal against a pinned revision,
so any number of people can mark up the same draft at the same time
while its author keeps writing.
Only requests that grant _edit_ can collide.

For those, the right answer depends on the artifact.

| Artifact type                        | Strategy                   |
| ------------------------------------ | -------------------------- |
| Notebooks, slides, heavy binary data | Lock while in use          |
| Papers, scripts, `calkit.yaml`       | Branch, then pick patches  |
| Pipeline outputs and figures         | Re-run the stage to verify |

**Locking** suits files where Git's diff and merge are useless anyway:
`.ipynb` notebooks, Word documents, slide decks, HDF5 data, raw figure
assets.
While an edit request holds a lock on one of these,
another edit request can't target it.
Review and suggestion requests are unaffected.

<!-- prettier-ignore -->
!!! warning
    Locking is the mechanism that most easily turns back into the thing
    this feature exists to eliminate.
    A lock that has to be requested and released by hand is just the
    "passing the pen" email with extra steps.
    Locks are therefore taken and released by the request itself, expire
    on their own, and can be force-released by project owners.
    Nobody should ever have to ask a person for one.

**Branching with selective patch acceptance** suits text.
Each response is staged on its own branch,
and the project lead chooses what to take from it.
Nothing about this is exposed to the responder--they see an editor and a
submit button, not a branch.

## Managing requests

The project's collaboration page lists collaborators and requests
together:
what's outstanding, who it went to, what's come back, and what's still
waiting on a decision.
From there, requests can be resent, extended, closed, or revoked.

If the project is connected to GitHub,
a request can be mirrored to an issue so repo watchers see the ask too,
and accepted contributions can be surfaced as pull requests.

<!-- prettier-ignore -->
!!! warning "Under construction"
    Collab requests are in design.
    The following are open and this page will be updated as they're
    settled:

    - Whether patch selection is presented hunk-by-hunk with checkboxes,
      or at the level of individual commits.
    - Whether queue items live as files in the working tree or in Git
      refs, e.g., `refs/calkit/collabs/`.
      Files are readable by anything and show up in `git log`; refs keep
      the working tree clean and are what git-bug already does.
      Both are cloneable and offline-first, which is the requirement.
    - Exactly which CLI commands exist and what they're called.
      The names above are a sketch, not a decision.
    - Whether the board generalizes to tasks that didn't come from a
      review.
      A project board wants "write the discussion section" on it too,
      and it would be a mistake to end up with two task systems that
      don't share a card.
    - Whether board columns are fixed or per-project.
    - Whether Calkit eventually hosts Git itself, with GitHub as one sync
      target rather than the substrate.
      Collab requests don't force that decision and don't depend on it,
      but they do make the case for it easier to see.
    - What the "submit" surface looks like for bulk asks, e.g., how
      uploaded files are validated and where they land in the repo.
    - How far document ingestion should go beyond `.docx`, e.g., PDF
      annotations exported from Acrobat or Preview, or an emailed reply
      quoting the text it's about.
    - How locks interact with editing outside the hub, e.g., in the VS
      Code extension or a local checkout.
    - Whether a reviewer can run pipeline stages themselves, and where.
      Verifying a result means executing it somewhere, which a review
      link can't do on its own.
    - Whether reviews ever need to be blinded.
      Nothing in internal pre-submission review does, so blinding isn't
      modeled; it only becomes a question if Calkit is ever used for
      external review.
