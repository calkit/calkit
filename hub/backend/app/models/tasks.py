"""Project management: tasks and the board they're worked on.

A ``Task`` is one unit of *human* work on a project's board. Most of them
arrive as feedback -- a comment from a reviewer, a tracked change lifted out
of a Word document, a highlight on a PDF -- but a task doesn't need an
origin. "Write the discussion section" is the same kind of card as "reviewer
2 wants the axes logarithmic", and putting them on two different boards would
guarantee neither is the one people actually use.

Not to be confused with a unit of computation: pipeline work is a *stage*,
and scheduled work in ``calkit.ops`` should be named to match rather than
borrowing "task" back.

Two independent axes, which is the thing worth getting right:

``status``
    Progress. Where the card sits on the board: to do, in progress, blocked,
    done. Always meaningful.
``verdict``
    Agreement. Whether proposed feedback was accepted or rejected. Only
    meaningful for a task that came from someone else's suggestion; None for
    one the team wrote for itself.

A one-line typo fix collapses both into a single click. "Redo Figure 3 with
log axes and rerun the sweep" is agreed to weeks before it's finished, and
there's nowhere to put that interval if a queue only knows accepted and
rejected.

Because this has to work without a hub -- a student ingesting a marked-up
document with the CLI, offline -- the fields here are deliberately a superset
of what a repo-native item needs, so syncing up is a serialization rather
than a translation.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Literal

import sqlalchemy
from pydantic import computed_field
from sqlmodel import Field, Relationship, SQLModel

from app import utcnow
from app.models.core import CommentHighlight, Project, User

if TYPE_CHECKING:
    # ContribRequestResponse lives in app.models.contrib, which imports back
    # from here; the guarded import resolves the forward reference without a
    # runtime cycle.
    from app.models.contrib import ContribRequestResponse

# What payload the item carries.
#   ``edit``      -- an original string and its proposed replacement
#   ``highlight`` -- a react-pdf-highlighter anchor into a PDF
#   ``note``      -- words only, which is what a plain task is
TaskKind = Literal["edit", "highlight", "note"]

# Where the item came from. Ingested sources matter because they carry
# different confidence: something written in the app knows exactly what it's
# attached to, while a tracked change lifted out of a Word document had to be
# matched back to the source that document was generated from.
TaskSource = Literal["manual", "docx", "pdf", "email"]

# Whether an ingested item could be located in the project's source.
#   ``resolved``   -- matched a unique spot; accepting can write it directly
#   ``ambiguous``  -- the context matched more than one place
#   ``unresolved`` -- no match, e.g., structural edits or rewritten equations
# Anything but ``resolved`` still belongs on the board -- it just needs a
# person to place it, which is the honest outcome for a good fraction of a
# heavily marked-up document.
TaskAnchorStatus = Literal["resolved", "ambiguous", "unresolved"]

# Progress: which column the card is in.
TaskStatus = Literal["todo", "in_progress", "blocked", "done"]

# Agreement, for items that came from someone else's proposal. Rejecting sets
# the verdict and moves the card to ``done``: it's off the board either way,
# and the verdict is what says whether it was carried out or declined.
TaskVerdict = Literal["pending", "accepted", "rejected"]


class Task(SQLModel, table=True):
    """One card on a project's board."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # Always set. A task belongs to a project whether or not it came from a
    # contribution, so the board can be queried without walking a response.
    project_id: uuid.UUID = Field(foreign_key="project.id", index=True)
    # The contribution response this came in on, if any. None for a task the
    # team wrote itself.
    response_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="contribrequestresponse.id",
        index=True,
        ondelete="CASCADE",
    )
    # Short label for the card. Derived from the comment or the change when
    # the item was ingested rather than typed.
    title: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="note", max_length=16)
    # Repo path the item applies to. For a paper this is the source the target
    # is built from (e.g., the .tex), not the rendered PDF.
    path: str | None = Field(default=None, max_length=512)
    # For ``edit``: the exact string being replaced and what to replace it
    # with. Kept verbatim rather than as a diff so accepting can verify the
    # original still matches before writing.
    original_text: str | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.Text)
    )
    suggested_text: str | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.Text)
    )
    # For ``highlight``: the same anchor shape ProjectComment.highlight and
    # ReleaseComment.highlight use. Stored as a plain dict; CommentHighlight
    # validates it on the way in.
    highlight: dict | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.JSON)
    )
    # The body: a reviewer's rationale, or the whole content of a plain note.
    body: str | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.Text)
    )
    source: str = Field(default="manual", max_length=16)
    # The file this was extracted from, for provenance: "comment 12 of
    # advisor-review.docx" rather than a free-floating item.
    attachment_id: uuid.UUID | None = Field(
        default=None, foreign_key="contribattachment.id"
    )
    anchor_status: str = Field(default="resolved", max_length=16)
    # Text surrounding the change in the document it came from, kept so an
    # ambiguous or unresolved item can still be placed by a person, or
    # re-matched later after the source has moved on.
    context_before: str | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.Text)
    )
    context_after: str | None = Field(
        default=None, sa_column=sqlalchemy.Column(sqlalchemy.Text)
    )
    # Progress. Ingested items that could be applied automatically are put
    # straight into ``done`` on acceptance; everything else lands in ``todo``.
    status: str = Field(default="todo", max_length=16, index=True)
    # Agreement, for items proposed by someone else. None when the team wrote
    # this itself, since there's nothing to agree with.
    verdict: str | None = Field(default=None, max_length=16)
    assigned_to_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id"
    )
    # Position within its column. A float so a card can be dropped between two
    # others without renumbering the rest of the column.
    board_position: float = Field(default=0.0)
    due: datetime | None = Field(default=None)
    # The GitHub issue this was mirrored to, so the board can be worked
    # alongside the rest of the project's issues.
    github_issue_url: str | None = Field(default=None, max_length=2048)
    created_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id"
    )
    decided_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id"
    )
    decided_at: datetime | None = Field(default=None)
    # Set once an accepted edit has actually been written to the repo.
    applied_git_rev: str | None = Field(default=None, max_length=40)
    created: datetime = Field(default_factory=utcnow)
    # Relationships (the three user FKs have to be disambiguated)
    project: Project = Relationship(back_populates="tasks")
    response: "ContribRequestResponse | None" = Relationship(
        back_populates="tasks"
    )
    assigned_to: User | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Task.assigned_to_user_id]"}
    )

    @computed_field
    @property
    def from_contribution(self) -> bool:
        return self.response_id is not None


class TaskPost(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    kind: TaskKind = "note"
    source: TaskSource = "manual"
    path: str | None = None
    original_text: str | None = None
    suggested_text: str | None = None
    highlight: CommentHighlight | None = None
    body: str | None = None
    due: datetime | None = None
    assigned_to_user_id: uuid.UUID | None = None


class TaskPublic(SQLModel):
    id: uuid.UUID
    project_id: uuid.UUID
    response_id: uuid.UUID | None
    title: str
    kind: str
    source: str
    anchor_status: str
    attachment_id: uuid.UUID | None
    context_before: str | None
    context_after: str | None
    path: str | None
    original_text: str | None
    suggested_text: str | None
    highlight: dict | None
    body: str | None
    status: str
    verdict: str | None
    assigned_to_user_id: uuid.UUID | None
    board_position: float
    due: datetime | None
    github_issue_url: str | None
    from_contribution: bool
    decided_at: datetime | None
    applied_git_rev: str | None
    created: datetime


class TaskBoardPatch(SQLModel):
    """Move a card: change its column, assignee, position, or due date.

    Separate from the verdict on purpose -- dragging a card to "in progress"
    says nothing about whether the underlying suggestion was agreed with, and
    agreeing with it says nothing about whether it's been done.
    """

    status: TaskStatus | None = None
    assigned_to_user_id: uuid.UUID | None = None
    board_position: float | None = None
    due: datetime | None = None
    title: str | None = None
    body: str | None = None


class TaskVerdictPost(SQLModel):
    """Accept or reject one proposed item."""

    verdict: TaskVerdict
    # Whether to write an accepted edit to the repo now. False accepts the
    # suggestion but leaves the work for a person, which is the normal case
    # for anything an anchor couldn't be resolved for.
    apply: bool = True


class TaskIngestResult(SQLModel):
    """What came out of ingesting a marked-up document."""

    created: int
    resolved: int
    ambiguous: int
    unresolved: int
    todo_ids: list[uuid.UUID] = Field(default_factory=list)
