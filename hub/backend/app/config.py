"""App configuration."""

import secrets
import warnings
from typing import Annotated, Any, Literal

from pydantic import (
    AnyUrl,
    BeforeValidator,
    HttpUrl,
    PostgresDsn,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_allowed_emails(v: Any) -> list[str] | None:
    """Parse the user allowlist, normalizing "no restriction" to None.

    Unset, blank, and an empty list all mean the same thing, so they
    collapse to a single sentinel rather than leaving callers to check
    for both None and [].
    """
    if v is None:
        return None
    if isinstance(v, str):
        v = v.split(",")
    if isinstance(v, list):
        emails = [str(i).strip() for i in v if str(i).strip()]
        return emails or None
    raise ValueError(v)


def parse_featured_projects(v: Any) -> list[str]:
    """Parse the featured project list into normalized ``owner/name`` slugs.

    Accepts a comma-separated string or a list, and drops anything that
    isn't a two-part slug so one typo in the environment can't take the
    landing page down with a 500.
    """
    if v is None:
        return []
    if isinstance(v, str):
        v = v.split(",")
    if not isinstance(v, list):
        raise ValueError(v)
    slugs = []
    for item in v:
        slug = str(item).strip().strip("/").lower()
        if slug.count("/") != 1 or not all(slug.split("/")):
            continue
        if slug not in slugs:
            slugs.append(slug)
    return slugs


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore"
    )
    # The project name is used in the default email sender name and in the
    # default frontend title, so it should be something that makes sense to
    # end users. It can be overridden in the frontend, but that would be
    # a separate setting from the backend's project name, which is used in
    # the default email sender name and in the default frontend title.
    PROJECT_NAME: str
    API_V1_STR: str = ""
    SECRET_KEY: str = secrets.token_urlsafe(32)
    FERNET_KEY: str  # Can be generated with Fernet.generate_key()
    # Optional comma-separated list of keys for decryption fallback.
    # First key is treated as the active key for encryption.
    FERNET_KEYS: str | None = None
    # Access token TTL; kept short because refresh tokens handle re-issuance.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    DOMAIN: str = "localhost"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    # Set at image build time from the hub/vX.Y.Z release tag, since the
    # build context has no .git to derive it from. Empty in a development
    # checkout, where app.version asks Git directly instead.
    HUB_VERSION: str = ""
    FRONTEND_HOST: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def server_host(self) -> str:
        # Use HTTPS for anything other than local development
        if self.ENVIRONMENT == "local":
            return f"http://{self.DOMAIN}"
        return f"https://{self.DOMAIN}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def frontend_host(self) -> str:
        # If explicitly set, use that (useful for local dev)
        if self.FRONTEND_HOST:
            return self.FRONTEND_HOST
        # Otherwise, use the same as server_host
        return self.server_host

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fernet_keys(self) -> list[str]:
        if self.FERNET_KEYS:
            keys = [
                k.strip() for k in self.FERNET_KEYS.split(",") if k.strip()
            ]
            if keys:
                return keys
        return [self.FERNET_KEY]

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []
    SENTRY_DSN: HttpUrl | None = None
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return MultiHostUrl.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )  # type: ignore

    # What to leave out of a clone. A research project keeps its results in
    # Git, so most of what a full clone downloads is old revisions of files
    # nobody is looking at: for one real project, 739 MB of the 957 MB was
    # history. ``blob:none`` fetches every commit and tree but only the file
    # contents actually asked for, which took that clone from ~350 s to 26 s
    # and 957 MB to 274 MB with byte-identical responses, including reads at
    # old refs. The cost is that reading a file at an old revision fetches it
    # then (about a second, once, then it is local for good), so a
    # deployment that needs reads to work without reaching the remote should
    # set this empty for full clones.
    GIT_CLONE_FILTER: str = "blob:none"

    # Shared cache. Everything the project view derives from a repo -- stage
    # statuses, parsed pipelines, figure listings -- is a pure function of a
    # commit SHA, so it can be cached until that SHA moves. Running several
    # workers means a per-process cache is cold most of the time, hence a
    # shared one. Unset disables caching entirely, which is a supported way
    # to run: every read just recomputes.
    REDIS_URL: str | None = None
    # How long a cached entry lives. Entries are keyed by commit SHA and so
    # are never stale, but they still expire so a repo nobody visits again
    # doesn't hold memory forever.
    CACHE_TTL_S: int = 86400

    # Object storage configuration
    # The root under which this hub stores all of its objects, usually
    # just a bucket; project DVC data lives in a folder within it (see
    # storage.DVC_DATA_DIR). The scheme picks the backend: s3:// for AWS
    # S3 and everything S3-compatible (the bundled MinIO, Cloudflare R2,
    # DigitalOcean Spaces, a self-run server), which are distinguished by
    # endpoint URL rather than by scheme, and gs:// for Google (the
    # gcs:// alias is rejected so there's only one spelling).
    OBJECT_STORAGE_PREFIX: str = "s3://calkit"
    # Unset means AWS S3 itself; set it for any other S3-compatible service,
    # including the MinIO container this stack can run
    OBJECT_STORAGE_ENDPOINT_URL: str | None = None
    OBJECT_STORAGE_KEY: str | None = None
    OBJECT_STORAGE_SECRET: str | None = None

    @field_validator("OBJECT_STORAGE_PREFIX")
    @classmethod
    def _check_storage_prefix(cls, v: str) -> str:
        # gcs:// is a gcsfs alias for gs://; rejecting it keeps one
        # spelling everywhere rather than two that must both be handled
        scheme = v.split("://")[0]
        if scheme == "gcs":
            raise ValueError(
                "OBJECT_STORAGE_PREFIX uses the gcs:// scheme; use gs:// "
                f"instead (got {v!r})"
            )
        if scheme not in ["s3", "gs"]:
            raise ValueError(
                "OBJECT_STORAGE_PREFIX must start with s3:// or gs:// "
                f"(got {v!r})"
            )
        # Object storage has no location without a bucket, and a bare
        # scheme would otherwise yield paths like 's3:/data'
        if not v.split("://", 1)[1].strip("/"):
            raise ValueError(
                "OBJECT_STORAGE_PREFIX must include a bucket, e.g. "
                f"s3://calkit (got {v!r})"
            )
        return v

    @computed_field  # type: ignore[prop-decorator]
    @property
    def object_storage_type(self) -> Literal["s3", "gcs"]:
        scheme = self.OBJECT_STORAGE_PREFIX.split("://")[0]
        return "gcs" if scheme == "gs" else "s3"

    # Emails allowed to use this hub, as a comma-separated list. Unset
    # (the default) means anyone can sign up and log in, which is what a
    # public instance wants; a private or pre-release instance sets it to
    # the people who should get in. Checked case-insensitively.
    ALLOWED_USER_EMAILS: Annotated[
        list[str] | None, BeforeValidator(parse_allowed_emails)
    ] = None

    def email_allowed(self, email: str | None) -> bool:
        """Check an email against the allowlist, allowing all if unset."""
        if self.ALLOWED_USER_EMAILS is None:
            return True
        if not email:
            return False
        # The bootstrap superuser is created by prestart on every deploy,
        # so an allowlist that omits it would break the deploy rather than
        # lock down signups
        if email.strip().lower() == self.FIRST_SUPERUSER.strip().lower():
            return True
        return email.strip().lower() in {
            a.lower() for a in self.ALLOWED_USER_EMAILS
        }

    # Projects showcased to signed-out visitors and to users who haven't
    # created anything yet, as a comma-separated list of ``owner/name``
    # slugs. Newest-first is what a hub has before anyone curates it, and
    # it shows a first-time visitor whatever happened to be created last
    # rather than what Calkit is for. Order here is the order shown.
    # Private or missing projects are skipped rather than erroring, so a
    # slug can be listed before the project is public.
    FEATURED_PROJECTS: Annotated[
        list[str], BeforeValidator(parse_featured_projects)
    ] = [
        "calkit/example-basic",
        "petebachant/nacafoil-openfoam",
        "petebachant/strava-analysis",
        "calkit/example-matlab",
        "calkit/example-overleaf",
        "petebachant/rans-boundary-layer-validation",
    ]

    # Where in-app feedback and help requests are sent. Falls back to the
    # hub operator (the bootstrap superuser), so a self-hosted instance
    # reaches someone real without being configured first.
    FEEDBACK_EMAIL: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def feedback_email(self) -> str:
        return self.FEEDBACK_EMAIL or self.FIRST_SUPERUSER

    # Email configuration
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    # TODO: update type to EmailStr when sqlmodel supports it
    EMAILS_FROM_EMAIL: str | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    # TODO: update type to EmailStr when sqlmodel supports it
    EMAIL_TEST_USER: str = "test@example.com"
    # TODO: update type to EmailStr when sqlmodel supports it
    FIRST_SUPERUSER: str
    FIRST_SUPERUSER_PASSWORD: str
    FIRST_SUPERUSER_GITHUB_USERNAME: str

    # GitHub
    GH_CLIENT_ID: str
    GH_CLIENT_SECRET: str
    # GitHub App private key (PEM contents), used to mint installation tokens
    # so GitHub-less members (email/Google signups) can push. Set it in .env or
    # as a GitHub Actions secret. Optional: without it, GitHub-less users can
    # only read public projects.
    GH_APP_PRIVATE_KEY: str | None = None
    # Stripe
    STRIPE_SECRET_KEY: str
    STRIPE_PUBLISHABLE_KEY: str
    # Mixpanel
    MIXPANEL_TOKEN: str
    # Zenodo
    ZENODO_CLIENT_ID: str
    ZENODO_CLIENT_SECRET: str
    # Google
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    # Zotero, which uses OAuth 1.0a, hence key/secret instead of ID/secret
    ZOTERO_CLIENT_KEY: str
    ZOTERO_CLIENT_SECRET: str

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )
        return self


settings = Settings()  # type: ignore
