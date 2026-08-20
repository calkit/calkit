"""Functionality for working with users."""

import json
import logging
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
from app.models import (
    Account,
    User,
    UserCreate,
    UserExternalCredential,
    UserGitHubToken,
    UserSubscription,
    UserUpdate,
)
from app.security import (
    decrypt_secret,
    encrypt_secret,
    get_password_hash,
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
    if existing is not None:
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


def link_github_account(
    *, session: Session, user: User, github_username: str
) -> bool:
    """Attach a GitHub identity to an account, taking its name if free.

    Account name and GitHub username are separate fields, but everything a
    user types by hand -- ``calkit clone owner/project``, the project URL --
    goes through the account name, so two different names to remember is a
    papercut and a source of "why doesn't this work". Adopting the GitHub
    name at link time keeps them the same for accounts created some other
    way first.

    Only when the new name is free and the account owns no projects, since
    renaming is what every existing project URL and configured DVC remote
    points at. Returns whether the account was renamed.
    """
    user.account.github_name = github_username
    renamed = False
    desired = github_username.lower()
    if (
        user.account.name != desired
        and not user.account.owned_projects
        and desired not in (INVALID_ACCOUNT_NAMES + ORG_ONLY_ACCOUNT_NAMES)
        and session.exec(
            select(Account).where(Account.name == desired)
        ).first()
        is None
    ):
        logger.info(
            f"Renaming account {user.account.name} to {desired} on GitHub link"
        )
        user.account.name = desired
        user.account.display_name = github_username
        renamed = True
    session.add(user.account)
    session.commit()
    session.refresh(user)
    return renamed


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


def save_google_token(session: Session, user: User, google_resp: dict):
    """Save Google OAuth token to UserExternalCredential table.

    Preserves existing refresh_token when Google doesn't return a new one
    (Google often omits refresh_token on subsequent authorizations).
    """
    now = utcnow()
    # Google's expires_in is in seconds
    expires = now + timedelta(seconds=int(google_resp["expires_in"]))
    # Preserve existing refresh_token if not provided in response
    refresh_token = google_resp.get("refresh_token")
    if not refresh_token:
        # Try to get existing refresh_token
        existing_cred = get_external_credential(
            session=session,
            user=user,
            provider="google",
            label="default",
        )
        if existing_cred:
            try:
                existing_tokens = json.loads(
                    decrypt_secret(existing_cred.secret_payload)
                )
                refresh_token = existing_tokens.get("refresh_token")
            except Exception:
                pass
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
