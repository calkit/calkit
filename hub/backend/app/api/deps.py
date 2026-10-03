"""Dependencies to use in API routes."""

import logging
import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session, select

import app.stripe as stripe
from app import security
from app.config import settings
from app.core import utcnow
from app.db import engine
from app.models import RefreshToken, TokenPayload, User, UserToken
from app.security import (
    hash_token_verifier,
    verify_token_verifier,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl="/login/access-token", auto_error=True
)
reusable_oauth2_optional = OAuth2PasswordBearer(
    tokenUrl="/login/access-token", auto_error=False
)

PAT_SELECTOR_LENGTH_BYTES = 8
PAT_VERIFIER_LENGTH_BYTES = 24
PAT_SELECTOR_END_CHAR_IDX = 4 + PAT_SELECTOR_LENGTH_BYTES * 2


# How stale a token's last_used may get before a request rewrites it. The
# field answers "is this token still in use", which nothing needs to the
# second, and without a floor every authenticated request would carry a
# write to the same row.
TOKEN_LAST_USED_RESOLUTION_SECONDS = 300


def touch_token(session: Session, token: UserToken) -> None:
    """Record that a token was just used to authenticate."""
    now = utcnow()
    if (
        token.last_used is not None
        and (now - token.last_used).total_seconds()
        < TOKEN_LAST_USED_RESOLUTION_SECONDS
    ):
        return
    token.last_used = now
    session.add(token)
    # Committing would normally expire everything loaded, and the next read
    # of the token's user would go back to the database for a row fetched a
    # moment ago. Nothing else is pending this early in a request, so the
    # loaded state is kept across the commit.
    expire = session.expire_on_commit
    session.expire_on_commit = False
    try:
        session.commit()
    finally:
        session.expire_on_commit = expire


def verify_pat(session: Session, token: UserToken, verifier: str) -> bool:
    """Check a personal access token's secret half.

    Tokens from before hashing switched to SHA-256 have bcrypt hashes, so
    they're rehashed on first use, and only that request pays for bcrypt.
    """
    hashed = token.hashed_verifier
    if hashed is None or not verify_token_verifier(verifier, hashed):
        return False
    if hashed.startswith("$2"):
        token.hashed_verifier = hash_token_verifier(verifier)
        session.add(token)
        session.commit()
    return True


def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]
OptionalTokenDep = Annotated[str | None, Depends(reusable_oauth2_optional)]


def get_current_user(session: SessionDep, token: TokenDep) -> User:
    # Handle personal access tokens, which start with 'ckp_'
    if token.startswith("ckp_"):
        # Try to find the token in the database by its selector
        selector = token[4:PAT_SELECTOR_END_CHAR_IDX]
        verifier = token[PAT_SELECTOR_END_CHAR_IDX:]
        token_in_db = session.exec(
            select(UserToken).where(UserToken.selector == selector)
        ).first()
        if token_in_db is None:
            logger.info(f"PAT not found in database (selector: {selector})")
            raise HTTPException(403, "Invalid token")
        else:
            if not token_in_db.is_active:
                raise HTTPException(403, "Token has been deactivated")
            # Check expiration
            if token_in_db.expired:
                raise HTTPException(403, "Token has expired")
            # Check verifier
            if token_in_db.hashed_verifier is None:
                raise HTTPException(403, "Invalid token")
            if not verify_pat(session, token_in_db, verifier):
                raise HTTPException(403, "Invalid token")
            # A scoped token, e.g., one for DVC that's written into a
            # project's DVC config, only works where its scope is asked for
            if token_in_db.scope is not None:
                raise HTTPException(403, "Invalid token scope")
            touch_token(session, token_in_db)
            user = token_in_db.user
    else:
        # This is a regular JWT
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
            )
            token_data = TokenPayload(**payload)
            token_scope = payload.get("scope")
            if token_scope is not None:
                raise HTTPException(403, "Invalid token scope")
            # Tokens for emailed links, e.g., to verify an address, aren't
            # logins
            if "purpose" in payload:
                raise HTTPException(403, "Invalid token")
            if "token_id" in payload:
                token_id = payload["token_id"]
                token_in_db = session.get(UserToken, token_id)
                if token_in_db is None:
                    raise HTTPException(403, "Token invalid")
                if not token_in_db.is_active:
                    raise HTTPException(403, "Token has been deactivated")
                touch_token(session, token_in_db)
                user = token_in_db.user
            else:
                user = session.get(User, token_data.sub)
        except (InvalidTokenError, ValidationError):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Could not validate credentials",
            )
    if not user:
        # The token parsed and verified but names a user that no longer
        # exists (deleted account, restored database, wrong instance).
        # That's the credential failing, not a missing resource, so send
        # the detail clients already treat as "log out" -- a 404 here
        # leaves them retrying a request that can never succeed.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    # Ensure a non-free subscription is valid, including a $0 comp with an
    # end date, since quotas read the plan without checking paid_until; a
    # comp with no end date runs indefinitely
    sub = user.subscription
    if (
        sub is not None
        and sub.plan_id != 0
        and not (sub.price == 0 and sub.paid_until is None)
    ):
        # Drop to free if payment hasn't been received in 5 minutes since
        # the transaction started, or the paid period has lapsed
        if (
            user.subscription.paid_until is None
            and ((utcnow() - user.subscription.created).total_seconds() > 300)
        ) or (
            user.subscription.paid_until is not None
            and user.subscription.paid_until < utcnow()
        ):
            logger.info(f"Checking subscription for {user.email}")
            stripe_subs = [
                sub
                for cust in stripe.get_user_customers(user)
                for sub in stripe.get_customer_subscriptions(
                    customer_id=cust.id, status="active"
                )
            ]
            sub_valid = False
            for sub in stripe_subs:
                if sub.current_period_end > utcnow().timestamp():
                    logger.info("Found valid subscription")
                    user.subscription.paid_until = datetime.fromtimestamp(
                        sub.current_period_end
                    )
                    user.subscription.processor_subscription_id = sub.id
                    session.commit()
                    session.refresh(user)
                    sub_valid = True
            if not sub_valid:
                logger.info("Reverting invalid subscription to free")
                # Rather than deleting, since quotas need a subscription
                subscription = user.subscription
                subscription.plan_id = 0
                subscription.price = 0.0
                subscription.period_months = 1
                subscription.paid_until = None
                subscription.processor = None
                subscription.processor_product_id = None
                subscription.processor_price_id = None
                subscription.processor_subscription_id = None
                session.commit()
                session.refresh(user)
    return user


def get_current_user_with_token_scope(
    session: SessionDep, token: TokenDep, scope: str | None = None
) -> User:
    # Handle personal access tokens, which start with 'ckp_'
    if token.startswith("ckp_"):
        # Try to find the token in the database by its selector
        selector = token[4:PAT_SELECTOR_END_CHAR_IDX]
        verifier = token[PAT_SELECTOR_END_CHAR_IDX:]
        token_in_db = session.exec(
            select(UserToken).where(UserToken.selector == selector)
        ).first()
        if token_in_db is None:
            logger.info(f"PAT not found in database (selector: {selector})")
            raise HTTPException(403, "Invalid token")
        else:
            if not token_in_db.is_active:
                raise HTTPException(403, "Token has been deactivated")
            # Check expiration
            if token_in_db.expired:
                raise HTTPException(403, "Token has expired")
            # Check verifier
            if token_in_db.hashed_verifier is None:
                raise HTTPException(403, "Invalid token")
            # Check scope
            if token_in_db.scope is not None and token_in_db.scope != scope:
                raise HTTPException(403, "Invalid token scope")
            if not verify_pat(session, token_in_db, verifier):
                raise HTTPException(403, "Invalid token")
            touch_token(session, token_in_db)
            user = token_in_db.user
    else:
        # This is a regular JWT
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
            )
            token_data = TokenPayload(**payload)
            token_scope = payload.get("scope")
            if token_scope is not None and token_scope != scope:
                raise HTTPException(403, "Invalid token scope")
            if "token_id" in payload:
                token_id = payload["token_id"]
                token_in_db = session.get(UserToken, token_id)
                if token_in_db is None:
                    raise HTTPException(403, "Token invalid")
                if not token_in_db.is_active:
                    raise HTTPException(403, "Token has been deactivated")
                if token_in_db.expired:
                    raise HTTPException(403, "Token has expired")
                touch_token(session, token_in_db)
                user = token_in_db.user
            else:
                user = session.get(User, token_data.sub)
        except (InvalidTokenError, ValidationError):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Could not validate credentials",
            )
    if not user:
        # The token parsed and verified but names a user that no longer
        # exists (deleted account, restored database, wrong instance).
        # That's the credential failing, not a missing resource, so send
        # the detail clients already treat as "log out" -- a 404 here
        # leaves them retrying a request that can never succeed.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


def get_current_user_optional(
    session: SessionDep, token: OptionalTokenDep
) -> User | None:
    if token is None:
        return
    return get_current_user(session=session, token=token)


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass
class SignedIn:
    """A person signed in through the web app, and which sign-in it is."""

    user: User
    session_id: uuid.UUID


def get_current_session(session: SessionDep, token: TokenDep) -> SignedIn:
    """Authenticate a person signed in through the web app.

    Some actions, e.g., opening a shell on a user's machine or managing
    their second factor, shouldn't be possible with a credential that can
    end up in a CI secret, a config file, or a third party's hands, so only
    access tokens from an interactive sign-in whose session is still live
    count. Personal access tokens, CLI and CI logins, and link tokens are
    all refused, and ending the session, e.g., by changing the password,
    ends this too.
    """
    refused = HTTPException(403, "This requires signing in, not a token")
    if token.startswith("ckp_"):
        raise refused
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        session_id = uuid.UUID(payload["sid"])
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        raise refused
    if "token_id" in payload:
        raise refused
    user = get_current_user(session, token)
    live = session.exec(
        select(RefreshToken)
        .where(RefreshToken.session_id == session_id)
        .where(RefreshToken.user_id == user.id)
        .where(RefreshToken.interactive)
        .where(RefreshToken.is_active)
        .where(RefreshToken.expires > utcnow())
    ).first()
    if live is None:
        raise refused
    return SignedIn(user=user, session_id=session_id)


CurrentSession = Annotated[SignedIn, Depends(get_current_session)]


def get_current_session_user(signed_in: CurrentSession) -> User:
    return signed_in.user


SessionUser = Annotated[User, Depends(get_current_session_user)]
CurrentUserDvcScope = Annotated[
    User, Depends(partial(get_current_user_with_token_scope, scope="dvc"))
]
CurrentUserOptional = Annotated[
    User | None, Depends(get_current_user_optional)
]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user
