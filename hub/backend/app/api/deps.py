"""Dependencies to use in API routes."""

import logging
from collections.abc import Generator
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
from app.models import TokenPayload, User, UserToken
from app.security import verify_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token", auto_error=True
)
reusable_oauth2_optional = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token", auto_error=False
)

PAT_SELECTOR_LENGTH_BYTES = 8
PAT_VERIFIER_LENGTH_BYTES = 24
PAT_SELECTOR_END_CHAR_IDX = 4 + PAT_SELECTOR_LENGTH_BYTES * 2


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
            if not verify_password(verifier, token_in_db.hashed_verifier):
                raise HTTPException(403, "Invalid token")
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
            if "token_id" in payload:
                token_id = payload["token_id"]
                token_in_db = session.get(UserToken, token_id)
                if token_in_db is None:
                    raise HTTPException(403, "Token invalid")
                if not token_in_db.is_active:
                    raise HTTPException(403, "Token has been deactivated")
                user = token_in_db.user
            else:
                user = session.get(User, token_data.sub)
        except (InvalidTokenError, ValidationError):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Could not validate credentials",
            )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    # Ensure that if this user has a paid subscription, it is valid
    if user.subscription is not None and user.subscription.price > 0:
        # Delete subscription if payment hasn't been received in 5 minutes
        # since transaction started
        if (
            user.subscription.paid_until is None
            and ((utcnow() - user.subscription.created).total_seconds() > 300)
        ) or (
            user.subscription.paid_until is not None
            and user.subscription.paid_until < utcnow()
        ):
            logger.info(f"Checking subscription for {user.email}")
            stripe_cust = stripe.get_customer(user.email)
            if stripe_cust is not None:
                stripe_subs = stripe.get_customer_subscriptions(
                    customer_id=stripe_cust.id, status="active"
                )
            else:
                logger.info(f"No Stripe customer exists for {user.email}")
                stripe_subs = []
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
                logger.info("Deleting invalid subscription")
                session.delete(user.subscription)
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
            if not verify_password(verifier, token_in_db.hashed_verifier):
                raise HTTPException(403, "Invalid token")
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
                user = token_in_db.user
            else:
                user = session.get(User, token_data.sub)
        except (InvalidTokenError, ValidationError):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Could not validate credentials",
            )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
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
