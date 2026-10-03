"""Authentication."""

import base64
import hashlib
import hmac
import secrets
import struct
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Literal

import jwt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext

from app.config import settings

EMAIL_VERIFICATION_LINK_HOURS = 24

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


@lru_cache
def _operator_grant_key() -> Ed25519PrivateKey:
    """The key that signs grants to use an Operator, derived from
    SECRET_KEY, so Operators that pinned its public key stop trusting the
    hub if that's rotated, and have to be registered again.
    """
    seed = hmac.new(
        settings.SECRET_KEY.encode(), b"operator-grant", "sha256"
    ).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def get_operator_grant_public_key() -> str:
    """The public key Operators pin to check grants, base64-encoded."""
    raw = (
        _operator_grant_key()
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    return base64.b64encode(raw).decode()


def create_operator_grant(
    operator_id: uuid.UUID, user_id: uuid.UUID, expires_delta: timedelta
) -> str:
    """Create a grant for a user to open one channel to an Operator.

    It's signed with a key only the API holds, and the Operator checks it,
    so the relay, which carries it, can't open channels of its own.
    """
    payload = {
        "exp": datetime.now(timezone.utc) + expires_delta,
        "aud": str(operator_id),
        "sub": str(user_id),
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, _operator_grant_key(), algorithm="EdDSA")


def create_relay_token(
    kind: Literal["operator", "browser"],
    operator_id: uuid.UUID,
    user_id: uuid.UUID,
    expires_delta: timedelta,
    grant: str | None = None,
) -> str:
    """Create a JWT for opening one relay connection.

    These are signed with a key of their own, so the relay, which is
    exposed to the internet, never holds one that can sign logins. Each has
    a unique ID, so the relay can take it only once.
    """
    payload = {
        "exp": datetime.now(timezone.utc) + expires_delta,
        "sub": str(operator_id),
        "user_id": str(user_id),
        "scope": f"relay:{kind}",
        "jti": secrets.token_hex(16),
    }
    if grant is not None:
        payload["grant"] = grant
    return jwt.encode(payload, settings.RELAY_SECRET_KEY, algorithm=ALGORITHM)


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


def generate_email_verification_token(user_id: uuid.UUID, email: str) -> str:
    """A signed link token naming the user and the address it went to."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=EMAIL_VERIFICATION_LINK_HOURS)
    return jwt.encode(
        {
            "exp": expires.timestamp(),
            "nbf": now,
            "sub": str(user_id),
            "email": email,
            "purpose": "verify-email",
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )


def verify_email_verification_token(
    token: str,
) -> tuple[uuid.UUID, str] | None:
    """The user ID and email a verification link token was issued for.

    The purpose claim is checked so a password reset token, which is
    signed the same way, can't be handed in as a verification.
    """
    try:
        decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if decoded.get("purpose") != "verify-email":
            return None
        return uuid.UUID(str(decoded["sub"])), str(decoded["email"])
    except (InvalidTokenError, KeyError, ValueError):
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


TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6


def generate_totp_secret() -> str:
    """A random base32 secret for an authenticator app (RFC 6238)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def get_totp_code(secret: str, step: int) -> str:
    """The code for a time step, per RFC 6238 with SHA-1, as authenticator
    apps compute it.
    """
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return str(value % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


def match_totp_step(
    secret: str, code: str, now: float | None = None, window: int = 1
) -> int | None:
    """The time step a code is valid for, allowing a step of clock drift
    either way, or None if it isn't valid.
    """
    code = code.strip().replace(" ", "")
    if now is None:
        now = datetime.now(timezone.utc).timestamp()
    current = int(now // TOTP_PERIOD_SECONDS)
    for step in range(current - window, current + window + 1):
        if hmac.compare_digest(get_totp_code(secret, step), code):
            return step
    return None


def hash_token_verifier(verifier: str) -> str:
    """Hash the secret half of a token for storage.

    Tokens are generated with at least 192 random bits, far beyond what
    could be guessed, so a fast hash is as good as a slow one here, unlike
    for passwords. Being fast matters because it runs on every request a
    token makes.
    """
    return hashlib.sha256(verifier.encode()).hexdigest()


def verify_token_verifier(verifier: str, hashed: str) -> bool:
    """Check a token's secret half against its stored hash.

    Tokens made before hashing switched to SHA-256 have bcrypt hashes,
    which start with "$2", and still verify.
    """
    if hashed.startswith("$2"):
        return verify_password(verifier, hashed)
    return hmac.compare_digest(hash_token_verifier(verifier), hashed)


SECOND_FACTOR_SCOPE = "second-factor"


def create_second_factor_token(
    user_id: uuid.UUID, session_id: uuid.UUID, expires_delta: timedelta
) -> str:
    """Create a token proving a second factor was entered in one session.

    The session keeps it and sends it along with sensitive requests. It
    names that session, so it's worthless to any other credential the user
    has, and stops working when the session ends. It carries a scope, so
    the API's own auth rejects it as a login.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "exp": now + expires_delta,
        "iat": now,
        "sub": str(user_id),
        "sid": str(session_id),
        "scope": SECOND_FACTOR_SCOPE,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_second_factor_token(token: str) -> dict | None:
    """Decode a second factor token, or return None if it isn't valid."""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[ALGORITHM]
        )
    except InvalidTokenError:
        return None
    if payload.get("scope") != SECOND_FACTOR_SCOPE:
        return None
    return payload
