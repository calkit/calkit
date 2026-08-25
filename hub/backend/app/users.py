"""Functionality for working with users."""

import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any

import requests
from fastapi import HTTPException
from requests.exceptions import JSONDecodeError
from sqlmodel import Session, select

import app.stripe
from app import utcnow
from app.config import settings
from app.core import INVALID_ACCOUNT_NAMES, ORG_ONLY_ACCOUNT_NAMES
from app.github import token_resp_text_to_dict
from app.messaging import EMAIL_VERIFICATION_CODE_MINUTES
from app.models import (
    Account,
    User,
    UserCreate,
    UserEmailVerification,
    UserExternalCredential,
    UserGitHubToken,
    UserSubscription,
    UserUpdate,
)
from app.security import (
    decrypt_secret,
    encrypt_secret,
    generate_email_verification_token,
    get_password_hash,
    verify_email_verification_token,
    verify_password,
)
from app.zenodo import AUTH_URL as ZENODO_AUTH_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_external_credential(
    session: Session,
    user: User,
    provider: str,
    label: str = "default",
) -> UserExternalCredential | None:
    statement = select(UserExternalCredential).where(
        UserExternalCredential.user_id == user.id,
        UserExternalCredential.provider == provider,
        UserExternalCredential.label == label,
    )
    return session.exec(statement).first()


def get_external_secret_payload(
    session: Session,
    user: User,
    provider: str,
    label: str = "default",
) -> str:
    credential = get_external_credential(
        session=session,
        user=user,
        provider=provider,
        label=label,
    )
    if credential is None:
        raise HTTPException(404, f"No {provider} credential found")
    return decrypt_secret(credential.secret_payload)


def save_external_credential(
    session: Session,
    user: User,
    provider: str,
    secret_payload: str,
    *,
    credential_type: str = "oauth2",
    label: str = "default",
    scopes: str | None = None,
    provider_account_id: str | None = None,
    metadata_json: dict[str, Any] | None = None,
    expires: datetime | None = None,
    refresh_token_expires: datetime | None = None,
) -> UserExternalCredential:
    now = utcnow()
    credential = get_external_credential(
        session=session,
        user=user,
        provider=provider,
        label=label,
    )
    if credential is None:
        credential = UserExternalCredential(
            user_id=user.id,
            provider=provider,
            credential_type=credential_type,
            label=label,
            secret_payload=encrypt_secret(secret_payload),
            scopes=scopes,
            provider_account_id=provider_account_id,
            metadata_json=metadata_json,
            expires=expires,
            refresh_token_expires=refresh_token_expires,
        )
    else:
        credential.credential_type = credential_type
        credential.secret_payload = encrypt_secret(secret_payload)
        credential.scopes = scopes
        credential.provider_account_id = provider_account_id
        credential.metadata_json = metadata_json
        credential.expires = expires
        credential.refresh_token_expires = refresh_token_expires
        credential.updated = now
    session.add(credential)
    session.commit()
    session.refresh(credential)
    return credential


def check_email_allowed(email: str | None) -> None:
    """Refuse an email the hub's allowlist doesn't cover.

    Enforced at every point where an identity enters or re-enters the
    system, so a private instance can't be signed up for or logged into
    by someone left off the list.
    """
    if not settings.email_allowed(email):
        logger.info(f"Email not allowed on this hub: {email}")
        raise HTTPException(
            403, "This Calkit hub is not open to this email address"
        )


def create_user(*, session: Session, user_create: UserCreate) -> User:
    check_email_allowed(user_create.email)
    account_name = user_create.account_name or user_create.github_username
    if not account_name:
        account_name = user_create.email.split("@")[0]
    # Only set a GitHub name when the user actually has a GitHub account;
    # GitHub-less (email/Google) signups leave it null.
    github_name = user_create.github_username
    if account_name.lower() in (
        INVALID_ACCOUNT_NAMES + ORG_ONLY_ACCOUNT_NAMES
    ):
        raise HTTPException(422, "Invalid account name")
    existing = session.exec(
        select(Account).where(Account.name == account_name.lower())
    ).first()
    if existing is not None and user_create.account_name:
        raise HTTPException(422, "Account name is already taken")
    if existing is not None:
        # A name nobody chose (the email's local part, or a GitHub name
        # already used here) shouldn't block signup: a second alex@ gets
        # alex-2
        base = account_name
        for n in range(2, 1000):
            account_name = f"{base}-{n}"
            if (
                session.exec(
                    select(Account).where(Account.name == account_name.lower())
                ).first()
                is None
            ):
                break
        else:
            raise HTTPException(422, "Account name is already taken")
    user = User.model_validate(
        user_create,
        update={
            "hashed_password": get_password_hash(user_create.password),
            "account": Account(
                name=account_name.lower(),
                display_name=account_name,
                github_name=github_name,
            ),  # type: ignore
        },
    )
    # Give the user a free subscription by default
    user.subscription = UserSubscription(
        period_months=1,
        plan_id=0,
        price=0.0,
    )  # type: ignore
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def update_user(
    *, session: Session, db_user: User, user_in: UserUpdate
) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


def email_is_verified(*, session: Session, user: User) -> bool:
    """Whether the account's email is known to belong to whoever holds it.

    See ``User.email_verified`` for what counts.
    """
    return user.email_verified


EMAIL_VERIFICATION_RESEND_SECONDS = 60
EMAIL_VERIFICATION_MAX_ATTEMPTS = 5


def hash_email_verification_code(code: str) -> str:
    """The stored form of a code: an HMAC under the server's secret.

    Six digits is too small a space to protect with a slow hash alone,
    which is why guesses are counted; keying the hash keeps a leaked table
    from being useful on its own.
    """
    return hmac.new(
        settings.SECRET_KEY.encode(), code.encode(), "sha256"
    ).hexdigest()


def create_email_verification(
    *, session: Session, user: User
) -> tuple[str, str]:
    """Issue a fresh code and link token for the user's current email.

    Returns the code and the token, which the caller emails. Any earlier
    code stops working. Raises 429 when one was sent less than a minute
    ago, so the endpoint can't be used to flood an inbox.
    """
    now = utcnow()
    existing = user.email_verification
    if (
        existing is not None
        and (now - existing.created).total_seconds()
        < EMAIL_VERIFICATION_RESEND_SECONDS
    ):
        raise HTTPException(
            429, "A code was just sent. Wait a minute before asking again."
        )
    code = f"{secrets.randbelow(10**6):06d}"
    expires = now + timedelta(minutes=EMAIL_VERIFICATION_CODE_MINUTES)
    if existing is None:
        existing = UserEmailVerification(
            user_id=user.id,
            code_hash=hash_email_verification_code(code),
            expires=expires,
        )
    else:
        existing.code_hash = hash_email_verification_code(code)
        existing.created = now
        existing.expires = expires
        existing.attempts = 0
    session.add(existing)
    session.commit()
    session.refresh(user)
    token = generate_email_verification_token(
        user_id=user.id, email=user.email
    )
    return code, token


def mark_email_verified(*, session: Session, user: User) -> User:
    """Record that the user's current email is theirs, once."""
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
        session.add(user)
    if user.email_verification is not None:
        session.delete(user.email_verification)
    session.commit()
    session.refresh(user)
    return user


def confirm_email_verification_code(
    *, session: Session, user: User, code: str
) -> User:
    """Check an entered code and, if it's right, mark the email verified.

    A wrong code counts as an attempt; past the limit the code is thrown
    away and a new one has to be requested, which is what keeps guessing
    all million of them from being an option.
    """
    pending = user.email_verification
    if pending is None:
        raise HTTPException(400, "No verification code has been sent")
    if pending.expires < utcnow():
        session.delete(pending)
        session.commit()
        raise HTTPException(400, "That code has expired; request a new one")
    if not hmac.compare_digest(
        pending.code_hash, hash_email_verification_code(code.strip())
    ):
        pending.attempts += 1
        if pending.attempts >= EMAIL_VERIFICATION_MAX_ATTEMPTS:
            session.delete(pending)
            session.commit()
            raise HTTPException(400, "Too many wrong codes; request a new one")
        session.add(pending)
        session.commit()
        raise HTTPException(400, "That code isn't right")
    return mark_email_verified(session=session, user=user)


def confirm_email_verification_token(*, session: Session, token: str) -> User:
    """Mark an email verified from the link in the message, without login.

    The token names the user and the address it was sent to; an address
    changed since then leaves the old link proving nothing about the new
    one, so the two have to still match.
    """
    claims = verify_email_verification_token(token)
    if claims is None:
        raise HTTPException(400, "This link is invalid or has expired")
    user_id, email = claims
    user = session.get(User, user_id)
    if user is None or user.email.lower() != email.lower():
        raise HTTPException(400, "This link is invalid or has expired")
    if not user.is_active:
        raise HTTPException(400, "Inactive user")
    return mark_email_verified(session=session, user=user)


def link_github_account(
    *, session: Session, user: User, github_username: str
) -> None:
    """Attach a GitHub identity to an account.

    Only ``github_name`` changes: account names are immutable, since every
    project URL, configured DVC remote, and object storage path is keyed
    by them.
    """
    user.account.github_name = github_username
    session.add(user.account)
    session.commit()
    session.refresh(user)


def get_user_by_github_username(
    *, session: Session, github_username: str
) -> User | None:
    """Get a user by their GitHub username."""
    statement = (
        select(User)
        .join(Account)
        .where(Account.github_name == github_username)
    )
    session_user = session.exec(statement).first()
    return session_user


def authenticate(
    *, session: Session, email: str, password: str
) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        return None
    if not verify_password(password, db_user.hashed_password):
        return None
    return db_user


def get_github_token(session: Session, user: User) -> str:
    """Get a user's decrypted GitHub access token, automatically refreshing if
    necessary. Tries new UserExternalCredential table first, falls back to
    legacy UserGitHubToken.
    """

    def load_credential(lock: bool) -> UserExternalCredential | None:
        query = select(UserExternalCredential).where(
            UserExternalCredential.user_id == user.id,
            UserExternalCredential.provider == "github",
            UserExternalCredential.label == "default",
        )
        if lock:
            query = query.with_for_update()
        return session.exec(query).first()

    def refresh_due(credential: UserExternalCredential) -> bool:
        return (
            credential.expires is not None
            and (utcnow() + timedelta(minutes=30)) >= credential.expires
        )

    # Fast path: a plain read, deliberately not SELECT ... FOR UPDATE. That
    # lock is held until the request's session closes, and `get_repo` asks for
    # this token on every project read, so taking it here made every
    # concurrent request for this user queue behind whichever one was doing
    # the slowest Git/object-storage work -- a whole page's worth of requests
    # serializing on one row. Only the branches that write it need the lock.
    credential = load_credential(lock=False)
    if credential is not None and not refresh_due(credential):
        tokens = json.loads(decrypt_secret(credential.secret_payload))
        return tokens["access_token"]
    # Slow path: we're about to write, so re-read under the row lock and
    # re-check. Whoever held the lock ahead of us may have refreshed already,
    # and refreshing a second time would invalidate the token they just
    # stored. Expire first so the locked read repopulates the instance rather
    # than handing back the copy the identity map already holds.
    if credential is not None:
        session.expire(credential)
    credential = load_credential(lock=True)
    if credential is not None and not refresh_due(credential):
        tokens = json.loads(decrypt_secret(credential.secret_payload))
        return tokens["access_token"]
    # Fall back to legacy table if not in new system
    if credential is None:
        logger.info(
            f"No UserExternalCredential for {user.email}, checking legacy table"
        )
        legacy_query = (
            select(UserGitHubToken)
            .where(UserGitHubToken.user_id == user.id)
            .with_for_update()
        )
        legacy_token = session.exec(legacy_query).first()
        if legacy_token is None:
            logger.info(f"{user.email} has no GitHub token")
            raise HTTPException(401, "User needs to authenticate with GitHub")
        # Migrate from legacy to new system
        logger.info(
            f"Migrating {user.email} GitHub token to new credential system"
        )
        payload = json.dumps(
            {
                "access_token": decrypt_secret(legacy_token.access_token),
                "refresh_token": decrypt_secret(legacy_token.refresh_token),
            }
        )
        credential = save_external_credential(
            session=session,
            user=user,
            provider="github",
            secret_payload=payload,
            credential_type="oauth2",
            expires=legacy_token.expires,
            refresh_token_expires=legacy_token.refresh_token_expires,
        )
    if refresh_due(credential):
        logger.info(f"Refreshing GitHub token for {user.email}")
        tokens = json.loads(decrypt_secret(credential.secret_payload))
        resp = requests.post(
            "https://github.com/login/oauth/access_token",
            json=dict(
                client_id=settings.GH_CLIENT_ID,
                client_secret=settings.GH_CLIENT_SECRET,
                grant_type="refresh_token",
                refresh_token=tokens["refresh_token"],
            ),
            timeout=15,
        )
        logger.info(f"GitHub token refresh status code: {resp.status_code}")
        gh_resp = token_resp_text_to_dict(resp.text)
        logger.info(
            f"GitHub token refresh response keys: {list(gh_resp.keys())}"
        )
        # Handle failure
        if "error" in gh_resp:
            msg = (
                f"{gh_resp['error']}: "
                f"{gh_resp['error_description'].replace('+', ' ')}"
            )
            logger.error(msg)
            if gh_resp["error"] == "bad_refresh_token":
                logger.info(f"Bad refresh token for {user.email}")
                logger.info(f"Deleting bad GitHub credential for {user.email}")
                session.delete(credential)
                session.commit()
            raise HTTPException(401, "GitHub token refresh failed")
        # Save refreshed token
        save_github_token(session=session, user=user, github_resp=gh_resp)
    tokens = json.loads(decrypt_secret(credential.secret_payload))
    return tokens["access_token"]


def save_github_token(
    session: Session, user: User, github_resp: dict
) -> UserExternalCredential:
    """Save GitHub OAuth token to new UserExternalCredential table."""
    now = utcnow()
    expires = now + timedelta(seconds=int(github_resp["expires_in"]))
    rt_expires = now + timedelta(
        seconds=int(github_resp["refresh_token_expires_in"])
    )
    payload = json.dumps(
        {
            "access_token": github_resp["access_token"],
            "refresh_token": github_resp["refresh_token"],
        }
    )
    return save_external_credential(
        session=session,
        user=user,
        provider="github",
        secret_payload=payload,
        credential_type="oauth2",
        expires=expires,
        refresh_token_expires=rt_expires,
    )


def get_zenodo_token(session: Session, user: User) -> str:
    """Get a user's decrypted Zenodo token, automatically refreshing if
    necessary. Tries new UserExternalCredential table first, falls back to
    legacy UserZenodoToken.
    """
    # Try new credential system first
    query = (
        select(UserExternalCredential)
        .where(
            UserExternalCredential.user_id == user.id,
            UserExternalCredential.provider == "zenodo",
            UserExternalCredential.label == "default",
        )
        .with_for_update()
    )
    credential = session.exec(query).first()
    # Fall back to legacy table if not in new system
    if credential is None:
        logger.info(
            f"No UserExternalCredential for {user.email}, checking legacy "
            "Zenodo table"
        )
        if user.zenodo_token is None:
            raise HTTPException(401, "User needs to authenticate with Zenodo")
        # Migrate from legacy to new system
        logger.info(
            f"Migrating {user.email} Zenodo token to new credential system"
        )
        payload = json.dumps(
            {
                "access_token": decrypt_secret(user.zenodo_token.access_token),
                "refresh_token": decrypt_secret(
                    user.zenodo_token.refresh_token
                ),
            }
        )
        credential = save_external_credential(
            session=session,
            user=user,
            provider="zenodo",
            secret_payload=payload,
            credential_type="oauth2",
            expires=user.zenodo_token.expires,
            refresh_token_expires=user.zenodo_token.refresh_token_expires,
        )
    # Check if refresh needed
    needs_refresh = (
        credential.expires is not None and credential.expires <= utcnow()
    )
    if needs_refresh:
        logger.info(f"Refreshing Zenodo token for {user.email}")
        tokens = json.loads(decrypt_secret(credential.secret_payload))
        resp = requests.post(
            ZENODO_AUTH_URL,
            data=dict(
                client_id=settings.ZENODO_CLIENT_ID,
                client_secret=settings.ZENODO_CLIENT_SECRET,
                grant_type="refresh_token",
                refresh_token=tokens["refresh_token"],
            ),
            timeout=15,
        )
        logger.info(f"Refreshed Zenodo token; status code: {resp.status_code}")
        try:
            zenodo_resp = resp.json()
        except JSONDecodeError:
            zenodo_resp = {}
        logger.info(f"Zenodo token response keys: {list(zenodo_resp.keys())}")
        # Handle failure
        if resp.status_code != 200:
            msg = zenodo_resp.get("error", "Failed to authenticate")
            logger.error(
                f"Failed to refresh Zenodo token for {user.email}: {msg}"
            )
            # Delete credential if refresh token is invalid
            if zenodo_resp.get("error") == "invalid_grant":
                logger.info(
                    f"Deleting invalid Zenodo credential for {user.email}"
                )
                session.delete(credential)
                session.commit()
            raise HTTPException(
                401,
                "Zenodo token refresh failed. Please reconnect your account.",
            )
        save_zenodo_token(session, user=user, zenodo_resp=zenodo_resp)
        # Re-fetch the updated credential
        credential = session.exec(query).first()
        if credential is None:
            raise HTTPException(500, "Failed to save Zenodo token")
    tokens = json.loads(decrypt_secret(credential.secret_payload))
    return tokens["access_token"]


def save_zenodo_token(session: Session, user: User, zenodo_resp: dict):
    """Save Zenodo OAuth token to UserExternalCredential table."""
    now = utcnow()
    expires = now + timedelta(seconds=int(zenodo_resp["expires_in"]))
    payload = json.dumps(
        {
            "access_token": zenodo_resp["access_token"],
            "refresh_token": zenodo_resp["refresh_token"],
        }
    )
    save_external_credential(
        session=session,
        user=user,
        provider="zenodo",
        secret_payload=payload,
        credential_type="oauth2",
        expires=expires,
    )


def get_overleaf_token(session: Session, user: User) -> str:
    """Get a user's decrypted Overleaf token. Tries new UserExternalCredential
    table first, falls back to legacy UserOverleafToken.
    """
    # Try new credential system first
    credential = get_external_credential(
        session=session,
        user=user,
        provider="overleaf",
        label="default",
    )
    # Fall back to legacy table if not in new system
    if credential is None:
        logger.info(
            f"No UserExternalCredential for {user.email}, checking legacy "
            "Overleaf table"
        )
        if user.overleaf_token is None:
            raise HTTPException(404, "User has no Overleaf token saved")
        # Migrate from legacy to new system
        logger.info(
            f"Migrating {user.email} Overleaf token to new credential system"
        )
        payload = json.dumps(
            {
                "access_token": decrypt_secret(
                    user.overleaf_token.access_token
                ),
            }
        )
        credential = save_external_credential(
            session=session,
            user=user,
            provider="overleaf",
            secret_payload=payload,
            credential_type="pat",
            expires=user.overleaf_token.expires,
        )
    tokens = json.loads(decrypt_secret(credential.secret_payload))
    return tokens["access_token"]


def save_overleaf_token(
    session: Session, user: User, token: str, expires: datetime | None
):
    """Save Overleaf PAT to UserExternalCredential table."""
    payload = json.dumps({"access_token": token})
    save_external_credential(
        session=session,
        user=user,
        provider="overleaf",
        secret_payload=payload,
        credential_type="pat",
        expires=expires,
    )


def get_google_token(session: Session, user: User) -> str:
    """Get a user's decrypted Google access token, automatically refreshing if
    necessary.
    """
    credential = get_external_credential(
        session=session,
        user=user,
        provider="google",
        label="default",
    )
    if credential is None:
        raise HTTPException(401, "User needs to authenticate with Google")
    # Check if refresh needed
    needs_refresh = (
        credential.expires is not None
        and (utcnow() + timedelta(minutes=5)) >= credential.expires
    )
    if needs_refresh:
        logger.info(f"Refreshing Google token for {user.email}")
        tokens = json.loads(decrypt_secret(credential.secret_payload))
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data=dict(
                client_id=settings.GOOGLE_CLIENT_ID,
                client_secret=settings.GOOGLE_CLIENT_SECRET,
                grant_type="refresh_token",
                refresh_token=tokens["refresh_token"],
            ),
            timeout=15,
        )
        logger.info(f"Google token refresh status code: {resp.status_code}")
        # Handle failure
        if resp.status_code != 200:
            try:
                error_data = resp.json()
                msg = error_data.get(
                    "error_description", "Failed to refresh token"
                )
                error_code = error_data.get("error")
            except Exception:
                msg = "Failed to refresh token"
                error_code = None
            logger.error(
                f"Failed to refresh Google token for {user.email}: {msg}"
            )
            # Delete credential if refresh token is invalid
            if error_code in ["invalid_grant", "invalid_token"]:
                logger.info(
                    f"Deleting invalid Google credential for {user.email}"
                )
                session.delete(credential)
                session.commit()
            raise HTTPException(
                401,
                "Google token refresh failed. Please reconnect your account.",
            )
        google_resp = resp.json()
        # Preserve existing refresh_token if Google doesn't return a new one
        if "refresh_token" not in google_resp:
            tokens = json.loads(decrypt_secret(credential.secret_payload))
            google_resp["refresh_token"] = tokens.get("refresh_token")
        save_google_token(session=session, user=user, google_resp=google_resp)
        # Re-fetch the updated credential
        credential = get_external_credential(
            session=session,
            user=user,
            provider="google",
            label="default",
        )
        if credential is None:
            raise HTTPException(500, "Failed to save Google token")
    tokens = json.loads(decrypt_secret(credential.secret_payload))
    return tokens["access_token"]


def save_google_token(
    session: Session,
    user: User,
    google_resp: dict[str, Any],
    verified_email: str | None = None,
) -> None:
    """Save Google OAuth token to UserExternalCredential table.

    Preserves existing refresh_token when Google doesn't return a new one
    (Google often omits refresh_token on subsequent authorizations).

    ``verified_email`` is the address Google reported as verified, when the
    caller fetched the profile and checked it. It's kept on the credential
    as what this account has proven about its email, and is carried over
    rather than cleared when a later save doesn't know it.
    """
    now = utcnow()
    # Google's expires_in is in seconds
    expires = now + timedelta(seconds=int(google_resp["expires_in"]))
    existing_cred = get_external_credential(
        session=session,
        user=user,
        provider="google",
        label="default",
    )
    # Preserve existing refresh_token if not provided in response
    refresh_token = google_resp.get("refresh_token")
    if not refresh_token and existing_cred:
        try:
            existing_tokens = json.loads(
                decrypt_secret(existing_cred.secret_payload)
            )
            refresh_token = existing_tokens.get("refresh_token")
        except Exception:
            pass
    if verified_email is None and existing_cred is not None:
        verified_email = existing_cred.provider_account_id
    payload = json.dumps(
        {
            "access_token": google_resp["access_token"],
            "refresh_token": refresh_token,
        }
    )
    save_external_credential(
        session=session,
        user=user,
        provider="google",
        secret_payload=payload,
        credential_type="oauth2",
        provider_account_id=verified_email,
        expires=expires,
    )


def save_zotero_request_token(
    session: Session, user: User, request_token: dict[str, str]
) -> None:
    """Stash an in-progress Zotero OAuth 1.0a request token.

    Its secret is needed to sign the access token request once the user comes
    back from Zotero, and must never reach the browser, so it's kept against
    the user under a separate label until the flow finishes.
    """
    payload = json.dumps(
        {
            "oauth_token": request_token["oauth_token"],
            "oauth_token_secret": request_token["oauth_token_secret"],
        }
    )
    save_external_credential(
        session=session,
        user=user,
        provider="zotero",
        secret_payload=payload,
        credential_type="oauth1_request",
        label="pending",
    )


def get_zotero_request_token(session: Session, user: User) -> dict[str, str]:
    """Read a user's stashed Zotero request token."""
    credential = get_external_credential(
        session=session,
        user=user,
        provider="zotero",
        label="pending",
    )
    if credential is None:
        raise HTTPException(400, "No Zotero authorization is in progress")
    return json.loads(decrypt_secret(credential.secret_payload))


def get_zotero_api_key(session: Session, user: User) -> str:
    """Get a user's decrypted Zotero API key.

    Zotero's OAuth 1.0a keys don't expire, so there's nothing to refresh.
    """
    credential = get_external_credential(
        session=session,
        user=user,
        provider="zotero",
        label="default",
    )
    if credential is None:
        raise HTTPException(401, "User needs to authenticate with Zotero")
    payload = json.loads(decrypt_secret(credential.secret_payload))
    return payload["api_key"]


def get_zotero_api_key_and_user_id(
    session: Session, user: User
) -> tuple[str, str]:
    """Get a user's Zotero API key together with their Zotero user ID.

    The user ID (Zotero's ``userID``, stored as ``provider_account_id``) is the
    library ID for their personal library and is needed to list their groups.
    """
    credential = get_external_credential(
        session=session,
        user=user,
        provider="zotero",
        label="default",
    )
    if credential is None or credential.provider_account_id is None:
        raise HTTPException(401, "User needs to authenticate with Zotero")
    payload = json.loads(decrypt_secret(credential.secret_payload))
    return payload["api_key"], credential.provider_account_id


def save_zotero_api_key(
    session: Session, user: User, zotero_resp: dict[str, str]
) -> None:
    """Save the API key Zotero returns from the access token step.

    The request token that earned the key is spent at this point, so it's
    cleared here too.
    """
    pending = get_external_credential(
        session=session,
        user=user,
        provider="zotero",
        label="pending",
    )
    if pending is not None:
        session.delete(pending)
        session.commit()
    payload = json.dumps({"api_key": zotero_resp["oauth_token_secret"]})
    save_external_credential(
        session=session,
        user=user,
        provider="zotero",
        secret_payload=payload,
        credential_type="oauth1",
        provider_account_id=str(zotero_resp["userID"]),
        metadata_json={"username": zotero_resp.get("username")},
    )


def check_user_subscription_active(session: Session, user: User) -> bool:
    logger.info(f"Checking subscription for {user.email}")
    subscription = user.subscription
    if subscription is None:
        logger.info(f"{user.email} has no subscription")
        return False
    if subscription.plan_id == 0:
        logger.info(f"{user.email} has a free subscription")
        return True
    if (
        subscription.paid_until is not None
        and subscription.paid_until >= utcnow()
    ):
        return True
    # Check with Stripe if the subscription has been paid
    customer = app.stripe.get_customer(email=user.email)
    if customer is None:
        return False
    stripe_subs = app.stripe.get_customer_subscriptions(
        customer_id=customer.id, status="active"
    )
    if not stripe_subs:
        return False
    sub_period_end_timestamps = [sub.current_period_end for sub in stripe_subs]
    subscription.paid_until = datetime.fromtimestamp(
        max(sub_period_end_timestamps)
    )
    session.commit()
    return True
