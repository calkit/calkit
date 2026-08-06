"""Release-related models.

Split out from ``core`` for locality: the cloud release feature (hosted
review releases, share tokens, comments, view tracking) owns a good chunk of
the schema. The table classes register into ``SQLModel.metadata`` at import
time just like the core ones, so Alembic autogenerate and app startup see
them as long as this module is imported in ``app.models`` (it is, via
``__init__``).
"""

import uuid
from datetime import datetime
from typing import Literal

import sqlalchemy
from app import utcnow
from app.models.core import CommentHighlight, Project, User
from pydantic import BaseModel, computed_field, field_validator
from sqlmodel import Field, Relationship, SQLModel

# Release ``kind`` mirrors calkit's release schema (the ``releases`` map in
# calkit.yaml is keyed by tag). For this cloud feature the DB is the source of
# truth; private releases are not written to calkit.yaml.
ReleaseKind = Literal["project", "publication", "dataset", "model", "figure"]

# Characters Git forbids anywhere in a ref name (plus space and DEL); the rest
# of the rules are positional and handled in validate_release_name.
_GIT_REF_FORBIDDEN = set(" \x7f~^:?*[\\")


def validate_release_name(name: str) -> str:
    """Validate a release name as a Git tag name, returning it unchanged.

    A release becomes a Git tag (and a calkit.yaml key), so its name must
    satisfy Git's ``check-ref-format`` rules. Raises ``ValueError`` with a
    user-facing message when it doesn't, so the API responds with a 422. Keep
    this in sync with ``validateReleaseName`` in the frontend.
    """
    name = name.strip()
    if not name:
        raise ValueError("Release name is required.")
    if any(c in _GIT_REF_FORBIDDEN or ord(c) < 0x20 for c in name):
        raise ValueError(
            "Release name can't contain spaces or any of: ~ ^ : ? * [ \\"
        )
    if name in ("@",):
        raise ValueError("Release name can't be '@'.")
    if name.startswith("-"):
        raise ValueError("Release name can't start with '-'.")
    if name.startswith("/") or name.endswith("/") or "//" in name:
        raise ValueError(
            "Release name can't start or end with '/' or contain '//'."
        )
    if name.endswith("."):
        raise ValueError("Release name can't end with '.'.")
    if ".." in name or "@{" in name:
        raise ValueError("Release name can't contain '..' or '@{'.")
    # Per-component (slash-separated) Git rules.
    for part in name.split("/"):
        if part.startswith(".") or part.endswith(".lock"):
            raise ValueError(
                "No part of the release name can start with '.' or end with "
                "'.lock'."
            )
    return name


class ReleaseBase(SQLModel):
    # ``name`` is the release tag/identifier, unique within a project.
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="publication", max_length=32)
    # Released path; None or "." means the whole project.
    path: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=2048)
    # Human-readable ref the release was cut from (tag or branch).
    git_ref: str | None = Field(default=None, max_length=256)
    # Full commit SHA the content is pinned to.
    git_rev: str | None = Field(default=None, max_length=40)
    public: bool = Field(default=False)
    # Populated for public releases (e.g., Zenodo); unused for private ones.
    url: str | None = Field(default=None, max_length=2048)
    doi: str | None = Field(default=None, max_length=255)


class Release(ReleaseBase, table=True):
    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            "project_id", "name", name="uq_release_project_name"
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(foreign_key="project.id")
    created_by_user_id: uuid.UUID = Field(foreign_key="user.id")
    view_count: int = Field(default=0)
    # The GitHub release this Calkit release was published to, if any. Set when
    # the release is pushed to GitHub (or an existing GitHub release for the tag
    # is found), so the releases table can show its "released to GitHub" status.
    github_release_url: str | None = Field(default=None, max_length=2048)
    created: datetime = Field(default_factory=utcnow)
    # Relationships
    project: Project = Relationship(back_populates="releases")
    created_by: User = Relationship()
    comments: list["ReleaseComment"] = Relationship(
        back_populates="release", cascade_delete=True
    )
    share_tokens: list["ReleaseShareToken"] = Relationship(
        back_populates="release", cascade_delete=True
    )
    viewers: list["ReleaseViewer"] = Relationship(
        back_populates="release", cascade_delete=True
    )

    @computed_field
    @property
    def comment_count(self) -> int:
        return len(self.comments)

    @computed_field
    @property
    def git_rev_abbrev(self) -> str | None:
        return self.git_rev[:7] if self.git_rev else None


class ReleasePost(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str = "publication"
    path: str | None = None
    description: str | None = None
    # If None, defaults to the project's default branch HEAD.
    git_ref: str | None = None
    public: bool = False
    # Set True to release even when the producing pipeline stage is stale, i.e.
    # the user has acknowledged the artifact may not be reproducible.
    acknowledge_non_reproducible: bool = False

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return validate_release_name(v)


class ReleaseStaleness(SQLModel):
    """Whether the pipeline stage that produces a release path is up-to-date.

    Used to warn before creating a release of a possibly non-reproducible
    artifact. ``stage`` is None when the path isn't produced by any pipeline
    stage (staleness doesn't apply), in which case ``up_to_date`` stays True.
    """

    path: str | None = None
    stage: str | None = None
    status: (
        Literal[
            "up-to-date",
            "stale",
            "not-run",
            "unknown",
            "always-run",
            "frozen",
        ]
        | None
    ) = None
    up_to_date: bool = True
    modified_inputs: list[str] = Field(default_factory=list)
    modified_outputs: list[str] = Field(default_factory=list)
    missing_outputs: list[str] = Field(default_factory=list)


class ReleasePublic(ReleaseBase):
    """Release as seen by a user with write access."""

    id: uuid.UUID
    project_id: uuid.UUID
    view_count: int
    comment_count: int
    git_rev_abbrev: str | None
    created: datetime


class ReleaseView(SQLModel):
    """Release as rendered on its page, for a member or a share-token holder.

    Deliberately omits internal identifiers; exposes only what the viewer page
    needs to render the artifact, the provenance note, and comments. The
    viewer's effective ``permission`` says whether they may comment or manage
    the release, so the UI can adapt without leaking the share tokens.
    """

    name: str
    kind: str
    path: str | None
    description: str | None
    git_ref: str | None
    git_rev_abbrev: str | None
    public: bool
    comment_count: int
    created: datetime
    owner_account_name: str
    owner_account_display_name: str
    project_name: str
    project_title: str
    # The viewing party's effective access: ``view`` (read-only), ``comment``
    # (may post comments), or ``manage`` (a project member with write access).
    permission: Literal["view", "comment", "manage"]
    # Pre-fill/identity for a token-scoped viewer (attribution only).
    viewer_email: str | None = None


class ReleaseComment(SQLModel, table=True):
    """A comment posted against a release via its secret link.

    Kept separate from ``ProjectComment`` because release comments may be
    anonymous (no ``user_id``) and are scoped to a release rather than a
    project artifact path.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    release_id: uuid.UUID = Field(foreign_key="release.id")
    # Set when the commenter was logged in; None for anonymous comments.
    user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id")
    # Set when the comment came in through a share link; records which invite.
    # ON DELETE SET NULL so revoking/deleting a share token (or its release)
    # never trips over the referencing comments -- the comment's own
    # name/email attribution is preserved.
    share_token_id: uuid.UUID | None = Field(
        default=None,
        sa_column=sqlalchemy.Column(
            sqlalchemy.Uuid,
            sqlalchemy.ForeignKey("releasesharetoken.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Optional display name supplied by an anonymous commenter.
    author_name: str | None = Field(default=None, max_length=255)
    # Email the comment is attributed to (from the share token or the logged-in
    # user). Attribution only -- never verified.
    author_email: str | None = Field(default=None, max_length=320)
    # The commit the comment was made against -- copied from the release at post
    # time so feedback stays pinned to the exact reviewed revision.
    git_rev: str | None = Field(default=None, max_length=40)
    comment: str = Field(
        sa_column=sqlalchemy.Column(sqlalchemy.Text, nullable=False)
    )
    # Optional PDF (or other artifact) highlight anchor this comment is pinned
    # to, in the react-pdf-highlighter format. Stored as a plain dict (JSON
    # column); CommentHighlight is used only for input validation in the post
    # schema, matching ProjectComment.highlight.
    highlight: dict | None = Field(
        default=None,
        sa_column=sqlalchemy.Column(sqlalchemy.JSON, nullable=True),
    )
    # GitHub URL the comment was mirrored to: the thread's own issue for a
    # top-level comment, or the issue-comment anchor for a reply, mirroring
    # ProjectComment.external_url (one issue per thread, not per release).
    external_url: str | None = Field(default=None, max_length=2048)
    # Parent comment for flat one-level threading: replies point to the
    # top-level comment, mirroring ProjectComment.parent_id.
    parent_id: uuid.UUID | None = Field(
        default=None, foreign_key="releasecomment.id"
    )
    # When the thread was resolved (its GitHub issue closed). Set on the
    # top-level comment and cascaded to its replies, mirroring ProjectComment.
    resolved: datetime | None = Field(default=None)
    created: datetime = Field(default_factory=utcnow)
    # Relationships
    release: Release = Relationship(back_populates="comments")


class ReleaseCommentPost(SQLModel):
    comment: str = Field(min_length=1)
    author_name: str | None = None
    highlight: CommentHighlight | None = None
    # When set, this comment is a reply to the given top-level comment.
    parent_id: uuid.UUID | None = None


class ReleaseCommentResolvePost(SQLModel):
    resolved: bool


class ReleaseCommentPublic(SQLModel):
    id: uuid.UUID
    author_name: str | None
    comment: str
    highlight: dict | None = None
    external_url: str | None
    parent_id: uuid.UUID | None = None
    # When set, this comment's thread is resolved (its GitHub issue closed).
    resolved: datetime | None = None
    created: datetime


# Permission a share token grants. ``view`` is read-only; ``comment`` also
# allows posting comments. Editing is intentionally never grantable via a
# release share token -- releases are no-signup and comment-only.
ReleaseSharePermission = Literal["view", "comment"]


class ReleaseShareToken(SQLModel, table=True):
    """An unguessable link that grants scoped, no-signup access to a release.

    Each token optionally targets a specific recipient ``email`` (attribution
    only -- never verified) and carries a ``permission`` of ``view`` or
    ``comment``. A release can have many tokens, so access can be granted and
    revoked per recipient without affecting the others.

    Only the SHA-256 ``token_hash`` is stored -- the raw token is shown to its
    creator once at mint time and never persisted, so a database leak can't be
    turned into working links. The tokens are high-entropy, so a plain (fast)
    hash is sufficient and keeps the lookup an indexed equality check.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    release_id: uuid.UUID = Field(foreign_key="release.id")
    created_by_user_id: uuid.UUID = Field(foreign_key="user.id")
    token_hash: str = Field(index=True, unique=True, max_length=64)
    # Intended recipient; None means "anyone with the link".
    email: str | None = Field(default=None, max_length=320)
    permission: str = Field(default="comment", max_length=16)
    # Optional human label, e.g. "Reviewer 2".
    note: str | None = Field(default=None, max_length=255)
    expires_at: datetime | None = Field(default=None)
    revoked: bool = Field(default=False)
    view_count: int = Field(default=0)
    created: datetime = Field(default_factory=utcnow)
    # Relationships
    release: Release = Relationship(back_populates="share_tokens")
    created_by: User = Relationship()


class ReleaseViewer(SQLModel, table=True):
    """A distinct viewer of a release, so ``view_count`` counts unique viewers.

    A viewer is either a logged-in member (``user_id``) or an anonymous
    share-link visitor (``share_token_id``); exactly one is set per row. The
    release's ``view_count`` is bumped only when a new row is inserted, so
    repeat visits by the same viewer don't inflate it. Anonymous visitors with
    no share token (e.g., a public project viewed while logged out) can't be
    identified, so they aren't counted.
    """

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            "release_id", "user_id", name="uq_releaseviewer_release_user"
        ),
        sqlalchemy.UniqueConstraint(
            "release_id",
            "share_token_id",
            name="uq_releaseviewer_release_token",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    release_id: uuid.UUID = Field(foreign_key="release.id", ondelete="CASCADE")
    user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="CASCADE"
    )
    share_token_id: uuid.UUID | None = Field(
        default=None, foreign_key="releasesharetoken.id", ondelete="SET NULL"
    )
    created: datetime = Field(default_factory=utcnow)
    # Relationships
    release: Release = Relationship(back_populates="viewers")


class ReleaseShareTokenPost(SQLModel):
    email: str | None = None
    permission: ReleaseSharePermission = "comment"
    note: str | None = None
    expires_at: datetime | None = None


class ReleaseShareTokenPublic(SQLModel):
    """A share token as shown in the manage list -- never includes the secret."""

    id: uuid.UUID
    email: str | None
    permission: str
    note: str | None
    expires_at: datetime | None
    revoked: bool
    view_count: int
    created: datetime


class ReleaseShareTokenCreated(ReleaseShareTokenPublic):
    """Returned once when a token is minted; carries the raw token to share."""

    token: str
    # Whether the invite email was actually sent to ``email``. False when no
    # recipient was given or email isn't configured, in which case the caller
    # falls back to copying the link.
    email_sent: bool = False


class ReleaseListItem(BaseModel):
    """A release row for the project releases page.

    Merges two sources: ``calkit`` releases declared in ``calkit.yaml`` (the
    public, DOI-bearing ones produced via the CLI/Zenodo) and ``cloud``
    releases stored in this database (the private, secret-link ones). Fields
    that only apply to one source are optional.
    """

    source: Literal["cloud", "calkit"]
    name: str
    kind: str | None = None
    path: str | None = None
    description: str | None = None
    git_ref: str | None = None
    git_rev: str | None = None
    git_rev_abbrev: str | None = None
    # calkit.yaml releases default to public (a missing key means public);
    # cloud releases carry an explicit flag.
    public: bool = True
    url: str | None = None
    doi: str | None = None
    # Where the artifact was declared released (e.g., arxiv, journal, zenodo,
    # caltechdata). Unified with the existing ``publisher`` key that Zenodo
    # releases already use. ``None`` for hosted cloud secret-link releases.
    publisher: str | None = None
    # Release date as an ISO string (calkit.yaml ``date`` or cloud ``created``).
    date: str | None = None
    # An internal release: a frozen, pinned snapshot hosted for review rather
    # than published to an archival service. True for all cloud releases and
    # for calkit.yaml entries with ``internal: true``.
    internal: bool = False
    # Cloud-only fields.
    view_count: int | None = None
    comment_count: int | None = None
    # Number of active (non-revoked) share links, for cloud releases.
    share_count: int | None = None
    # The GitHub release URL when this release has been published to GitHub. For
    # cloud releases this is stored; for calkit.yaml releases imported from
    # GitHub it's the release's ``url``. ``None`` means not on GitHub (yet).
    github_release_url: str | None = None


class ReleaseGithubResult(BaseModel):
    """Result of creating (or finding) a GitHub release for a Calkit release."""

    url: str
    # False when a GitHub release already existed for the tag and we returned
    # its link instead of creating a duplicate.
    created: bool


class ExternalReleasePost(SQLModel):
    """A release declared as published to an external venue.

    Recorded loosely in ``calkit.yaml`` (not hosted by Calkit); used to track
    that an artifact was, e.g., posted to arXiv or published in a journal. The
    ``publisher`` key matches what Zenodo releases already write.
    """

    name: str = Field(min_length=1, max_length=255)
    kind: str = "publication"
    path: str | None = None
    publisher: str | None = None
    url: str | None = None
    doi: str | None = None
    # ISO date string; defaults to today when omitted.
    date: str | None = None
    description: str | None = None
    public: bool = True

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return validate_release_name(v)


class ReleaseUrlImport(SQLModel):
    """Request to look up an already-published release from a URL or DOI."""

    url: str = Field(min_length=1, max_length=2048)


class ReleaseUrlMetadata(SQLModel):
    """Metadata parsed from an external release URL/DOI.

    Returned by the parse-url lookup so the create modal can pre-fill the
    declare-external form. The user reviews/edits it, then submits via the
    external release endpoint. ``git_rev`` is intentionally absent -- imports
    can't know the producing commit, so it's left for the user to set later.
    """

    publisher: str | None = None
    title: str | None = None
    doi: str | None = None
    url: str | None = None
    # ISO date string (YYYY-MM-DD) when available.
    date: str | None = None
    description: str | None = None
    # Best-guess calkit release kind (e.g., "publication" for a preprint).
    kind: str = "publication"
