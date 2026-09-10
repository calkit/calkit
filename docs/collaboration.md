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

A **contribution request** is Calkit's answer.
It's a request for a specific contribution to a specific artifact,
sent to a specific person, with an explicit scope and deadline.
The recipient gets a link, does the work in the browser,
and sends it back.
The project lead decides what to accept.
Underneath it's still Git, so the provenance survives,
but nobody has to think about branches to participate.

<!-- prettier-ignore -->
!!! note
    Contribution requests are the research-native replacement for pull requests.
    A pull request asks "merge branch A into branch B."
    A contribution request asks "review Figure 2," "co-author Section 3," or
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

**Contribution requests** are for everyone else, and for members whose
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
What comes back from them is
[project management](project-management.md).

## Reviewing a manuscript before you submit it

This is the case to get right.

A student has a draft that's nearly ready.
Before it goes anywhere it has to go around the team:
the PI reads it, two co-authors read the sections they contributed,
a labmate checks the figures.
Today that's a burst of email with attachments,
four differently-marked-up copies coming back over two weeks,
and a merge chore at the end that falls entirely on the student.

As contribution requests it's one request per reviewer,
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

Requests go both ways, and the difference is simply who started it.

An **outbound** request is a solicitation:
you're asking someone to review or contribute something.
This is the "send the manuscript to my PI" case,
and the one that has to be as close to frictionless as email.
It's live the moment you create it, because the person creating it is the
person with the authority to grant it.

An **inbound** request is someone asking the project for something.
Mostly that means asking for the ability to do something they currently
can't:
a collaborator looking at a figure who wants to fix the axes,
or a reader who finds comments turned off on a paper and wants them.
It's the Request access button, and it grants nothing until a project
lead approves it.

<!-- prettier-ignore -->
!!! note
    The two converge the moment an inbound request is approved.
    An approved inbound request and an outbound one are the same object
    doing the same job--*this person may do this thing to this target
    until it expires*--which is why there's one kind of request rather
    than two.

Whether there's anything to ask for depends on a project setting.
By default anyone who can see a project can comment on it, because
feedback is the entire point.
A project that would rather keep comments to its members can say so, and
the comment box then becomes a request-to-comment button for everyone
else--an inbound request a lead can approve, rather than a dead end with
no way to reach anybody.

Approving doesn't have to mean granting what was asked.
A lead can hand back less:
someone who asked to edit a figure can be given suggest instead,
so their change arrives as a proposal rather than a commit.
Denying can carry a reason, which is worth doing--_"we don't take
outside edits on this"_ is a better answer than silence.

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

**What the other party may do.**
This is a ladder, and deliberately the one everybody already knows from
Google Drive and Docs.
A PI shouldn't have to learn a new sharing model to read their student's
paper.

| Permission | What it allows                                      |
| ---------- | --------------------------------------------------- |
| View       | Read the target at the pinned revision. That's all. |
| Comment    | Read and annotate. Nothing in the project changes.  |
| Suggest    | Propose edits, accepted or rejected one by one.     |
| Edit       | Commit changes directly to the default branch.      |

Most requests should be _suggest_:
the responder marks up the work without taking it over,
and you keep the pen.
That's the mode that removes the coordination email entirely,
because nothing has to be handed back before you can keep writing.

**Submit** is the exception, and isn't a rung on that ladder at all.
It grants upload to one designated place and no visibility into anything
else--which is precisely what the bulk case needs,
since a hundred authors each handing in a chapter shouldn't be able to
read each other's.

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

## Assembling something to send

Every week or two, a student pulls together a handful of figures into
slides for the group meeting or an advisor check-in.
It's the most common review cycle in research and the one that leaks the
most.
The deck gets built by hand:
export a figure, paste it into PowerPoint, retype the caption, notice the
numbers changed, redo it.
Convergence after a period of divergence, done by copy and paste.

Two things get lost every time.
The provenance goes first--once a plot is a picture in a slide, nothing
connects it to the code and data that made it,
and a question in the meeting about how it was computed can't be answered
from the deck.
Then the work goes:
next fortnight, the arranging and the commentary get done again from
scratch, because the deck was drawn rather than declared.

In Calkit a review deck is **declared, not drawn**.
You say which figures go in it, in what order, with what commentary,
and the deck is generated from the project's own
[pipeline](pipeline/index.md) outputs at a pinned revision--which makes it
a [presentation](calkit-yaml.md) artifact like any other, produced by a
stage, rebuildable on demand.

That changes both halves.
Regenerating next fortnight picks up current results while your ordering
and commentary survive, because those live in the declaration rather than
in a binary someone has to redo.
And every slide knows what it came from, so a comment on slide 4 resolves
to the figure on it, to the stage that produced that figure, and to the
data that stage consumed.

<!-- prettier-ignore -->
!!! note
    Rearranging and writing commentary is real work and shouldn't be
    automated away--the synthesis is the point of the exercise.
    What should be automated away is the copying, the retyping, and the
    silent staleness when a figure changes and the slide doesn't.

The deck is then just another target.
Send it for review, and comments come back as tasks that already know
which figure and which stage they're about,
rather than as "slide 4" in an email thread nobody can act on in a month.

## Meeting people where they are

The hardest constraint on this whole feature is that the most important
reviewer is the least likely to cooperate.
A PI who checks email and Slack and nothing else is not going to visit
calkit.io because a student asked them to,
and any design that requires it has already failed for the person whose
feedback matters most.

So the reviewer never has to.
An artifact arrives in their inbox or in a Slack thread.
They reply, in the client they already have open, in prose:

> Figure 3 should have log axes. The intro is about a page too long, and
> Table 2 is missing units.

That reply comes back to Calkit and becomes three
[tasks](project-management.md) on the student's board.
No account, no link, no login--the reviewer's half of this feature is
supposed to be invisible to them.

Each request carries its own reply address, so hitting **Reply** is the
whole interaction.
Attachments come along:
if the PI marked up the Word version instead of writing prose,
that gets [ingested](project-management.md#marked-up-documents-become-tasks)
the same way.
Slack works the same, with the thread mapped to the request, and a link
back to it kept on the response so the conversation stays where the team
already talks.

<!-- prettier-ignore -->
!!! warning
    A reply proves less about who sent it than a confirmed link does.
    From addresses can be forged, so an emailed response is only treated
    as verified when the message actually authenticates as the sender's
    domain.
    For a request that needs real certainty about identity, require an
    account and accept the friction--but that should be rare, and it's
    the wrong default for a PI.

Whatever channel it came in on, the response is pinned to the revision
the artifact was sent at.
That's the part that makes this more than a nicer inbox:
"Figure 3 should have log axes" is attached to a specific Figure 3,
produced by a specific pipeline stage, from specific data, at a specific
commit.
Six weeks later the student--or an agent working on their behalf--can
follow that comment back to exactly what produced the thing being
complained about.

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
    Contribution requests are in design.
    The following are open and this page will be updated as they're
    settled:

    - Whether "suggest" and "edit" are both offered at launch, or
      whether early versions stop at review and submission.
    - What the "submit" surface looks like for bulk asks, e.g., how
      uploaded files are validated and where they land in the repo.
    - Whether reviews ever need to be blinded.
      Nothing in internal pre-submission review does, so blinding isn't
      modeled; it only becomes a question if Calkit is ever used for
      external review.
    - How locks interact with editing outside the hub, e.g., in the VS
      Code extension or a local checkout.
    - Whether a reviewer can run pipeline stages themselves, and where.
      Verifying a result means executing it somewhere, which a review
      link can't do on its own.
    - How a reply email is split into individual tasks.
      "Figure 3 needs log axes, and the intro is too long" is two tasks,
      but prose doesn't come with delimiters, and getting this wrong in
      either direction is annoying.
    - Whether Slack support is a Calkit app a workspace installs, or a
      bot invited to a channel, and what it does with threads nobody
      asked it about.
    - Where a review deck's declaration lives, e.g., in `calkit.yaml`
      alongside other presentations, or in its own file next to the
      generated deck.
    - Whether Calkit eventually hosts Git itself, with GitHub as one
      sync target rather than the substrate.
      Contribution requests don't force that decision and don't depend
      on it, but they do make the case for it easier to see.
