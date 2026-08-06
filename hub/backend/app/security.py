"""Authentication."""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import jwt
from app.config import settings
from cryptography.fernet import Fernet
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"
SCOPES = ["dvc"]


@lru_cache(maxsize=1)
def _get_fernet_instances() -> tuple[Fernet, list[Fernet]]:
    keys = settings.fernet_keys
    primary = Fernet(key=keys[0])
    fallbacks = [Fernet(key=k) for k in keys]
    return primary, fallbacks


def create_access_token(
    subject: str | Any,
    expires_delta: timedelta,
    scope: str | None = None,
    add_payload: dict | None = None,
    token_id: uuid.UUID | None = None,
) -> str:
    """Create an access token.

    Parameters
    ----------
    subject : str
        The subject for the access token, typically a user ID.
    expires_delta : timedelta
        How long from now the token should expire.
    scope : str, optional
        The scope of the token. If there are multiple, they should be
        space-separated.
    add_payload : dict, optional
        Additional payload to include in the token.
    token_id : uuid.UUID, optional
        The unique identifier for the token.
    """
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {"exp": expire, "sub": str(subject)}
    if scope is not None:
        for s in scope.split():
            if s not in SCOPES:
                raise ValueError(f"{s} is not a valid scope")
        to_encode["scope"] = scope
    if token_id is not None:
        to_encode["token_id"] = str(token_id)
    if add_payload:
        to_encode.update(add_payload)
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=ALGORITHM
    )
    return encoded_jwt


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def generate_password_reset_token(email: str) -> str:
    delta = timedelta(hours=settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS)
    now = datetime.now(timezone.utc)
    expires = now + delta
    exp = expires.timestamp()
    encoded_jwt = jwt.encode(
        {"exp": exp, "nbf": now, "sub": email},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    return encoded_jwt


def verify_password_reset_token(token: str) -> str | None:
    try:
        decoded_token = jwt.decode(
            token, settings.SECRET_KEY, algorithms=["HS256"]
        )
        return str(decoded_token["sub"])
    except InvalidTokenError:
        return None


def encrypt_secret(value: str) -> str:
    primary, _ = _get_fernet_instances()
    return primary.encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    _, fallbacks = _get_fernet_instances()
    for fernet in fallbacks:
        try:
            return fernet.decrypt(value.encode()).decode()
        except Exception:
            continue
    raise ValueError("Failed to decrypt secret with configured Fernet keys")


def generate_refresh_token() -> str:
    """Generate a cryptographically secure random refresh token string."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """Return the hex-encoded SHA-256 digest of a refresh token."""
    return hashlib.sha256(token.encode()).hexdigest()
