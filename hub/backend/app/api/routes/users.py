"""Routes for users."""

import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Literal, Sequence

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import DataError
from sqlmodel import Field, func, select

import app.stripe
from app import mixpanel, users, zotero
from app.api.deps import (
    PAT_SELECTOR_LENGTH_BYTES,
    PAT_VERIFIER_LENGTH_BYTES,
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
from app.config import settings
from app.core import utcnow
from app.messaging import generate_new_account_email, send_email
from app.models import (
    DiscountCode,
    Message,
    UpdateSubscriptionResponse,
    StorageUsage,
    SubscriptionUpdate,
    Token,
    UpdatePassword,
    User,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserSubscription,
    UserToken,
    UserTokenPublic,
    UserUpdate,
    UserUpdateMe,
)
from app.security import (
    get_password_hash,
    verify_password,
)
from app.storage import get_storage_usage
from app.subscriptions import PLAN_IDS, get_monthly_price
from app.zenodo import AUTH_URL as ZENODO_AUTH_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/users", dependencies=[Depends(get_current_active_superuser)])
def read_users(
    session: SessionDep, skip: int = 0, limit: int = 100
) -> UsersPublic:
    """Retrieve users."""
    count_statement = select(func.count()).select_from(User)
    count = session.exec(count_statement).one()
    statement = select(User).offset(skip).limit(limit)
    users = session.exec(statement).all()
    return UsersPublic(data=users, count=count)


@router.post("/users", dependencies=[Depends(get_current_active_superuser)])
def create_user(*, session: SessionDep, user_in: UserCreate) -> UserPublic:
    """Create new user."""
    user = users.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )
    user = users.create_user(session=session, user_create=user_in)
    if settings.emails_enabled and user_in.email:
        email_data = generate_new_account_email(
            email_to=user_in.email,
            username=user_in.email,
            password=user_in.password,
        )
        send_email(
            email_to=user_in.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return user


@router.patch("/user")
def update_current_user(
    *, session: SessionDep, user_in: UserUpdateMe, current_user: CurrentUser
) -> UserPublic:
    """Update own user."""
    if user_in.email:
        existing_user = users.get_user_by_email(
            session=session, email=user_in.email
        )
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
    user_data = user_in.model_dump(exclude_unset=True)
    current_user.sqlmodel_update(user_data)
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user


@router.patch("/user/password")
def update_current_user_password(
    *, session: SessionDep, body: UpdatePassword, current_user: CurrentUser
) -> Message:
    """Update own password."""
    if not verify_password(
        body.current_password, current_user.hashed_password
    ):
        raise HTTPException(status_code=400, detail="Incorrect password")
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=400,
            detail="New password cannot be the same as the current one",
        )
    hashed_password = get_password_hash(body.new_password)
    current_user.hashed_password = hashed_password
    session.add(current_user)
    session.commit()
    return Message(message="Password updated successfully")


@router.get("/user")
def get_current_user(current_user: CurrentUser) -> UserPublic:
    """Get current user."""
    return UserPublic.model_validate(current_user)


@router.delete("/user")
def delete_current_user(
    session: SessionDep, current_user: CurrentUser
) -> Message:
    """Delete own user."""
    if current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="Super users are not allowed to delete themselves",
        )
    # TODO: If the user has a paid subscription, cancel it
    # TODO: If they user is the owner of any orgs, delete them and cancel
    # their subscriptions, if applicable
    session.delete(current_user)
    session.commit()
    return Message(message="User deleted successfully")


@router.post("/users/signup")
def register_user(session: SessionDep, user_in: UserRegister) -> UserPublic:
    """Create a new user with email + password, without a GitHub account.

    Such users can collaborate on projects (e.g. via invite links) but cannot
    own projects until git hosting is decoupled from GitHub.
    """
    user = users.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="A user with this email already exists in the system",
        )
    user_create = UserCreate.model_validate(user_in)
    user = users.create_user(session=session, user_create=user_create)
    return user


@router.get("/users/{user_id}")
def read_user_by_id(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> UserPublic:
    """Get a specific user by ID."""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404)
    if user == current_user:
        return UserPublic.model_validate(user)
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges",
        )
    return UserPublic.model_validate(user)


@router.patch(
    "/users/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
)
def update_user(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    user_in: UserUpdate,
) -> UserPublic:
    """Update a user."""
    db_user = session.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=404,
            detail="A user with this ID does not exist in the system",
        )
    if user_in.email:
        existing_user = users.get_user_by_email(
            session=session, email=user_in.email
        )
        if existing_user and existing_user.id != user_id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
    db_user = users.update_user(
        session=session, db_user=db_user, user_in=user_in
    )
    return db_user


@router.delete(
    "/users/{user_id}", dependencies=[Depends(get_current_active_superuser)]
)
def delete_user(
    session: SessionDep, current_user: CurrentUser, user_id: uuid.UUID
) -> Message:
    """Delete a user."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user == current_user:
        raise HTTPException(
            status_code=403,
            detail="Super users are not allowed to delete themselves",
        )
    session.delete(user)
    session.commit()
    return Message(message="User deleted successfully")


@router.get("/user/github/repos")
def get_user_github_repos(
    session: SessionDep,
    current_user: CurrentUser,
    per_page: int = 30,
    page: int = 1,
) -> list[dict]:
    # See https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28#list-repositories-for-the-authenticated-user
    access_token = users.get_github_token(session=session, user=current_user)
    url = "https://api.github.com/user/repos"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(
        url, headers=headers, params=dict(page=page, per_page=per_page)
    )
    if not resp.status_code == 200:
        raise HTTPException(400, f"GitHub request failed: {resp.text}")
    return resp.json()


@router.put("/user/subscription")
def put_user_subscription(
    req: SubscriptionUpdate, current_user: CurrentUser, session: SessionDep
) -> UpdateSubscriptionResponse:
    current_subscription = current_user.subscription
    plan_id = PLAN_IDS[req.plan_name]
    discount_code = None
    period_months = 1 if req.period == "monthly" else 12
    if req.discount_code is not None:
        try:
            discount_code = session.get(DiscountCode, req.discount_code)
            if (
                discount_code is not None
                and discount_code.redeemed is not None
            ):
                raise HTTPException(
                    400, "Discount code has already been redeemed"
                )
        except DataError:
            logger.info("User provided invalid discount code")
    if discount_code is not None:
        price = discount_code.price
        months = discount_code.months % 12
        years = months // 12
        today = utcnow().date()
        paid_until = datetime(
            today.year + years, today.month + months, today.day
        )
        discount_code.redeemed = utcnow()
        discount_code.redeemed_by_user_id = current_user.id
    else:
        price = get_monthly_price(req.plan_name, period=req.period)
        paid_until = None
    new_subscription = UserSubscription(
        user_id=current_user.id,
        period_months=period_months,
        plan_id=plan_id,
        price=price,
        paid_until=paid_until,
    )
    # If we're not making any change to the subscription, we can return
    if current_subscription is not None and (
        new_subscription.period_months == current_subscription.period_months
        and new_subscription.plan_id == current_subscription.plan_id
        and new_subscription.price == current_subscription.price
        and new_subscription.paid_until == current_subscription.paid_until
    ):
        return UpdateSubscriptionResponse(
            subscription=current_subscription,
            stripe_session_client_secret=None,
        )
    session_secret = None
    stripe_changing = (
        current_subscription is not None
        and (
            new_subscription.period_months
            != current_subscription.period_months
            or new_subscription.plan_id != current_subscription.plan_id
            or new_subscription.price != current_subscription.price
            or new_subscription.paid_until != current_subscription.paid_until
        )
    ) or (current_subscription is None and price > 0)
    if stripe_changing:
        # We need to setup payment stuff in Stripe
        customer = app.stripe.get_customer(email=current_user.email)
        if customer is None:
            customer = app.stripe.create_customer(
                email=current_user.email,
                full_name=current_user.full_name,
                user_id=current_user.id,
            )
        # If the user already has any subscriptions, update them
        stripe_subs = app.stripe.get_customer_subscriptions(
            customer.id, status="active"
        )
        # Filter down for subscriptions without orgs in them
        stripe_subs = [s for s in stripe_subs if not s.metadata.get("org_id")]
        if len(stripe_subs) > 1:
            raise HTTPException(400, "User has multiple active subscriptions")
        # Get the Stripe price object for this plan
        stripe_price = app.stripe.get_price(plan_id=plan_id, period=req.period)
        if stripe_price is None and price > 0:
            raise HTTPException(400, "Stripe price not found")
        # If we have an active stripe subscription, update it
        if stripe_subs:
            stripe_sub = stripe_subs[0]
            # Update the subscription if price isn't zero
            if price > 0:
                app.stripe.update_subscription(
                    subscription_id=stripe_sub.id,
                    items=[
                        {
                            "id": stripe_sub["items"]["data"][0]["id"],
                            "price": stripe_price.id,  # type: ignore
                        },
                    ],
                    metadata=dict(user_id=current_user.id, plan_id=plan_id),
                )
                new_subscription.processor_price_id = stripe_price.id
                new_subscription.processor = "stripe"
            else:
                app.stripe.cancel_subscription(stripe_sub.id)
                new_subscription.processor = None
                new_subscription.processor_price_id = None
            session_secret = None
        elif price > 0:
            stripe_session = app.stripe.stripe.checkout.Session.create(
                client_reference_id=str(current_user.id),
                customer=customer.id,
                mode="subscription",
                line_items=[dict(price=stripe_price.id, quantity=1)],  # type: ignore
                ui_mode="embedded",
                return_url=settings.frontend_host,
                subscription_data={
                    "metadata": {
                        "user_id": current_user.id,
                        "plan_id": plan_id,
                    }
                },  # type: ignore
            )
            session_secret = stripe_session.client_secret
            new_subscription.processor_price_id = stripe_price.id
            new_subscription.processor = "stripe"
    current_user.subscription = new_subscription
    session.commit()
    session.refresh(current_user.subscription)
    return UpdateSubscriptionResponse(
        subscription=current_user.subscription,
        stripe_session_client_secret=session_secret,
    )


@router.get("/user/tokens")
def get_user_tokens(
    session: SessionDep,
    current_user: CurrentUser,
    is_active: bool | None = None,
) -> Sequence[UserTokenPublic]:
    query = select(UserToken).where(UserToken.user_id == current_user.id)
    if is_active is not None:
        query = query.where(UserToken.is_active == is_active)
    query = query.order_by(UserToken.created.desc())  # type: ignore
    tokens = session.exec(query).fetchall()
    return tokens


class TokenPost(BaseModel):
    expires_days: int = Field(ge=1, le=(365 * 3))
    scope: Literal["dvc"] | None
    description: str | None = None


class TokenResp(UserTokenPublic, Token):
    pass


@router.post("/user/tokens")
def post_user_token(
    session: SessionDep, current_user: CurrentUser, req: TokenPost
) -> TokenResp:
    # Generate a random token and hash it
    # Prepend 'ckp_' to indicate it's a Calkit user personal access token
    selector = secrets.token_hex(PAT_SELECTOR_LENGTH_BYTES)
    verifier = secrets.token_hex(PAT_VERIFIER_LENGTH_BYTES)
    token_str = f"ckp_{selector}{verifier}"
    hashed_verifier = get_password_hash(verifier)
    token = UserToken(
        user_id=current_user.id,
        expires=utcnow() + timedelta(days=req.expires_days),
        scope=req.scope,
        is_active=True,
        selector=selector,
        hashed_verifier=hashed_verifier,
        description=req.description,
    )
    session.add(token)
    session.commit()
    session.refresh(token)
    mixpanel.user_created_new_token(
        current_user, scope=req.scope, expires_days=req.expires_days
    )
    return TokenResp.model_validate(token, update=dict(access_token=token_str))


class TokenPatch(BaseModel):
    is_active: bool


@router.patch("/user/tokens/{token_id}")
def patch_user_token(
    session: SessionDep,
    current_user: CurrentUser,
    token_id: uuid.UUID,
    req: TokenPatch,
) -> UserTokenPublic:
    token = session.get(UserToken, token_id)
    if token is None:
        raise HTTPException(404)
    if token.user_id != current_user.id:
        raise HTTPException(403, "Not your token")
    token.is_active = req.is_active
    session.commit()
    session.refresh(token)
    return token


@router.delete("/user/tokens/{token_id}")
def delete_user_token(
    session: SessionDep, current_user: CurrentUser, token_id: uuid.UUID
) -> Message:
    token = session.get(UserToken, token_id)
    if token is None:
        raise HTTPException(404)
    if token.user_id != current_user.id:
        raise HTTPException(403, "Not your token")
    session.delete(token)
    session.commit()
    return Message(message="Token deleted successfully")


class GitHubInstallations(BaseModel):
    total_count: int
    installations: list[dict]


@router.get("/user/github-app-installations")
def get_user_github_app_installations(
    session: SessionDep, current_user: CurrentUser
) -> GitHubInstallations:
    token = users.get_github_token(session=session, user=current_user)
    url = "https://api.github.com/user/installations"
    logger.info(f"Making request to: {url}")
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    logger.info(f"Response status code from GitHub: {resp.status_code}")
    if resp.status_code != 200:
        raise HTTPException(
            resp.status_code, "Could not fetch GitHub installations"
        )
    resp_json = resp.json()
    n = resp_json["total_count"]
    accounts = [i["account"]["login"] for i in resp_json["installations"]]
    logger.info(f"User {current_user.email} has {n} installations: {accounts}")
    return GitHubInstallations.model_validate(resp_json)


class ConnectedAccounts(BaseModel):
    github: bool
    zenodo: bool
    overleaf: bool
    google: bool
    zotero: bool


@router.get("/user/connected-accounts")
def get_user_connected_accounts(
    session: SessionDep, current_user: CurrentUser
) -> ConnectedAccounts:
    # For OAuth providers, actually validate tokens work
    # (triggers refresh/cleanup)
    github_connected = False
    try:
        users.get_github_token(session=session, user=current_user)
        github_connected = True
    except HTTPException:
        pass
    zenodo_connected = False
    try:
        users.get_zenodo_token(session=session, user=current_user)
        zenodo_connected = True
    except HTTPException:
        pass
    google_connected = False
    try:
        users.get_google_token(session=session, user=current_user)
        google_connected = True
    except HTTPException:
        pass
    # Overleaf doesn't have refresh logic, just check if credential exists
    overleaf_cred = current_user.get_external_credential(provider="overleaf")
    overleaf_connected = (
        overleaf_cred is not None or current_user.overleaf_token is not None
    )
    # Zotero API keys don't expire, so there's nothing to refresh
    zotero_cred = current_user.get_external_credential(provider="zotero")
    return ConnectedAccounts(
        github=github_connected,
        zenodo=zenodo_connected,
        overleaf=overleaf_connected,
        google=google_connected,
        zotero=zotero_cred is not None,
    )


@router.post("/user/zenodo-auth")
def post_user_zenodo_auth(
    session: SessionDep,
    current_user: CurrentUser,
    req: "OAuthCodeExchange",
) -> Message:
    logger.info(f"Received Zenodo auth request for user {current_user.email}")
    body = dict(
        client_id=settings.ZENODO_CLIENT_ID,
        client_secret=settings.ZENODO_CLIENT_SECRET,
        grant_type="authorization_code",
        code=req.code,
        redirect_uri=req.redirect_uri,
    )
    url = ZENODO_AUTH_URL
    resp = requests.post(url, data=body)
    logger.info(f"Zenodo response status code: {resp.status_code}")
    if resp.status_code != 200:
        try:
            error_msg = resp.json().get("error_description", resp.text)
        except Exception:
            error_msg = resp.text
        logger.error(f"Zenodo auth failed: {error_msg}")
        raise HTTPException(resp.status_code, error_msg)
    resp_json = resp.json()
    # Response should have these keys
    # - access_token
    # - expires_in
    # - token_type
    # - scope
    # - user (dict with key 'id')
    # - refresh_token
    zenodo_user_id = resp_json["user"]["id"]
    current_user.zenodo_user_id = zenodo_user_id
    logger.info(f"Setting Zenodo user ID as {zenodo_user_id}")
    session.commit()
    logger.info("Saving Zenodo token")
    users.save_zenodo_token(
        session=session, user=current_user, zenodo_resp=resp_json
    )
    return Message(message="success")


class ExternalTokenResponse(BaseModel):
    access_token: str


@router.get("/user/zenodo-token")
def get_user_zenodo_token(
    session: SessionDep, current_user: CurrentUser
) -> ExternalTokenResponse:
    token = users.get_zenodo_token(session=session, user=current_user)
    return ExternalTokenResponse(access_token=token)


@router.get("/user/github-token")
def get_user_github_token(
    session: SessionDep, current_user: CurrentUser
) -> ExternalTokenResponse:
    token = users.get_github_token(session=session, user=current_user)
    return ExternalTokenResponse(access_token=token)


class TokenPut(BaseModel):
    token: str
    expires: datetime | None = None


class OAuthCodeExchange(BaseModel):
    code: str
    redirect_uri: str


@router.put("/user/overleaf-token")
def put_user_overleaf_token(
    req: TokenPut, session: SessionDep, current_user: CurrentUser
) -> Message:
    """Update the current user's Overleaf token."""
    if not req.token.startswith("olp_"):
        raise HTTPException(422, "Overleaf tokens start with 'olp_'")
    users.save_overleaf_token(
        session=session,
        user=current_user,
        token=req.token,
        expires=req.expires,
    )
    return Message(message="Token saved successfully")


@router.post("/user/google-auth")
def post_user_google_auth(
    session: SessionDep,
    current_user: CurrentUser,
    req: OAuthCodeExchange,
) -> Message:
    """Authenticate with Google using authorization code."""
    logger.info(f"Received Google auth request for user {current_user.email}")
    body = dict(
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        grant_type="authorization_code",
        code=req.code,
        redirect_uri=req.redirect_uri,
    )
    url = "https://oauth2.googleapis.com/token"
    resp = requests.post(url, data=body)
    logger.info(f"Google response status code: {resp.status_code}")
    if resp.status_code != 200:
        try:
            error_data = resp.json()
            msg = error_data.get("error_description", "Failed to authenticate")
        except Exception:
            msg = "Failed to authenticate with Google"
        logger.error(f"Google auth failed: {msg}")
        raise HTTPException(resp.status_code, msg)
    google_resp = resp.json()
    logger.info("Saving Google token")
    users.save_google_token(
        session=session, user=current_user, google_resp=google_resp
    )
    return Message(message="success")


class ZoteroAuthStart(BaseModel):
    authorize_url: str


@router.post("/user/zotero-auth/start")
def post_user_zotero_auth_start(
    session: SessionDep, current_user: CurrentUser
) -> ZoteroAuthStart:
    """Start the Zotero OAuth 1.0a flow and return where to send the user.

    Zotero requires signed requests, so the authorization URL can't be built in
    the browser like it can for our OAuth 2 providers.
    """
    logger.info(f"Starting Zotero auth for user {current_user.email}")
    callback_uri = f"{settings.frontend_host.rstrip('/')}/auth/zotero"
    request_token = zotero.fetch_request_token(callback_uri=callback_uri)
    users.save_zotero_request_token(
        session=session, user=current_user, request_token=request_token
    )
    authorize_url = zotero.create_authorize_url(
        oauth_token=request_token["oauth_token"]
    )
    return ZoteroAuthStart(authorize_url=authorize_url)


class ZoteroAuthFinish(BaseModel):
    oauth_token: str
    oauth_verifier: str


@router.post("/user/zotero-auth")
def post_user_zotero_auth(
    session: SessionDep, current_user: CurrentUser, req: ZoteroAuthFinish
) -> Message:
    """Finish the Zotero OAuth 1.0a flow, saving the resulting API key."""
    logger.info(f"Received Zotero auth request for user {current_user.email}")
    request_token = users.get_zotero_request_token(
        session=session, user=current_user
    )
    # Leave the stashed token in place on a mismatch, e.g. from a stale tab, so
    # a flow the user still has open elsewhere can finish
    if request_token["oauth_token"] != req.oauth_token:
        logger.error(f"Zotero request token mismatch for {current_user.email}")
        raise HTTPException(400, "Zotero request token mismatch")
    zotero_resp = zotero.fetch_access_token(
        oauth_token=req.oauth_token,
        oauth_token_secret=request_token["oauth_token_secret"],
        oauth_verifier=req.oauth_verifier,
    )
    logger.info("Saving Zotero API key")
    users.save_zotero_api_key(
        session=session, user=current_user, zotero_resp=zotero_resp
    )
    return Message(message="success")


@router.get("/user/overleaf-token")
def get_user_overleaf_token(
    session: SessionDep, current_user: CurrentUser
) -> ExternalTokenResponse:
    token = users.get_overleaf_token(session=session, user=current_user)
    return ExternalTokenResponse(access_token=token)


@router.delete("/user/external-credentials/{provider}")
def delete_user_external_credential(
    session: SessionDep, current_user: CurrentUser, provider: str
) -> Message:
    """Disconnect an external account by deleting its credential."""
    if provider == "github":
        raise HTTPException(
            403, "Cannot disconnect GitHub as it is your login method"
        )
    credential = users.get_external_credential(
        session=session,
        user=current_user,
        provider=provider,
        label="default",
    )
    if credential:
        session.delete(credential)
    # Also delete legacy tokens if they exist
    if provider == "zenodo" and current_user.zenodo_token:
        session.delete(current_user.zenodo_token)
    elif provider == "overleaf" and current_user.overleaf_token:
        session.delete(current_user.overleaf_token)
    session.commit()
    return Message(message=f"{provider.capitalize()} account disconnected")


@router.get("/user/storage")
def get_user_storage(
    session: SessionDep,
    current_user: CurrentUser,
) -> StorageUsage:
    used = get_storage_usage(owner_name=current_user.account.name)
    if current_user.subscription is None:
        raise HTTPException(404, "User does not have a subscription")
    limit = current_user.subscription.storage_limit
    return StorageUsage(limit_gb=limit, used_gb=used)
