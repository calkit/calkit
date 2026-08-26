"""Contriboration request models.

A ``ContribRequest`` is an ask for a specific contribution to a specific
artifact -- a review of a paper at a given revision, edits to a figure, a
chapter uploaded to a proceedings volume -- addressed to a named recipient or
to anyone holding the link. It replaces the pull request for research work:
the framing is the deliverable, not the diff. Requests go both ways, outbound
(the lead solicits) and inbound (someone proposes).

Answers come back as ``ContribRequestResponse`` rows -- one request can collect
many -- each carrying zero or more ``ContribSuggestion`` items the lead accepts
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
``ContribRequest`` and its access control live here. What comes back does not.
The board of tasks is meant to be materializable into the project's own
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
from app.models.core import Project, User

# tasks imports back from here only under TYPE_CHECKING, so importing it at
# runtime is safe -- and necessary: TaskPost and TaskPublic are plain pydantic
# fields on the response schemas below, and a forward reference to a name
# that's only visible to type checkers would never resolve.
from app.models.tasks import Task, TaskPost, TaskPublic  # noqa: E402

# What the request points at. ``project`` is the whole thing; the rest name an
# artifact declared in calkit.yaml (or a bare repo path for ``path``),
# identified by ``target_path``. ``figures`` is the whole figures collection,
# ``figure`` a single one.
ContribTargetKind = Literal[
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
#   ``suggest`` -- propose edits, which land as gated tasks the lead
#                  accepts or rejects individually. The default: the
#                  responder marks up the work without taking custody of it,
#                  so nothing has to be handed back before the author can
#                  keep writing
#   ``edit``    -- commit directly to the project's default branch. The only
#                  permission that can collide with another responder, and so
#                  the only one locking applies to
ContribPermission = Literal["review", "submit", "suggest", "edit"]

# Which way the ask points. ``outbound`` is a solicitation the project lead
# sent ("please review this"); ``inbound`` is a proposal someone made to the
# project ("may I change this?"), which is the gated stand-in for a pull
# request from a stranger.
ContribDirection = Literal["outbound", "inbound"]

# How sure we need to be about who is responding:
#   ``anonymous`` -- the link is the only credential
#   ``email``     -- the responder proves control of an address, either the one
#                    the link was mailed to or one they enter and confirm with
#                    a code
#   ``account``   -- a signed-in Calkit user is required
ContribIdentityRequirement = Literal["anonymous", "email", "account"]


# A reviewer's verdict on the work, kept separate from the lead's verdict on
# the response. A recommendation is an opinion the requester weighs ("this
# isn't ready to submit"); the response status is what the requester decided.
ContribRecommendation = Literal[
    "accept",
    "minor_revision",
    "major_revision",
    "reject",
]

# A response is ``draft`` while the responder is still working, ``submitted``
# once handed back, then ``accepted``/``rejected`` by the lead. The per-item
# verdicts live on the individual tasks -- a response can be accepted as a
# whole with only some of its proposed changes taken.
ContribResponseStatus = Literal[
    "draft",
    "declined",
    "submitted",
    "accepted",
    "rejected",
]


class ContribRequest(SQLModel, table=True):
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
        default=None, foreign_key="contribrequest.id"
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
        default=None, foreign_key="contribrequest.id"
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
    project: Project = Relationship(back_populates="contrib_requests")
    in_response_to: "ContribRequest | None" = Relationship(
        sa_relationship_kwargs=dict(
            remote_side="ContribRequest.id",
            foreign_keys="[ContribRequest.in_response_to_request_id]",
        )
    )
    supersedes: "ContribRequest | None" = Relationship(
        sa_relationship_kwargs=dict(
            remote_side="ContribRequest.id",
            foreign_keys="[ContribRequest.supersedes_request_id]",
        )
    )
    created_by: User = Relationship()
    responses: list["ContribRequestResponse"] = Relationship(
        back_populates="request", cascade_delete=True
    )
    attachments: list["ContribAttachment"] = Relationship(
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


class ContribRequestResponse(SQLModel, table=True):
    """One party's answer to a contribution request.

    A request is one-to-many with responses so a public or team-wide ask can
    collect several. The responder is a signed-in user (``user_id``) or an
    email-scoped visitor; ``email_verified`` records whether the address was
    actually confirmed, since an address carried in a share link is
    attribution only.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    request_id: uuid.UUID = Field(
        foreign_key="contribrequest.id", index=True, ondelete="CASCADE"
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
    # Where accepted changes were staged, once any were applied: a branch
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
    request: ContribRequest = Relationship(back_populates="responses")
    user: User | None = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[ContribRequestResponse.user_id]"
        }
    )
    tasks: list[Task] = Relationship(
        back_populates="response", cascade_delete=True
    )
    attachments: list["ContribAttachment"] = Relationship(
        back_populates="response", cascade_delete=True
    )

    @computed_field
    @property
    def task_count(self) -> int:
        return len(self.tasks)

    @computed_field
    @property
    def accepted_count(self) -> int:
        return sum(1 for t in self.tasks if t.verdict == "accepted")


class ContribAttachment(SQLModel, table=True):
    """A file sent with a request or handed back with a response.

    The round trip a PI actually wants: mail out the manuscript as a Word
    document, get it back with tracked changes. Exactly one of ``request_id``
    and ``response_id`` is set. The bytes live in object storage under
    ``storage_key``; only the metadata is in the database.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    request_id: uuid.UUID | None = Field(
        default=None, foreign_key="contribrequest.id", ondelete="CASCADE"
    )
    response_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="contribrequestresponse.id",
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
    request: ContribRequest | None = Relationship(back_populates="attachments")
    response: ContribRequestResponse | None = Relationship(
        back_populates="attachments"
    )


class ContribRequestPost(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    message: str | None = None
    direction: ContribDirection = "outbound"
    in_response_to_request_id: uuid.UUID | None = None
    target_kind: ContribTargetKind = "project"
    target_path: str | None = None
    # If None, the project's default branch HEAD is pinned at creation.
    git_ref: str | None = None
    permission: ContribPermission = "suggest"
    identity_requirement: ContribIdentityRequirement = "anonymous"
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


class ContribRequestPatch(SQLModel):
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


class ContribRequestPublic(SQLModel):
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


class ContribRequestCreated(ContribRequestPublic):
    """Returned once at mint time; carries the raw token and its link."""

    token: str
    url: str
    # Whether the request email actually went out. False when there was no
    # recipient, email isn't configured, or sending failed -- the caller then
    # falls back to copying the link.
    email_sent: bool = False


class ContribRequestView(SQLModel):
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


class ContribResponsePost(SQLModel):
    message: str | None = None
    confidential_note: str | None = None
    recommendation: ContribRecommendation | None = None
    responder_name: str | None = None
    responder_email: str | None = None
    tasks: list[TaskPost] = Field(default_factory=list)
    # False saves a draft the responder can come back to; True hands it in.
    submit: bool = True


class ContribAttachmentPublic(SQLModel):
    id: uuid.UUID
    filename: str
    content_type: str | None
    size_bytes: int | None
    created: datetime


class ContribResponsePublic(SQLModel):
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
    task_count: int
    accepted_count: int
    created: datetime
    tasks: list[TaskPublic] = Field(default_factory=list)
    attachments: list[ContribAttachmentPublic] = Field(default_factory=list)


class ContribResponseDeclinePost(SQLModel):
    """An invited responder turning the request down."""

    reason: str | None = None


class ContribResponseReviewPost(SQLModel):
    """The lead's verdict on a whole response."""

    status: Literal["accepted", "rejected"]
    review_note: str | None = None


class ContribIdentityChallengePost(BaseModel):
    """Start email confirmation for a request that requires it."""

    email: str


class ContribIdentityConfirmPost(BaseModel):
    email: str
    code: str
