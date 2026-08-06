"""Routes for orgs."""

import logging
import uuid
from datetime import datetime
from typing import Literal

from app.models.core import UserPublic
import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import DataError
from sqlmodel import Field, SQLModel, select

import app.stripe
from app.api.deps import CurrentUser, CurrentUserOptional, SessionDep
from app.config import settings
from app.core import INVALID_ACCOUNT_NAMES, utcnow
from app.models import (
    ROLE_IDS,
    Account,
    DiscountCode,
    Message,
    Org,
    OrgSubscription,
    StorageUsage,
    SubscriptionUpdate,
    UpdateSubscriptionResponse,
    User,
    UserOrgMembership,
    UserSubscription,
)
from app.orgs import get_org_from_db
from app.storage import get_storage_usage
from app.subscriptions import PLAN_IDS, get_monthly_price
from app.users import get_github_token

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


class OrgPublic(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str
    github_name: str
    role: str


@router.get("/user/orgs")
def get_user_orgs(
    session: SessionDep,
    current_user: CurrentUser,
) -> list[OrgPublic]:
    resp = []
    for membership in current_user.org_memberships:
        org = membership.org
        resp.append(
            OrgPublic(
                id=org.id,
                name=org.account.name,
                display_name=org.display_name,
                github_name=org.github_name,
                role=membership.role_name,
            )
        )
    return resp


class OrgsResponse(SQLModel):
    data: list[OrgPublic]
    count: int


@router.get("/orgs")
def get_orgs(
    session: SessionDep,
    current_user: CurrentUserOptional,
    limit: int = 100,
    offset: int = 0,
    search_for: str | None = None,
) -> OrgsResponse:
    """Get a list of orgs."""
    query = (
        select(Org)
        .join(Account, Account.org_id == Org.id)  # type: ignore
        .offset(offset)
        .limit(limit)
        .order_by(Account.display_name)
    )
    if search_for is not None:
        search_for = f"%{search_for}%"
        query = query.where(Account.display_name.ilike(search_for))
    orgs = session.exec(query).all()
    count_query = (
        select(func.count())
        .select_from(Org)
        .join(
            Account,
            Account.org_id == Org.id,  # type: ignore
        )
    )
    if search_for is not None:
        count_query = count_query.where(Account.display_name.ilike(search_for))
    count = session.exec(count_query).one()
    resp = []
    for org in orgs:
        role = "none"
        if current_user is not None:
            for membership in current_user.org_memberships:
                if membership.org == org:
                    role = membership.role_name
        resp.append(
            OrgPublic(
                id=org.id,
                name=org.account.name,
                display_name=org.display_name,
                github_name=org.github_name,
                role=role,
            )
        )
    return OrgsResponse(data=resp, count=count)


class OrgPost(BaseModel):
    name: str | None = None
    display_name: str | None = None
    github_name: str


@router.post("/orgs")
def post_org(
    req: OrgPost, session: SessionDep, current_user: CurrentUser
) -> OrgPublic:
    org_name = (req.name or req.github_name).lower()
    if org_name in INVALID_ACCOUNT_NAMES:
        raise HTTPException(422, "Invalid account name")
    if get_org_from_db(org_name=org_name, session=session) is not None:
        raise HTTPException(400, "This org already exists")
    token = get_github_token(session=session, user=current_user)
    headers = {"Authorization": f"Bearer {token}"}
    org_resp = requests.get(
        f"https://api.github.com/orgs/{req.github_name}",
        headers=headers,
    )
    if org_resp.status_code != 200:
        logger.info(
            f"Could not find org {req.github_name} on "
            f"GitHub ({org_resp.status_code})"
        )
        raise HTTPException(400, "Could not fetch org from GitHub")
    # Org doesn't exist, so we can create it an give this user
    # ownership, but only if they have ownership on GitHub
    membership_resp = requests.get(
        (
            f"https://api.github.com/orgs/{req.github_name}/"
            f"memberships/{current_user.github_username}"
        ),
        headers=headers,
    )
    if membership_resp.status_code != 200:
        logger.info(
            (
                f"User {current_user.github_username} is not a "
                f"member of org {req.github_name} on GitHub"
            )
        )
        raise HTTPException(
            membership_resp.status_code,
            "Could not verify org membership on GitHub; "
            "Ensure the app is installed by visiting "
            "https://github.com/apps/calkit/installations/select_target",
        )
    role = membership_resp.json()["role"]
    if role != "admin":
        raise HTTPException(400, "Must be admin of GitHub org to create")
    # If the role is admin, we can make this user an owner here
    # Figure out the display name
    display_name = req.display_name
    if display_name is None:
        display_name = org_resp.json()["name"]
    if display_name is None:
        display_name = req.github_name
    if display_name is None:
        raise HTTPException(
            400, "Cannot detect display name; one must be provided"
        )
    org = Org(
        account=Account(
            name=org_name,
            display_name=display_name,
            github_name=req.github_name,
        ),
        user_memberships=[
            UserOrgMembership(user=current_user, role_id=ROLE_IDS["owner"])
        ],
        # Create new orgs with a free subscription
        subscription=OrgSubscription(
            plan_id=PLAN_IDS["free"],
            n_users=1,
            price=0.0,
            period_months=1,
            subscriber_user_id=current_user.id,
        ),
    )
    session.add(org)
    session.commit()
    session.refresh(org)
    return OrgPublic(
        id=org.id,
        name=org.account.name,
        display_name=org.display_name,
        github_name=org.github_name,
        role="owner",
    )


class OrgMemberPost(BaseModel):
    username: str
    role: Literal["read", "write", "admin", "owner"]


@router.post("/orgs/{org_name}/members")
def add_org_member(
    org_name: str,
    req: OrgMemberPost,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    org = get_org_from_db(org_name=org_name, session=session)
    if org is None:
        logger.info("Org '{org_name}' does not exist")
        raise HTTPException(404)
    # Ensure the current user is an org admin or owner
    role = None
    for membership in current_user.org_memberships:
        if membership.org.account.name == org_name:
            role = membership.role_name
    if role not in ["owner", "admin"]:
        logger.info("User is not an admin or owner of this org")
        raise HTTPException(403)
    # TODO: Check that this user is a member of the GitHub org?
    user_query = select(User).where(User.account.has(name=req.username))
    user = session.exec(user_query).first()
    if user is None:
        logger.info("Requested user does not exist")
        raise HTTPException(404, "User does not exist")
    if user in [m.user for m in org.user_memberships]:
        raise HTTPException(400, "User already exists in org")
    # Make sure this org has enough seats left
    subscription = org.subscription
    if not org.subscription_valid:
        logger.info(f"Org {org_name} has no valid subscription")
        raise HTTPException(400, "No valid subscription")
    n_users = subscription.n_users
    taken = len(org.user_memberships)
    left = n_users - taken
    if left <= 0:
        logger.info("No seats left")
        raise HTTPException(400, "No more seats left for this org")
    membership = UserOrgMembership(
        user=user, org=org, role_id=ROLE_IDS[req.role]
    )
    session.add(membership)
    session.commit()
    return Message(message="success")


class OrgSubscriptionUpdate(SubscriptionUpdate):
    plan_name: Literal["standard", "professional"]
    n_users: int = Field(ge=2)


@router.put("/orgs/{org_name}/subscription")
def put_org_subscription(
    org_name: str,
    req: OrgSubscriptionUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> UpdateSubscriptionResponse:
    # First check if this org exists, and if not, create it
    org = get_org_from_db(org_name=org_name, session=session)
    if org is None:
        logger.info("Org '{org_name}' does not exist")
        post_org(
            OrgPost(github_name=org_name),
            session=session,
            current_user=current_user,
        )
        org = get_org_from_db(org_name=org_name, session=session)
    else:
        if org.subscription is not None:
            raise HTTPException(400, "Org already has a subscription")
        # Ensure this user is an owner
        membership = None
        for m in org.user_memberships:  # type: ignore
            if m.user == current_user:
                membership = m
                break
        if membership is None:
            raise HTTPException(400, "Must be an org owner")
    if org is None:
        raise HTTPException(404, "Org not found")
    # Make sure there are enough seats for this org's current members
    if len(org.user_memberships) > req.n_users:  # type: ignore
        raise HTTPException(400, "Not enough seats for current org size")
    plan_id = PLAN_IDS[req.plan_name]
    discount_code = None
    period_months = 1 if req.period == "monthly" else 12
    if req.discount_code is not None:
        try:
            discount_code = session.get(DiscountCode, req.discount_code)
            if discount_code.redeemed is not None:  # type: ignore
                raise HTTPException(
                    400, "Discount code has already been redeemed"
                )
        except DataError:
            logger.info("User provided invalid discount code")
    if discount_code is not None:
        if discount_code.n_users != req.n_users:
            raise HTTPException(
                400, "Discount code number of users does not match"
            )
        price = discount_code.price
        years = discount_code.months // 12
        months = discount_code.months % 12
        today = utcnow().date()
        paid_until = datetime(
            today.year + years, today.month + months, today.day
        )
        discount_code.redeemed = utcnow()
        discount_code.redeemed_by_user_id = current_user.id
    else:
        price = get_monthly_price(req.plan_name, period=req.period)
        paid_until = None
    org.subscription = OrgSubscription(
        org_id=org.id,
        price=price,
        paid_until=paid_until,
        period_months=period_months,
        plan_id=plan_id,
        n_users=req.n_users,
        subscriber_user_id=current_user.id,
    )
    # Handle any discount codes
    if price > 0.0:
        # We need to setup payment stuff in Stripe
        customer = app.stripe.get_customer(email=current_user.email)
        if customer is None:
            customer = app.stripe.create_customer(
                email=current_user.email,
                full_name=current_user.full_name,
                user_id=current_user.id,
            )
        # TODO: If this is an update, we need to handle that
        # Get the Stripe price object for this plan
        stripe_price = app.stripe.get_price(plan_id=plan_id, period=req.period)
        stripe_session = app.stripe.stripe.checkout.Session.create(
            client_reference_id=current_user.id,  # type: ignore
            customer=customer.id,
            mode="subscription",
            line_items=[dict(price=stripe_price.id, quantity=req.n_users)],  # type: ignore
            ui_mode="embedded",
            return_url=settings.frontend_host,
            subscription_data={
                "description": f"{req.n_users} users for {org_name}.",
                "metadata": {"org_id": org.id, "plan_id": plan_id},
            },  # type: ignore
        )
        session_secret = stripe_session.client_secret
        org.subscription.processor_price_id = stripe_price.id  # type: ignore
        org.subscription.processor = "stripe"
    # If the current user doesn't have a subscription, give them a free one
    if current_user.subscription is None:
        current_user.subscription = UserSubscription(
            user_id=current_user.id,
            plan_id=0,
            price=0.0,
            period_months=1,
        )
    session.commit()
    session.refresh(org.subscription)
    return UpdateSubscriptionResponse(
        subscription=org.subscription,
        stripe_session_client_secret=session_secret,
    )


@router.get("/orgs/{org_name}/storage")
def get_org_storage(
    org_name: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> StorageUsage:
    org = get_org_from_db(org_name=org_name, session=session)
    if org is None:
        logger.info(f"Org '{org_name}' does not exist")
        raise HTTPException(404)
    # Ensure the current user is an org admin or owner
    role = None
    for membership in current_user.org_memberships:
        if membership.org.account.name == org_name:
            role = membership.role_name
    if role not in ["owner", "admin"]:
        logger.info("User is not an admin or owner of this org")
        raise HTTPException(403)
    limit = org.subscription.storage_limit
    used = get_storage_usage(org.account.name)
    return StorageUsage(used_gb=used, limit_gb=limit)


class OrgUserPublic(BaseModel):
    name: str
    github_name: str
    role: str


@router.get("/orgs/{org_name}/users")
def get_org_users(
    org_name: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[OrgUserPublic]:
    org = get_org_from_db(org_name=org_name, session=session)
    if org is None:
        logger.info(f"Org '{org_name}' does not exist")
        raise HTTPException(404)
    # Ensure the current user is an org admin or owner
    role = None
    for membership in current_user.org_memberships:
        if membership.org.account.name == org_name:
            role = membership.role_name
    if role is None:
        logger.info("User is not a member of this org")
        raise HTTPException(403)
    resp = []
    for membership in org.user_memberships:
        user = membership.user
        resp.append(
            OrgUserPublic(
                name=user.account.name,
                github_name=user.github_username,
                role=membership.role_name,
            )
        )
    return resp
