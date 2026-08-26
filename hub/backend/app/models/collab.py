"""Collaboration request models.

A ``CollabRequest`` is an ask for a specific contribution to a specific
artifact -- a review of a paper at a given revision, edits to a figure, a
chapter uploaded to a proceedings volume -- addressed to a named recipient or
to anyone holding the link. It replaces the pull request for research work:
the framing is the deliverable, not the diff. Requests go both ways, outbound
(the lead solicits) and inbound (someone proposes).

Answers come back as ``CollabRequestResponse`` rows -- one request can collect
many -- each carrying zero or more ``CollabSuggestion`` items the lead accepts
or rejects one at a time.

The case this is built around is internal review of a manuscript before
submission -- the student sends the draft to their PI and co-authors -- which
is why a request carries rounds, due dates, and a per-response
recommendation. Because the manuscript, the figures, the pipeline that made
them, and the data are all pinned at one revision, a co-author can check a
number rather than take it on faith. Reviews arriving back from a journal are
ingested the same way, as somebody else's marked-up document.

A note on where the authority sits. Sending a request genuinely needs a hub:
something has to receive an email, host a link, and check a token, so
``CollabRequest`` and its access control live here. What comes back does not.
The queue of suggestions is meant to be materializable into the project's own
repo, so a student who was emailed a marked-up document can ingest it with
the CLI and work through it offline, in a project that never touched a hub.
These tables are then a view over that data plus the hub-only parts, not its
only home -- the same relationship the hub has to the rest of a Calkit
project.

Split out from ``core`` for locality, the same way ``releases`` is. The table
classes register into ``SQLModel.metadata`` at import time as long as this
module is imported from ``app.models`` (it is, via ``__init__``).
"""

import uuid
from datetime import datetime
from typing import Literal

import sqlalchemy
from pydantic import BaseModel, computed_field
from sqlmodel import Field, Relationship, SQLModel

from app import utcnow
from app.models.core import CommentHighlight, Project, User

# What the request points at. ``project`` is the whole thing; the rest name an
# artifact declared in calkit.yaml (or a bare repo path for ``path``),
# identified by ``target_path``. ``figures`` is the whole figures collection,
# ``figure`` a single one.
CollabTargetKind = Literal[
    "project",
    "publication",
    "figure",
    "figures",
    "presentation",
    "dataset",
    "notebook",
    "stage",
    "release",
    "path",
]

# What the responder may do:
#   ``review``  -- read and annotate only; nothing in the repo changes
#   ``submit``  -- upload files to the one place ``target_path`` names, and
#                  see nothing else; the bulk-contribution case, e.g., a
#                  hundred authors each handing in a chapter
#   ``suggest`` -- propose edits, which land as gated suggestions the lead
#                  accepts or rejects individually. The default: the
#                  responder marks up the work without taking custody of it,
#                  so nothing has to be handed back before the author can
#                  keep writing
#   ``edit``    -- commit directly to the project's default branch. The only
#                  permission that can collide with another responder, and so
#                  the only one locking applies to
CollabPermission = Literal["review", "submit", "suggest", "edit"]

# Which way the ask points. ``outbound`` is a solicitation the project lead
# sent ("please review this"); ``inbound`` is a proposal someone made to the
# project ("may I change this?"), which is the gated stand-in for a pull
# request from a stranger.
CollabDirection = Literal["outbound", "inbound"]

# How sure we need to be about who is responding:
#   ``anonymous`` -- the link is the only credential
#   ``email``     -- the responder proves control of an address, either the one
#                    the link was mailed to or one they enter and confirm with
#                    a code
#   ``account``   -- a signed-in Calkit user is required
CollabIdentityRequirement = Literal["anonymous", "email", "account"]


# A reviewer's verdict on the work, kept separate from the lead's verdict on
# the response. A recommendation is an opinion the requester weighs ("this
# isn't ready to submit"); the response status is what the requester decided.
CollabRecommendation = Literal[
    "accept",
    "minor_revision",
    "major_revision",
    "reject",
]

# A response is ``draft`` while the responder is still working, ``submitted``
# once handed back, then ``accepted``/``rejected`` by the lead. The per-item
# verdicts live on the suggestions -- a response can be accepted as a whole
# with only some of its suggestions taken.
CollabResponseStatus = Literal[
    "draft",
    "declined",
    "submitted",
    "accepted",
    "rejected",
]

CollabSuggestionStatus = Literal["pending", "accepted", "rejected"]

# How a suggestion locates what it changes. ``text`` carries an original and a
# replacement string, ``highlight`` pins to a PDF region (the
# react-pdf-highlighter anchor releases and project comments already use), and
# ``note`` is a comment with no proposed edit.
CollabSuggestionKind = Literal["text", "highlight", "note"]

# Where a suggestion came from. Ingested sources matter because they carry
# different confidence: something typed into the hub knows exactly what it's
# attached to, while a tracked change lifted out of a Word document had to be
# matched back to the source it was generated from.
CollabSuggestionSource = Literal["manual", "docx", "pdf", "email"]

# Whether an ingested suggestion could be located in the project's source.
#   ``resolved``   -- matched a unique spot; accepting can write it directly
#   ``ambiguous``  -- the context matched more than one place
#   ``unresolved`` -- no match, e.g., structural edits or rewritten equations
# Anything but ``resolved`` still belongs in the queue -- it just needs a
# human to place it, which is the honest outcome for a good fraction of a
# heavily marked-up document.
CollabAnchorStatus = Literal["resolved", "ambiguous", "unresolved"]

# Where an item sits on the board, which is a different question from
# ``CollabSuggestionStatus``. That one is a verdict -- do we agree with this
# feedback? This one is progress -- have we done it yet? A one-line typo fix
# collapses both into a single click, but "redo Figure 3 with log axes" is a
# week of work that's agreed to long before it's finished, and there's nowhere
# to put it if the only states are pending, accepted, and rejected.
CollabTaskStatus = Literal["todo", "in_progress", "blocked", "done"]


class CollabRequest(SQLModel, table=True):
    """A request for a specific contribution, sent out by a project lead.

    Access is by unguessable link: only the SHA-256 ``token_hash`` is stored,
    so a database leak can't be turned into working links, and the raw token
    is shown to the creator once at mint time. Tokens are high-entropy, so a
    plain (fast) hash keeps the lookup an indexed equality check, matching
    ``ReleaseShareToken`` and ``ProjectInvitation``.

    ``email`` names the intended recipient; a request with ``public`` set is an
    open call listed on the project page that anyone may answer.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)
    created_by_user_id: uuid.UUID = Field(foreign_key="user.id")
    token_hash: str = Field(index=True, unique=True, max_length=64)
    # Short label shown in the requests table and used as the email subject.
    title: str = Field(min_length=1, max_length=255)
    # The ask itself, in the requester's words; goes into the email body.
    message: str | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.Text)
    )
    direction: str = Field(default="outbound", max_length=16)
    # An inbound request raised in answer to an outbound one, e.g., a reviewer
    # who was asked to comment proposes a concrete change instead. Null for a
    # request that stands on its own.
    in_response_to_request_id: uuid.UUID | None = Field(
        default=None, foreign_key="collabrequest.id"
    )
    target_kind: str = Field(default="project", max_length=32)
    # Path to the targeted artifact, or None/"." for the whole project.
    target_path: str | None = Field(default=None, max_length=512)
    # The revision being asked about, pinned at creation so feedback stays
    # attached to what the recipient actually saw. ``git_ref`` is the
    # human-readable ref it was cut from.
    git_ref: str | None = Field(default=None, max_length=256)
    git_rev: str | None = Field(default=None, max_length=40)
    permission: str = Field(default="suggest", max_length=16)
    identity_requirement: str = Field(default="anonymous", max_length=16)
    # Soft deadline, shown to the responder and used for reminders. Distinct
    # from ``expires_at``, which actually kills the link: a review that's two
    # days late should still be submittable.
    due_at: datetime | None = Field(default=None)
    # Review round, and the request this one supersedes. A revise-and-resubmit
    # is a new request at a new revision chained to the previous one, so a
    # publication's whole review history is one walk back through this link.
    round: int = Field(default=1, ge=1)
    supersedes_request_id: uuid.UUID | None = Field(
        default=None, foreign_key="collabrequest.id"
    )
    # Intended recipient; None means "whoever has the link".
    email: str | None = Field(default=None, max_length=320)
    # Display name for the recipient, so the UI can say "Review from Jane Doe"
    # before they've ever responded.
    recipient_name: str | None = Field(default=None, max_length=255)
    # An open call for contributions: listed on the project page, answerable
    # without a token. Targeted requests leave this False.
    public: bool = Field(default=False)
    expires_at: datetime | None = Field(default=None)
    # Cap on submitted responses; None means unlimited. Useful for an open
    # call that should stop accepting once it has what it needs.
    max_responses: int | None = Field(default=None)
    closed_at: datetime | None = Field(default=None)
    revoked: bool = Field(default=False)
    # The GitHub issue this request is mirrored to, if the project is
    # connected to GitHub, so the ask is visible to repo watchers too.
    github_issue_url: str | None = Field(default=None, max_length=2048)
    view_count: int = Field(default=0)
    created: datetime = Field(default_factory=utcnow)
    # Relationships
    project: Project = Relationship(back_populates="collab_requests")
    in_response_to: "CollabRequest | None" = Relationship(
        sa_relationship_kwargs=dict(
            remote_side="CollabRequest.id",
            foreign_keys="[CollabRequest.in_response_to_request_id]",
        )
    )
    supersedes: "CollabRequest | None" = Relationship(
        sa_relationship_kwargs=dict(
            remote_side="CollabRequest.id",
            foreign_keys="[CollabRequest.supersedes_request_id]",
        )
    )
    created_by: User = Relationship()
    responses: list["CollabRequestResponse"] = Relationship(
        back_populates="request", cascade_delete=True
    )
    attachments: list["CollabAttachment"] = Relationship(
        back_populates="request", cascade_delete=True
    )

    @computed_field
    @property
    def response_count(self) -> int:
        return sum(1 for r in self.responses if r.status != "draft")

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at < utcnow()

    @property
    def is_open(self) -> bool:
        """Whether the request can still take a new response."""
        if self.revoked or self.closed_at is not None or self.is_expired:
            return False
        if (
            self.max_responses is not None
            and self.response_count >= self.max_responses
        ):
            return False
        return True


class CollabRequestResponse(SQLModel, table=True):
    """One party's answer to a collaboration request.

    A request is one-to-many with responses so a public or team-wide ask can
    collect several. The responder is a signed-in user (``user_id``) or an
    email-scoped visitor; ``email_verified`` records whether the address was
    actually confirmed, since an address carried in a share link is
    attribution only.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    request_id: uuid.UUID = Field(
        foreign_key="collabrequest.id", index=True, ondelete="CASCADE"
    )
    # Set when the responder was signed in; None for link-scoped visitors.
    user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id")
    responder_name: str | None = Field(default=None, max_length=255)
    responder_email: str | None = Field(default=None, max_length=320)
    # True only when the address was confirmed with a code, or came from the
    # signed-in user's verified account.
    email_verified: bool = Field(default=False)
    status: str = Field(default="draft", max_length=16)
    # Why an invited responder turned the request down, if they said.
    decline_reason: str | None = Field(default=None, max_length=1024)
    # The reviewer's verdict on the work itself, e.g., "minor_revision".
    recommendation: str | None = Field(default=None, max_length=32)
    # The responder's cover note, e.g., "looks good apart from section 3".
    message: str | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.Text)
    )
    # Comments for the requester's eyes only, e.g., a co-author telling the
    # corresponding author something they don't want in front of the whole
    # team. Never shown to other responders, so it must not be folded into
    # ``message``.
    confidential_note: str | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.Text)
    )
    # The revision the response was written against, copied from the request
    # so a later re-pin doesn't silently re-target the feedback.
    git_rev: str | None = Field(default=None, max_length=40)
    # Where accepted suggestions were staged, once any were applied: a branch
    # in the project repo and, if the project is on GitHub, its pull request.
    branch_name: str | None = Field(default=None, max_length=256)
    github_pr_url: str | None = Field(default=None, max_length=2048)
    submitted_at: datetime | None = Field(default=None)
    # The lead's verdict on the response as a whole.
    reviewed_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id"
    )
    reviewed_at: datetime | None = Field(default=None)
    review_note: str | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.Text)
    )
    created: datetime = Field(default_factory=utcnow)
    # Relationships (user_id disambiguated from the reviewed_by_user_id FK)
    request: CollabRequest = Relationship(back_populates="responses")
    user: User | None = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[CollabRequestResponse.user_id]"
        }
    )
    suggestions: list["CollabSuggestion"] = Relationship(
        back_populates="response", cascade_delete=True
    )
    attachments: list["CollabAttachment"] = Relationship(
        back_populates="response", cascade_delete=True
    )

    @computed_field
    @property
    def suggestion_count(self) -> int:
        return len(self.suggestions)

    @computed_field
    @property
    def accepted_count(self) -> int:
        return sum(1 for s in self.suggestions if s.status == "accepted")


class CollabSuggestion(SQLModel, table=True):
    """One atomic proposed change (or plain note) inside a response.

    Suggestions are the unit the lead accepts or rejects, so a reviewer's
    twenty edits to a paper don't have to be taken or dropped as a block.
    Accepting is what turns a suggestion into a commit; ``applied_git_rev``
    records where it landed.

    They're also the queue a marked-up document is turned into. Tracked
    changes and comments in a ``.docx`` are structured records, not prose, so
    each becomes one row here with its own anchor and verdict -- the same
    shape as a comment typed into the hub, arriving by a different road. The
    grad student works the list one item at a time instead of hunting a
    document for what changed.

    This is the part that has to work without a hub, so the fields here are
    deliberately a superset of what a repo-native queue item needs: ingesting
    a document with the CLI and syncing the result up should be a
    serialization, not a translation.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    response_id: uuid.UUID = Field(
        foreign_key="collabrequestresponse.id",
        index=True,
        ondelete="CASCADE",
    )
    kind: str = Field(default="text", max_length=16)
    # Repo path the change applies to. For a paper this is the source the
    # target is built from (e.g., the .tex), not the rendered PDF.
    path: str | None = Field(default=None, max_length=512)
    # For ``text``: the exact string being replaced and what to replace it
    # with. Kept verbatim rather than as a diff so acceptance can verify the
    # original still matches before writing.
    original_text: str | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.Text)
    )
    suggested_text: str | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.Text)
    )
    # For ``highlight``: a react-pdf-highlighter anchor, the same shape
    # ProjectComment.highlight and ReleaseComment.highlight use. Stored as a
    # plain dict; CommentHighlight validates it on the way in.
    highlight: dict | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.JSON)
    )
    # The reviewer's rationale, and the only content for a ``note``.
    comment: str | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.Text)
    )
    source: str = Field(default="manual", max_length=16)
    # The file this was extracted from, for provenance: "comment 12 of
    # advisor-review.docx" rather than a free-floating suggestion.
    attachment_id: uuid.UUID | None = Field(
        default=None, foreign_key="collabattachment.id"
    )
    anchor_status: str = Field(default="resolved", max_length=16)
    # Text surrounding the change in the document it was extracted from, kept
    # so an ambiguous or unresolved item can still be placed by a person (or
    # re-matched later, after the source has moved on).
    context_before: str | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.Text)
    )
    context_after: str | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.Text)
    )
    status: str = Field(default="pending", max_length=16)
    # Board state, assignee, and ordering. Set when an item is accepted:
    # anything that could be applied automatically lands in ``done``, while
    # anything needing real work lands in ``todo`` for someone to pick up.
    task_status: str = Field(default="todo", max_length=16, index=True)
    assigned_to_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id"
    )
    # Position within its column. A float so a card can be dropped between two
    # others without renumbering the rest of the column.
    board_position: float = Field(default=0.0)
    # The GitHub issue this item was mirrored to, so the queue can be worked
    # through alongside the rest of the project's issues.
    github_issue_url: str | None = Field(default=None, max_length=2048)
    decided_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id"
    )
    decided_at: datetime | None = Field(default=None)
    # Set once an accepted suggestion has actually been written to the repo.
    applied_git_rev: str | None = Field(default=None, max_length=40)
    created: datetime = Field(default_factory=utcnow)
    # Relationships
    response: CollabRequestResponse = Relationship(
        back_populates="suggestions"
    )


class CollabAttachment(SQLModel, table=True):
    """A file sent with a request or handed back with a response.

    The round trip a PI actually wants: mail out the manuscript as a Word
    document, get it back with tracked changes. Exactly one of ``request_id``
    and ``response_id`` is set. The bytes live in object storage under
    ``storage_key``; only the metadata is in the database.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    request_id: uuid.UUID | None = Field(
        default=None, foreign_key="collabrequest.id", ondelete="CASCADE"
    )
    response_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="collabrequestresponse.id",
        ondelete="CASCADE",
    )
    filename: str = Field(max_length=512)
    content_type: str | None = Field(default=None, max_length=255)
    size_bytes: int | None = Field(default=None)
    storage_key: str = Field(max_length=1024)
    uploaded_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id"
    )
    created: datetime = Field(default_factory=utcnow)
    # Relationships
    request: CollabRequest | None = Relationship(back_populates="attachments")
    response: CollabRequestResponse | None = Relationship(
        back_populates="attachments"
    )


class CollabRequestPost(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    message: str | None = None
    direction: CollabDirection = "outbound"
    in_response_to_request_id: uuid.UUID | None = None
    target_kind: CollabTargetKind = "project"
    target_path: str | None = None
    # If None, the project's default branch HEAD is pinned at creation.
    git_ref: str | None = None
    permission: CollabPermission = "suggest"
    identity_requirement: CollabIdentityRequirement = "anonymous"
    due_at: datetime | None = None
    # Set to chain a new review round onto a previous request; the round
    # number is derived from it.
    supersedes_request_id: uuid.UUID | None = None
    email: str | None = None
    recipient_name: str | None = None
    public: bool = False
    expires_days: int | None = Field(default=None, ge=1, le=365)
    max_responses: int | None = Field(default=None, ge=1)
    # Mirror the ask to a GitHub issue on the project's repo.
    create_github_issue: bool = False


class CollabRequestPatch(SQLModel):
    """Fields a lead may change after a request has gone out.

    Deliberately narrow: the target, revision, and permission are what the
    recipient was told they were looking at, so changing them would
    retroactively rewrite the ask.
    """

    title: str | None = None
    message: str | None = None
    due_at: datetime | None = None
    expires_at: datetime | None = None
    max_responses: int | None = Field(default=None, ge=1)
    closed: bool | None = None
    revoked: bool | None = None


class CollabRequestPublic(SQLModel):
    """A request as the project lead sees it -- never includes the token."""

    id: uuid.UUID
    title: str
    message: str | None
    direction: str
    in_response_to_request_id: uuid.UUID | None
    target_kind: str
    target_path: str | None
    git_ref: str | None
    git_rev: str | None
    permission: str
    identity_requirement: str
    due_at: datetime | None
    round: int
    supersedes_request_id: uuid.UUID | None
    email: str | None
    recipient_name: str | None
    public: bool
    expires_at: datetime | None
    max_responses: int | None
    response_count: int
    closed_at: datetime | None
    revoked: bool
    github_issue_url: str | None
    view_count: int
    created: datetime


class CollabRequestCreated(CollabRequestPublic):
    """Returned once at mint time; carries the raw token and its link."""

    token: str
    url: str
    # Whether the request email actually went out. False when there was no
    # recipient, email isn't configured, or sending failed -- the caller then
    # falls back to copying the link.
    email_sent: bool = False


class CollabRequestView(SQLModel):
    """A request as the responder sees it on the respond page.

    Omits internal identifiers and the requester's private metadata; exposes
    what's needed to render the ask, the target, and the response form.
    ``can_respond`` folds together expiry, closure, and the response cap so
    the page doesn't have to re-derive them.
    """

    title: str
    message: str | None
    direction: str
    target_kind: str
    target_path: str | None
    git_ref: str | None
    git_rev_abbrev: str | None
    permission: str
    identity_requirement: str
    due_at: datetime | None
    round: int
    expires_at: datetime | None
    created: datetime
    owner_account_name: str
    owner_account_display_name: str
    project_name: str
    project_title: str
    requester_name: str
    # Prefill/attribution for a link-scoped responder.
    responder_email: str | None = None
    # Whether the identity requirement has already been met by this caller.
    identity_confirmed: bool = False
    can_respond: bool = True


class CollabSuggestionPost(SQLModel):
    kind: CollabSuggestionKind = "text"
    source: CollabSuggestionSource = "manual"
    path: str | None = None
    original_text: str | None = None
    suggested_text: str | None = None
    highlight: CommentHighlight | None = None
    comment: str | None = None


class CollabResponsePost(SQLModel):
    message: str | None = None
    confidential_note: str | None = None
    recommendation: CollabRecommendation | None = None
    responder_name: str | None = None
    responder_email: str | None = None
    suggestions: list[CollabSuggestionPost] = Field(default_factory=list)
    # False saves a draft the responder can come back to; True hands it in.
    submit: bool = True


class CollabSuggestionPublic(SQLModel):
    id: uuid.UUID
    kind: str
    source: str
    anchor_status: str
    attachment_id: uuid.UUID | None
    github_issue_url: str | None
    task_status: str
    assigned_to_user_id: uuid.UUID | None
    board_position: float
    context_before: str | None
    context_after: str | None
    path: str | None
    original_text: str | None
    suggested_text: str | None
    highlight: dict | None
    comment: str | None
    status: str
    decided_at: datetime | None
    applied_git_rev: str | None
    created: datetime


class CollabAttachmentPublic(SQLModel):
    id: uuid.UUID
    filename: str
    content_type: str | None
    size_bytes: int | None
    created: datetime


class CollabResponsePublic(SQLModel):
    id: uuid.UUID
    request_id: uuid.UUID
    responder_name: str | None
    responder_email: str | None
    email_verified: bool
    status: str
    decline_reason: str | None
    recommendation: str | None
    message: str | None
    # Only populated for the requester; omitted from anything an author sees.
    confidential_note: str | None = None
    git_rev: str | None
    branch_name: str | None
    github_pr_url: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    review_note: str | None
    suggestion_count: int
    accepted_count: int
    created: datetime
    suggestions: list[CollabSuggestionPublic] = Field(default_factory=list)
    attachments: list[CollabAttachmentPublic] = Field(default_factory=list)


class CollabResponseDeclinePost(SQLModel):
    """An invited responder turning the request down."""

    reason: str | None = None


class CollabResponseReviewPost(SQLModel):
    """The lead's verdict on a whole response."""

    status: Literal["accepted", "rejected"]
    review_note: str | None = None


class CollabSuggestionBoardPatch(SQLModel):
    """Move a card: change its column, assignee, or position within a column.

    Separate from the accept/reject decision on purpose -- dragging a card to
    "in progress" says nothing about whether the suggestion was agreed with,
    and agreeing with it says nothing about whether it's been done.
    """

    task_status: CollabTaskStatus | None = None
    assigned_to_user_id: uuid.UUID | None = None
    board_position: float | None = None


class CollabSuggestionDecisionPost(SQLModel):
    """Accept or reject a single suggestion."""

    status: Literal["accepted", "rejected", "pending"]


class CollabIdentityChallengePost(BaseModel):
    """Start email confirmation for a request that requires it."""

    email: str


class CollabIdentityConfirmPost(BaseModel):
    email: str
    code: str
