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
    model_validator,
)
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


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
    PROJECT_NAME: str
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
