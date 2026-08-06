"""Core models that should make it into the top-level ``models`` namespace."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Union

import sqlalchemy
from app import utcnow

if TYPE_CHECKING:
    # Release lives in app.models.releases (imported into the app.models
    # namespace via __init__); this guarded import resolves the "Release"
    # forward reference in Project.releases for type checkers without creating
    # a runtime circular import.
    from app.models.releases import Release
from app.subscriptions import (
    PLAN_IDS,
    PLAN_NAMES,
    get_private_projects_limit,
    get_storage_limit,
)
from pydantic import BaseModel, EmailStr, computed_field
from sqlmodel import Field, Relationship, SQLModel


class Account(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(min_length=2, max_length=64, unique=True)
    display_name: str | None = Field(default=None, max_length=64)
    created: datetime = Field(
        default_factory=utcnow,
        sa_column_kwargs=dict(
            server_default=sqlalchemy.func.current_timestamp()
        ),
    )
    user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True
    )
    org_id: uuid.UUID | None = Field(
        default=None, foreign_key="org.id", nullable=True
    )
    # Null for accounts created without GitHub (email/Google signup). Project
    # owners must still have a github_name until git hosting is decoupled from
    # GitHub; collaborators need not.
    github_name: str | None = Field(default=None)
    # Relationships
    owned_projects: list["Project"] = Relationship(
        back_populates="owner_account",
        cascade_delete=True,
    )
    user: Union["User", None] = Relationship(back_populates="account")
    org: Union["Org", None] = Relationship(back_populates="account")

    @computed_field
    @property
    def type(self) -> str:
        if self.user_id is not None:
            return "user"
        elif self.org_id is not None:
            return "org"
        else:
            raise ValueError("Account is neither a user nor org account")


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=40)
    account_name: str | None = Field(default=None, max_length=64)
    github_username: str | None = Field(default=None, max_length=64)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=40)
    account_name: str | None = Field(default=None, max_length=64)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore
    password: str | None = Field(default=None, min_length=8, max_length=40)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)
    github_username: str | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=40)
    new_password: str = Field(min_length=8, max_length=40)


class UserGitHubToken(SQLModel, table=True):
    user_id: uuid.UUID = Field(foreign_key="user.id", primary_key=True)
    updated: datetime = Field(
        default_factory=utcnow,
        sa_column_kwargs=dict(
            server_onupdate=sqlalchemy.func.now(),
            server_default=sqlalchemy.func.now(),
        ),
    )
    access_token: str  # These should be encrypted
    refresh_token: str
    expires: datetime | None
    refresh_token_expires: datetime | None


class UserZenodoToken(SQLModel, table=True):
    user_id: uuid.UUID = Field(foreign_key="user.id", primary_key=True)
    updated: datetime = Field(
        default_factory=utcnow,
        sa_column_kwargs=dict(
            server_onupdate=sqlalchemy.func.now(),
            server_default=sqlalchemy.func.now(),
        ),
    )
    access_token: str  # These should be encrypted
    refresh_token: str
    expires: datetime | None
    refresh_token_expires: datetime | None


class UserOverleafToken(SQLModel, table=True):
    user_id: uuid.UUID = Field(foreign_key="user.id", primary_key=True)
    updated: datetime = Field(
        default_factory=utcnow,
        sa_column_kwargs=dict(
            server_onupdate=sqlalchemy.func.now(),
            server_default=sqlalchemy.func.now(),
        ),
    )
    access_token: str  # These should be encrypted
    expires: datetime | None = Field(default=None)


class UserExternalCredential(SQLModel, table=True):
    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            "user_id",
            "provider",
            "label",
            name="uq_userexternalcredential_user_provider_label",
        ),
        sqlalchemy.Index(
            "ix_userexternalcredential_user_provider",
            "user_id",
            "provider",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id")
    provider: str = Field(min_length=2, max_length=64)
    credential_type: str = Field(default="oauth2", min_length=2, max_length=64)
    label: str = Field(default="default", min_length=1, max_length=128)
    secret_payload: str  # This should be encrypted
    scopes: str | None = Field(default=None, max_length=2048)
    provider_account_id: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = Field(
        default=None,
        sa_column=sqlalchemy.Column(sqlalchemy.JSON, nullable=True),
    )
    updated: datetime = Field(
        default_factory=utcnow,
        sa_column_kwargs=dict(
            server_onupdate=sqlalchemy.func.now(),
            server_default=sqlalchemy.func.now(),
        ),
    )
    expires: datetime | None = Field(default=None)
    refresh_token_expires: datetime | None = Field(default=None)
    # Relationships
    user: "User" = Relationship(back_populates="external_credentials")


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    stripe_customer_id: str | None = None
    zenodo_user_id: str | None = None
    # Relationships
    account: Account = Relationship(back_populates="user", cascade_delete=True)
    github_token: UserGitHubToken | None = Relationship(cascade_delete=True)
    zenodo_token: UserZenodoToken | None = Relationship(cascade_delete=True)
    overleaf_token: UserOverleafToken | None = Relationship(
        cascade_delete=True
    )
    refresh_tokens: list["RefreshToken"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    external_credentials: list[UserExternalCredential] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    org_memberships: list["UserOrgMembership"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    subscription: Union["UserSubscription", None] = Relationship(
        back_populates="user", cascade_delete=True
    )
    project_access: list["UserProjectAccess"] = Relationship(
        back_populates="user",
        cascade_delete=True,
        # Disambiguate from the invited_by_user_id FK on UserProjectAccess.
        sa_relationship_kwargs={"foreign_keys": "[UserProjectAccess.user_id]"},
    )
    project_comments: list["ProjectComment"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    notifications: list["Notification"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )

    @computed_field
    @property
    def github_username(self) -> str | None:
        return self.account.github_name

    @property
    def owned_projects(self) -> list["Project"]:
        return self.account.owned_projects

    def get_external_credential(
        self, provider: str, label: str = "default"
    ) -> UserExternalCredential | None:
        for cred in self.external_credentials:
            if cred.provider == provider and cred.label == label:
                return cred
        return None


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    github_username: str | None
    subscription: Union["UserSubscription", None]


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


class Org(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # Relationships
    account: Account = Relationship(back_populates="org")
    user_memberships: list["UserOrgMembership"] = Relationship(
        back_populates="org"
    )
    subscription: "OrgSubscription" = Relationship(back_populates="org")

    @computed_field
    @property
    def display_name(self) -> str:
        return self.account.display_name or self.account.name

    @computed_field
    @property
    def github_name(self) -> str:
        # Orgs are always created with a GitHub name.
        if self.account.github_name is None:
            raise ValueError("Org account has no github_name")
        return self.account.github_name

    @property
    def owned_projects(self) -> list["Project"]:
        return self.account.owned_projects

    @property
    def subscription_valid(self) -> bool:
        """Check if the org has a valid subscription."""
        if self.subscription is None:
            return False
        if self.subscription.paid_until is None:
            return True
        return self.subscription.paid_until >= utcnow()


# These could be put in the database, but that seems unnecessary
ROLE_IDS = {
    name: n for n, name in enumerate(["read", "write", "admin", "owner"])
}
ROLE_NAMES = {i: name for name, i in ROLE_IDS.items()}


# Track user membership in an org
class UserOrgMembership(SQLModel, table=True):
    user_id: uuid.UUID = Field(foreign_key="user.id", primary_key=True)
    org_id: uuid.UUID = Field(foreign_key="org.id", primary_key=True)
    role_id: int = Field(ge=min(ROLE_IDS.values()), le=max(ROLE_IDS.values()))
    # Relationships
    user: User = Relationship(back_populates="org_memberships")
    org: Org = Relationship(back_populates="user_memberships")

    @computed_field
    @property
    def role_name(self) -> str:
        return ROLE_NAMES[self.role_id]


class _SubscriptionBase(SQLModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    created: datetime = Field(default_factory=utcnow)
    period_months: int
    price: float
    paid_until: datetime | None = None
    plan_id: int = Field(
        ge=min(PLAN_IDS.values()),
        le=max(PLAN_IDS.values()),
    )
    is_active: bool = True
    processor: str | None = None
    processor_product_id: str | None = None
    processor_price_id: str | None = None
    processor_subscription_id: str | None = None

    @computed_field
    @property
    def plan_name(self) -> str:
        return PLAN_NAMES[self.plan_id]

    @property
    def storage_limit(self) -> int:
        """Return the storage limit in GB."""
        return get_storage_limit(self.plan_name)  # type: ignore

    @property
    def private_projects_limit(self) -> int | None:
        """Return the max number of private projects for a subscription."""
        return get_private_projects_limit(self.plan_name)  # type: ignore


class OrgSubscription(_SubscriptionBase, table=True):
    org_id: uuid.UUID = Field(foreign_key="org.id", primary_key=True)
    n_users: int = Field(ge=1)
    subscriber_user_id: uuid.UUID = Field(foreign_key="user.id")
    # Relationships
    org: Org = Relationship(back_populates="subscription")


class UserSubscription(_SubscriptionBase, table=True):
    user_id: uuid.UUID = Field(foreign_key="user.id", primary_key=True)
    # Relationships
    user: User = Relationship(back_populates="subscription")


class SubscriptionUpdate(BaseModel):
    plan_name: Literal["free", "standard", "professional"]
    period: Literal["monthly", "annual"]
    discount_code: str | None = None


class UpdateSubscriptionResponse(BaseModel):
    subscription: UserSubscription | OrgSubscription
    stripe_session_client_secret: str | None


class DiscountCode(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created: datetime = Field(default_factory=utcnow)
    created_by_user_id: uuid.UUID = Field(foreign_key="user.id")
    created_for_account_id: uuid.UUID | None = Field(
        foreign_key="account.id",
        nullable=True,
        default=None,
    )
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    plan_id: int = Field(
        ge=min(PLAN_IDS.values()),
        le=max(PLAN_IDS.values()),
    )
    price: float
    months: int
    n_users: int = 1
    redeemed: datetime | None = None
    redeemed_by_user_id: uuid.UUID | None = Field(
        foreign_key="user.id",
        nullable=True,
        default=None,
    )

    @property
    def plan_name(self) -> str:
        return PLAN_NAMES[self.plan_id]


class DiscountCodePost(BaseModel):
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    created_for_account_name: str | None = None
    n_users: int = 1
    plan_name: Literal["standard", "professional"]
    price: float
    months: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int | None = None
    refresh_token: str | None = None


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class UserTokenPublic(SQLModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id")
    scope: str | None = None
    created: datetime = Field(default_factory=utcnow)
    updated: datetime = Field(default_factory=utcnow)
    expires: datetime
    is_active: bool
    description: str | None = Field(default=None, max_length=256)
    last_used: datetime | None = Field(default=None)


class UserToken(UserTokenPublic, table=True):
    selector: str | None = Field(
        default=None, index=True, unique=True, max_length=32
    )
    hashed_verifier: str | None = Field(default=None, max_length=64)
    # Relationships
    user: User = Relationship()

    @property
    def expired(self) -> bool:
        """Check if the token has expired."""
        if self.expires is None:
            return False
        return self.expires < utcnow()


class DeviceAuth(SQLModel, table=True):
    """A pending CLI device auth request."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    device_code: str = Field(index=True, unique=True, max_length=64)
    created: datetime = Field(
        default_factory=utcnow,
        sa_column_kwargs=dict(
            server_default=sqlalchemy.func.current_timestamp()
        ),
    )
    expires: datetime
    hostname: str | None = Field(default=None, max_length=255)
    user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True
    )

    @property
    def expired(self) -> bool:
        if self.expires is None:
            return False
        return self.expires < utcnow()


class RefreshToken(SQLModel, table=True):
    """A long-lived refresh token used to obtain new access tokens.

    The raw token value is never stored. Only sha256(token) is persisted so
    that a database dump cannot be used to impersonate users.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id")
    token_hash: str = Field(index=True, unique=True, max_length=64)
    created: datetime = Field(
        default_factory=utcnow,
        sa_column_kwargs=dict(
            server_default=sqlalchemy.func.current_timestamp()
        ),
    )
    expires: datetime
    is_active: bool = True
    description: str | None = Field(default=None, max_length=256)
    # Relationships
    user: "User" = Relationship(back_populates="refresh_tokens")

    @property
    def expired(self) -> bool:
        return self.expires < utcnow()


class RefreshTokenRequest(SQLModel):
    refresh_token: str


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=40)


class ProjectBase(SQLModel):
    name: str = Field(min_length=4, max_length=255)
    title: str = Field(min_length=4, max_length=255)
    description: str | None = Field(
        default=None, min_length=0, max_length=2048
    )
    is_public: bool = Field(default=False)
    created: datetime | None = Field(default_factory=utcnow)
    updated: datetime | None = Field(default_factory=utcnow)
    git_repo_url: str = Field(max_length=2048)
    latest_git_rev: str | None = Field(
        max_length=40, nullable=True, default=None
    )
    status: str | None = Field(default=None, min_length=4, max_length=32)
    status_updated: datetime | None = Field(default_factory=utcnow)
    status_message: str | None = Field(default=None, max_length=2048)


class Project(ProjectBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_account_id: uuid.UUID = Field(foreign_key="account.id")
    parent_project_id: uuid.UUID | None = Field(
        foreign_key="project.id", default=None
    )
    # Relationships
    owner_account: Account = Relationship(back_populates="owned_projects")
    user_access_records: list["UserProjectAccess"] = Relationship(
        back_populates="project", cascade_delete=True
    )
    # Shareable invite links that grant access when redeemed.
    invitations: list["ProjectInvitation"] = Relationship(
        back_populates="project", cascade_delete=True
    )
    # TODO: Figure out how to do self-referential relationships with parent
    # and children projects
    questions: list["Question"] = Relationship(
        back_populates="project", cascade_delete=True
    )
    datasets: list["Dataset"] = Relationship(
        back_populates="project", cascade_delete=True
    )
    file_locks: list["FileLock"] = Relationship(
        back_populates="project", cascade_delete=True
    )
    project_comments: list["ProjectComment"] = Relationship(
        back_populates="project", cascade_delete=True
    )
    notifications: list["Notification"] = Relationship(
        back_populates="project", cascade_delete=True
    )
    releases: list["Release"] = Relationship(
        back_populates="project", cascade_delete=True
    )

    @computed_field
    @property
    def owner_account_name(self) -> str:
        return self.owner_account.name

    @computed_field
    @property
    def owner_account_display_name(self) -> str:
        return self.owner_account.display_name or self.owner_account.name

    @computed_field
    @property
    def owner_account_type(self) -> str:
        return self.owner_account.type

    @computed_field
    @property
    def owner_github_name(self) -> str:
        # Project owners must have a GitHub account (collaborators need not)
        # until git hosting is decoupled from GitHub.
        if self.owner_account.github_name is None:
            raise ValueError("Project owner account has no github_name")
        return self.owner_account.github_name

    @property
    def owner(self) -> User | Org | None:
        if self.owner_account_type == "user":
            return self.owner_account.user
        elif self.owner_account_type == "org":
            return self.owner_account.org

    @property
    def current_user_access(
        self,
    ) -> Literal["read", "write", "admin", "owner"] | None:
        return getattr(self, "_current_user_access", None)

    @current_user_access.setter
    def current_user_access(
        self, val: Literal["read", "write", "admin", "owner"]
    ):
        self._current_user_access = val

    @property
    def github_repo(self) -> str | None:
        if not self.git_repo_url.startswith("https://github.com"):
            return
        return self.git_repo_url.removeprefix(
            "https://github.com/"
        ).removesuffix(".git")


class ProjectPublic(ProjectBase):
    id: uuid.UUID
    owner_account_id: uuid.UUID
    owner_account_name: str
    owner_account_display_name: str
    owner_account_type: str
    current_user_access: Literal["read", "write", "admin", "owner"] | None = (
        None
    )


class ProjectsPublic(SQLModel):
    data: list[ProjectPublic]
    count: int


class ProjectPost(ProjectBase):
    name: str = Field(min_length=4, max_length=255)
    title: str = Field(min_length=4, max_length=255)
    description: str | None = Field(
        default=None, min_length=0, max_length=2048
    )
    is_public: bool = Field(default=False)
    git_repo_url: str | None = Field(max_length=2048, default=None)
    template: str | None = None
    git_repo_exists: bool | None = None


class UserProjectAccess(SQLModel, table=True):
    """A user's access to a project.

    Unifies native Calkit membership (granted via invite links; ``role_id``
    set) and access derived from the project's GitHub repo (``github_access``,
    the permission GitHub reports, cached here). A row may carry either or both:
    ``role_id`` is the effective Calkit level and takes precedence, while
    ``github_access`` is retained to surface drift between GitHub and Calkit. A
    row with both null is a cached "GitHub grants no access" result.
    """

    user_id: uuid.UUID = Field(foreign_key="user.id", primary_key=True)
    project_id: uuid.UUID = Field(foreign_key="project.id", primary_key=True)
    # Calkit-native granted level (e.g. from an invite). None when access is
    # only GitHub-derived. Capped at admin by the API (never owner).
    role_id: int | None = Field(
        default=None, ge=min(ROLE_IDS.values()), le=max(ROLE_IDS.values())
    )
    # The permission GitHub reports for this user on the repo ("read"/"write"/
    # "admin"), or None if GitHub grants none. Cache and drift signal.
    github_access: str | None = Field(default=None, max_length=32)
    invited_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id"
    )
    created: datetime = Field(default_factory=utcnow)
    updated: datetime = Field(
        default_factory=utcnow,
        sa_column_kwargs=dict(
            server_onupdate=sqlalchemy.func.now(),
            server_default=sqlalchemy.func.now(),
        ),
    )
    # Relationships (user_id disambiguated from the invited_by_user_id FK)
    user: User = Relationship(
        back_populates="project_access",
        sa_relationship_kwargs={"foreign_keys": "[UserProjectAccess.user_id]"},
    )
    project: Project = Relationship(back_populates="user_access_records")

    @computed_field
    @property
    def role_name(self) -> str | None:
        return ROLE_NAMES[self.role_id] if self.role_id is not None else None


class ProjectInvitation(SQLModel, table=True):
    """A shareable invite link granting project membership when redeemed."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(foreign_key="project.id")
    # Only the SHA-256 hash of the token is stored; the raw token lives in the
    # invite URL and is shown to the creator once.
    token_hash: str = Field(unique=True, index=True)
    role_id: int = Field(ge=min(ROLE_IDS.values()), le=max(ROLE_IDS.values()))
    # Optional label for the link, and the address it was emailed to (if any).
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    created_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id"
    )
    created: datetime = Field(default_factory=utcnow)
    expires: datetime | None = Field(default=None)
    max_uses: int | None = Field(default=None)
    use_count: int = Field(default=0)
    revoked: bool = Field(default=False)
    # Relationships
    project: Project = Relationship(back_populates="invitations")

    @computed_field
    @property
    def role_name(self) -> str:
        return ROLE_NAMES[self.role_id]

    @property
    def is_valid(self) -> bool:
        if self.revoked:
            return False
        if self.expires is not None and self.expires < utcnow():
            return False
        if self.max_uses is not None and self.use_count >= self.max_uses:
            return False
        return True


class ProjectInvitationPost(SQLModel):
    # Invite links grant collaborator access only — never admin or owner.
    # Admins are added deliberately (not via a shareable link).
    role: Literal["read", "write"] = "write"
    expires_days: int | None = Field(default=None, ge=1, le=365)
    max_uses: int | None = Field(default=None, ge=1)
    # Optional label; and an address to email the invite link to.
    name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None


class ProjectInvitationPublic(SQLModel):
    id: uuid.UUID
    name: str | None = None
    email: str | None = None
    role_name: str
    created: datetime
    expires: datetime | None
    max_uses: int | None
    use_count: int
    revoked: bool


class ProjectInvitationCreated(ProjectInvitationPublic):
    # Raw token + ready-to-share URL, returned only at creation time.
    token: str
    url: str
    # Whether the invite email was actually sent (best-effort; false if no
    # recipient, SMTP is unconfigured, or sending failed).
    emailed: bool = False


class ProjectInvitationRedeemed(SQLModel):
    owner_name: str
    project_name: str
    role_name: str


class DvcPipelineStage(SQLModel):
    cmd: str
    deps: list[str] | None = None
    outs: list[str | dict[str, dict]] | None = None
    desc: str | None = None
    meta: dict | None = None
    wdir: str | None = None


class DvcForeachStage(SQLModel):
    foreach: list[str] | str
    do: DvcPipelineStage


class StageStatus(SQLModel):
    status: Literal[
        "up-to-date", "stale", "not-run", "unknown", "always-run", "frozen"
    ]
    modified_command: bool = False
    modified_inputs: list[str] = Field(default_factory=list)
    modified_outputs: list[str] = Field(default_factory=list)
    missing_outputs: list[str] = Field(default_factory=list)


class Pipeline(SQLModel):
    mermaid: str
    dvc_stages: dict[str, DvcPipelineStage | DvcForeachStage]
    dvc_yaml: str
    calkit_yaml: str | None
    stage_statuses: dict[str, StageStatus] = Field(default_factory=dict)
    status: Literal["up-to-date", "stale", "unknown"] = "unknown"


class Question(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(foreign_key="project.id")
    number: int
    question: str
    # Relationships
    project: Project = Relationship(back_populates="questions")


class Figure(SQLModel):
    path: str
    title: str
    description: str | None = None
    stage: str | None = None
    stage_status: "StageStatus | None" = None
    dataset: str | None = None
    content: str | None = None  # Base64 encoded
    url: str | None = None
    comment_count: int = 0
    storage: Literal["git", "dvc", "dvc-zip"] | None = None
    # TODO: Link to a dataset, or does the pipeline do that?
    # TODO: Add content, or maybe we can just get from Git contents via path?


class Result(SQLModel):
    path: str
    title: str
    description: str | None = None
    stage: str | None = None


class CommentHighlight(BaseModel):
    """Portable anchor for a highlighted region within an artifact.

    Currently used for PDF text highlights (react-pdf-highlighter format).
    ``position`` and ``content`` are kept as free-form dicts so the schema
    can accommodate future anchor types (image regions, notebook cells, etc.)
    without a migration.
    """

    position: dict
    content: dict = Field(default_factory=dict)


class ProjectComment(SQLModel, table=True):
    """A unified comment on any project artifact or on the project itself.

    ``artifact_type`` is one of 'figure', 'publication', 'notebook', 'file',
    or None for a project-level comment. ``artifact_path`` is the repo-relative
    path of the artifact (None for project-level comments).

    ``highlight`` carries a portable anchor position and is only populated for
    comments tied to a specific region (e.g., a PDF text selection). See
    ``CommentHighlight`` for the schema.

    ``parent_id`` enables flat one-level threading: replies point to the
    top-level comment. No nested replies are stored beyond one level in the UI,
    though the schema permits it for future use.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(foreign_key="project.id")
    user_id: uuid.UUID = Field(foreign_key="user.id")
    created: datetime = Field(default_factory=utcnow)
    updated: datetime = Field(default_factory=utcnow)
    comment: str = Field(
        sa_column=sqlalchemy.Column(sqlalchemy.Text, nullable=False)
    )
    artifact_path: str | None = Field(default=None, max_length=512)
    artifact_type: str | None = Field(default=None, max_length=50)
    # Artifact highlight, e.g., for publication comments.
    # Stored as a plain dict (JSON column); CommentHighlight is used only for
    # input validation in ProjectCommentPost. sa_column bypasses SQLModel's
    # Pydantic coercion layer so the Python type must match what psycopg
    # serializes — i.e. dict, not a Pydantic model.
    highlight: dict | None = Field(
        default=None,
        sa_column=sqlalchemy.Column(sqlalchemy.JSON, nullable=True),
    )
    # Parent comment ID for threaded replies (one level deep in the UI)
    parent_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="projectcomment.id",
    )
    external_url: str | None = Field(default=None, max_length=2048)
    resolved: datetime | None = Field(default=None)
    # Git context at the time the comment was posted
    git_ref: str | None = Field(default=None, max_length=256)
    git_rev: str | None = Field(default=None, max_length=40)
    # Relationships
    user: User = Relationship(back_populates="project_comments")
    project: Project = Relationship(back_populates="project_comments")

    @computed_field
    @property
    def user_github_username(self) -> str | None:
        return self.user.github_username

    @computed_field
    @property
    def user_full_name(self) -> str | None:
        return self.user.full_name

    @computed_field
    @property
    def user_email(self) -> str:
        return self.user.email


class ProjectCommentPost(SQLModel):
    comment: str
    artifact_path: str | None = None
    artifact_type: str | None = None
    highlight: CommentHighlight | None = None
    create_github_issue: bool = True
    parent_id: uuid.UUID | None = None
    git_ref: str | None = None


class ProjectCommentPatch(SQLModel):
    resolved: bool


class Notification(SQLModel, table=True):
    """In-app notification delivered to a user when a comment is posted on
    their project (or a project they collaborate on).

    Designed to be lightweight: no fan-out to external services here.
    ``link`` stores a frontend URL (e.g., ``/owner/project/publications?path=…``)
    so the notification can deep-link directly to the relevant item.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id")
    project_id: uuid.UUID = Field(foreign_key="project.id")
    project_comment_id: uuid.UUID | None = Field(
        default=None, foreign_key="projectcomment.id"
    )
    # Human-readable message, e.g., "Alice commented on pub.pdf"
    message: str = Field(max_length=500)
    # Frontend deep-link, e.g., "/owner/project/publications?path=pub.pdf"
    link: str = Field(max_length=2048)
    # None = unread; set to the timestamp when the user reads it
    read: datetime | None = Field(default=None)
    created: datetime = Field(default_factory=utcnow)
    # Relationships
    user: User = Relationship(back_populates="notifications")
    project: Project = Relationship(back_populates="notifications")


# Release-related models live in ``app.models.releases`` (imported into the
# ``app.models`` namespace via ``__init__``); ``Project.releases`` above refers
# to ``Release`` there by its registered name.


class DatasetBase(SQLModel):
    path: str = Field(primary_key=True)
    # Full path to origin project and dataset, if this is imported
    imported_from: str | None = None
    title: str | None = None
    tabular: bool | None = None
    stage: str | None = None
    description: str | None = None
    url: str | None = None  # To allow for downloads?


class Dataset(DatasetBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    # Project in which is was created
    project_id: uuid.UUID = Field(foreign_key="project.id", primary_key=True)
    # TODO: Track version somehow, and link to DVC remote MD5?
    # TODO: Is this a directory of files?
    # TODO: Track size? -- basically all DVC properties
    # Relationships
    project: Project = Relationship(back_populates="datasets")


class DVCOut(BaseModel):
    md5: str
    size: int
    hash: str = "md5"
    path: str
    remote: str
    push: bool = False


class DVCImport(BaseModel):
    """The necessary information to import a DVC object, which can be saved to
    a .dvc file.

    For example:

        outs:
          - md5: 46ce259ab949ecb23751eb88ec753ff2
            size: 83344240
            hash: md5
            path: time-ave-profiles.h5
            remote: calkit:petebachant/boundary-layer-turbulence-modeling
            push: false

    Note this is different from the file that would be produced by
    ``dvc import``, since they bundle in Git repo information to fetch from
    the original project's remote.

    """

    outs: list[DVCOut]


class GitImport(BaseModel):
    files: list[str]


class DatasetForImport(DatasetBase):
    dvc_import: DVCImport | None = None
    git_import: GitImport | None = None
    git_rev: str


class ImportedDataset(SQLModel):
    """A dataset imported into a project in a read-only fashion."""

    project_id: uuid.UUID = Field(foreign_key="project.id", primary_key=True)
    dataset_id: uuid.UUID = Field(foreign_key="dataset.id", primary_key=True)


class FileLock(SQLModel, table=True):
    project_id: uuid.UUID = Field(foreign_key="project.id", primary_key=True)
    path: str = Field(primary_key=True)
    created: datetime = Field(default_factory=utcnow)
    user_id: uuid.UUID = Field(foreign_key="user.id")
    # Relationships
    project: Project = Relationship(back_populates="file_locks")
    user: User = Relationship()

    @computed_field
    @property
    def user_github_username(self) -> str | None:
        return self.user.github_username

    @computed_field
    @property
    def user_email(self) -> str:
        return self.user.email


class StorageUsage(BaseModel):
    limit_gb: float
    used_gb: float


class ItemLock(BaseModel):
    created: datetime
    user_id: uuid.UUID
    user_email: str
    user_github_username: str


class _ContentsItemBase(BaseModel):
    name: str
    path: str
    type: str | None
    size: int | None
    in_repo: bool
    content: str | None = None
    url: str | None = None
    calkit_object: dict | None = None
    lock: ItemLock | None = None
    storage: Literal["git", "dvc", "dvc-zip"] | None = None
    # Pipeline stage that produces this path, if any (from dvc.lock)
    stage: str | None = None


class ContentsItem(_ContentsItemBase):
    dir_items: list[_ContentsItemBase] | None = None


class PublicationOverleaf(BaseModel):
    project_id: str
    wdir: str | None = None
    url: str | None = None
    push_paths: list[str] = []
    sync_paths: list[str] = []
    last_sync_commit: str | None = None


class Publication(BaseModel):
    path: str
    title: str
    description: str | None = None
    type: (
        Literal[
            "journal-article",
            "conference-paper",
            "presentation",
            "poster",
            "report",
            "book",
        ]
        | None
    ) = None
    stage: str | None = None
    stage_status: "StageStatus | None" = None
    content: str | None = None
    stage_info: DvcPipelineStage | None = None
    url: str | None = None
    overleaf: PublicationOverleaf | None = None
    storage: Literal["git", "dvc", "dvc-zip"] | None = None


# Question evidence models live here (after Figure, Result, and Publication) so
# their resolved-artifact fields reference already-defined types.
class QuestionEvidence(SQLModel):
    kind: Literal["figure", "result", "publication"]
    path: str
    key: str | None = None
    explanation: str | None = None
    # Resolved artifact the evidence points to, if it could be found
    figure: Figure | None = None
    result: Result | None = None
    publication: Publication | None = None
    # For result evidence with a key, the value read from the result file so it
    # can be shown dashboard-style
    value: str | None = None


class QuestionEvidencePost(SQLModel):
    kind: Literal["figure", "result", "publication"]
    path: str
    key: str | None = None
    explanation: str | None = None


class QuestionPublic(SQLModel):
    id: uuid.UUID
    project_id: uuid.UUID
    number: int
    question: str
    hypothesis: str | None = None
    answer: str | None = None
    evidence: list[QuestionEvidence] = []


class QuestionPut(SQLModel):
    question: str | None = None
    hypothesis: str | None = None
    answer: str | None = None
    evidence: list[QuestionEvidencePost] = []


class Presentation(BaseModel):
    path: str
    title: str
    description: str | None = None
    type: (
        Literal[
            "slides",
            "poster",
            "talk",
        ]
        | None
    ) = None
    stage: str | None = None
    content: str | None = None
    stage_info: DvcPipelineStage | None = None
    url: str | None = None
    storage: Literal["git", "dvc", "dvc-zip"] | None = None


class Notebook(BaseModel):
    path: str
    title: str | None = None
    description: str | None = None
    stage: str | None = None
    output_format: Literal["html", "notebook"] | None = None
    url: str | None = None
    content: str | None = None
    storage: Literal["git", "dvc", "dvc-zip"] | None = None


class FeatureVote(SQLModel, table=True):
    """A single user's vote for a not-yet-built feature.

    Used to gauge demand for features we haven't committed to building (e.g.,
    creating external releases from within Calkit rather than the CLI). One row
    per user per ``feature`` -- the unique constraint makes voting idempotent.
    """

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            "user_id", "feature", name="featurevote_user_id_feature_key"
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id")
    feature: str = Field(index=True, max_length=64)
    created: datetime = Field(default_factory=utcnow)


class FeatureVoteStatus(SQLModel):
    """Vote tally for a feature plus whether the current user has voted."""

    feature: str
    count: int
    has_voted: bool


class GitRef(BaseModel):
    """Represents a Git reference (commit, tag, or branch)."""

    name: str  # Full ref name (e.g., "main", "v1.0.0", "abc123def456...")
    kind: Literal["branch", "tag", "commit"]  # Kind of ref
    message: str | None = None  # Commit/tag message
    author: str | None = None  # Commit author
    timestamp: str | None = None  # ISO format datetime
    hash: str | None = None  # Full commit hash
    short_hash: str | None = (
        None  # Short commit hash (7 chars); consumer may truncate hash if needed
    )
    is_default: bool = False  # Whether this is the default branch
    ahead: int = 0  # Commits ahead of default branch
    behind: int = 0  # Commits behind default branch
