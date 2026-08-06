"""Miscellaneous routes."""

import os
import uuid
from typing import Literal

from app.api.deps import (
    CurrentUser,
    CurrentUserOptional,
    SessionDep,
    get_current_active_superuser,
)
from app.core import utcnow
from app.messaging import generate_test_email, send_email
from app.models import (
    PLAN_IDS,
    Account,
    Dataset,
    DiscountCode,
    DiscountCodePost,
    Message,
    Notification,
    Org,
    Project,
    User,
    UserOrgMembership,
    UserProjectAccess,
)
from sqlmodel import and_, or_, select
from app.stripe import stripe
from app.subscriptions import SubscriptionPlan, get_plans
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pydantic.networks import EmailStr
from sqlalchemy.exc import DataError
from starlette.requests import Request

router = APIRouter()


@router.post(
    "/test-email/",
    dependencies=[Depends(get_current_active_superuser)],
    status_code=201,
)
def test_email(email_to: EmailStr) -> Message:
    """Test emails."""
    email_data = generate_test_email(email_to=email_to)
    send_email(
        email_to=email_to,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="Test email sent")


class DiscountCodePublic(BaseModel):
    id: uuid.UUID
    is_valid: bool = True
    reason: str | None = None
    n_users: int | None = None
    price: float | None = None
    months: int | None = None
    plan_name: str | None = None


@router.get("/discount-codes/{discount_code}")
def get_discount_code(
    discount_code: str,
    session: SessionDep,
    current_user: CurrentUser,
    n_users: int = 1,
) -> DiscountCodePublic:
    try:
        code = session.get(DiscountCode, discount_code)
    except DataError:
        raise HTTPException(422, "Code is invalid")
    if code is None:
        raise HTTPException(404, "Code does not exist")
    # Check if this code has been redeemed
    if code.redeemed is not None:
        return DiscountCodePublic(
            id=code.id, is_valid=False, reason="Code has been redeemed"
        )
    # Check if this code is no longer valid
    now = utcnow()
    if code.valid_from is not None and now < code.valid_from:
        return DiscountCodePublic(
            id=code.id, is_valid=False, reason="Code is not yet active"
        )
    if code.valid_until is not None and now > code.valid_until:
        return DiscountCodePublic(
            id=code.id, is_valid=False, reason="Code is not yet active"
        )
    # Check if this code was created for a particular user
    if code.created_for_account_id is not None:
        if current_user.account.id != code.created_for_account_id:
            return DiscountCodePublic(
                id=code.id,
                is_valid=False,
                reason="Code was not created for this account",
            )
    if code.n_users != n_users:
        return DiscountCodePublic(
            id=code.id,
            is_valid=False,
            reason=f"Number of users does not match ({code.n_users})",
        )
    return DiscountCodePublic.model_validate(
        code.model_dump() | {"plan_name": code.plan_name}
    )


@router.post("/discount-codes")
def post_discount_code(
    session: SessionDep,
    req: DiscountCodePost,
    current_user: User = Depends(get_current_active_superuser),
) -> DiscountCode:
    created_for_account_id = None
    if req.created_for_account_name is not None:
        account = session.exec(
            select(Account).where(
                Account.name == req.created_for_account_name.lower()
            )
        ).first()
        if account is None:
            raise HTTPException(400, "Account does not exist")
        created_for_account_id = account.id
    code = DiscountCode.model_validate(
        req,
        update=dict(
            created_by_user_id=current_user.id,
            created_for_account_id=created_for_account_id,
            plan_id=PLAN_IDS[req.plan_name],
        ),
    )
    session.add(code)
    session.commit()
    session.refresh(code)
    return code


@router.post("/stripe-events", include_in_schema=False)
async def post_stripe_event(request: Request):
    # This comes directly from the Stripe example server app
    # You can use webhooks to receive information about asynchronous payment
    # events
    # For more about our webhook events check out
    # https://stripe.com/docs/webhooks
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    request_data = await request.json()
    if webhook_secret:
        # Retrieve the event by verifying the signature using the raw body and
        # secret if webhook signing is configured
        signature = request.headers.get("stripe-signature")
        try:
            event = stripe.Webhook.construct_event(
                payload=request.data,
                sig_header=signature,
                secret=webhook_secret,
            )
            data = event["data"]
        except Exception as e:
            return e
        event_type = event["type"]
    else:
        data = request_data["data"]
        event_type = request_data["type"]
    data_object = data["object"]
    if event_type == "invoice.payment_succeeded":
        if data_object["billing_reason"] == "subscription_create":
            # The subscription automatically activates after successful payment
            # Set the payment method used to pay the first invoice
            # as the default payment method for that subscription
            subscription_id = data_object["subscription"]
            payment_intent_id = data_object["payment_intent"]
            # Retrieve the payment intent used to pay the subscription
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            # Set the default payment method
            stripe.Subscription.modify(
                subscription_id,
                default_payment_method=payment_intent.payment_method,
            )
            print(
                "Default payment method set for subscription:"
                + payment_intent.payment_method
            )
    elif event_type == "invoice.payment_failed":
        # If the payment fails or the customer does not have a valid payment
        # method,
        # an invoice.payment_failed event is sent, the subscription becomes
        # past_due
        # Use this webhook to notify your user that their payment has
        # failed and to retrieve new card details.
        # print(data)
        print("Invoice payment failed: %s", event.id)
    elif event_type == "invoice.finalized":
        # If you want to manually send out invoices to your customers
        # or store them locally to reference to avoid hitting Stripe rate
        # limits
        # print(data)
        print("Invoice finalized: %s", event.id)
    elif event_type == "customer.subscription.deleted":
        # handle subscription cancelled automatically based
        # upon your subscription settings. Or if the user cancels it.
        # print(data)
        print("Subscription canceled: %s", event.id)


class PresignedUrlRequest(BaseModel):
    path: str
    method: Literal["get", "put"] = "get"


@router.post("/presigned-urls", include_in_schema=False)
def post_presigned_url(
    current_user: CurrentUser, session: SessionDep, req: PresignedUrlRequest
):
    from app.api.routes.projects import get_object_url

    if not current_user.is_superuser:
        raise HTTPException(403)
    return get_object_url(req.path, method=req.method)


@router.get("/subscription-plans")
def get_subscription_plans(
    current_user: CurrentUser,
) -> list[SubscriptionPlan]:
    return get_plans()


class SearchResultItem(BaseModel):
    kind: Literal["project", "org", "dataset"]
    name: str
    title: str | None = None
    description: str | None = None
    owner_name: str | None = None
    project_name: str | None = None


class SearchResults(BaseModel):
    results: list[SearchResultItem]


@router.get("/search")
def global_search(
    q: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
    limit: int = 5,
) -> SearchResults:
    """Search projects, orgs, and datasets visible to the current user.

    Parameters
    ----------
    q:
        Query string matched case-insensitively against names, titles,
        and descriptions. Short queries (<2 chars) return no results.
    limit:
        Maximum number of results returned per category.
    """
    if not q or len(q) < 2:
        return SearchResults(results=[])
    pattern = f"%{q}%"
    results: list[SearchResultItem] = []
    # Projects
    if current_user is None:
        proj_where = Project.is_public
    else:
        proj_where = or_(
            Project.is_public,
            Project.owner_account_id == current_user.account.id,
            # Native Calkit grant (invite) or GitHub-derived access; a row with
            # both null is a cached "no access" result.
            Project.user_access_records.any(  # type: ignore
                and_(
                    UserProjectAccess.user_id == current_user.id,
                    or_(
                        UserProjectAccess.role_id.is_not(None),
                        UserProjectAccess.github_access.is_not(None),
                    ),
                )
            ),
            Project.owner_account.has(  # type: ignore
                and_(
                    Account.org_id.is_not(None),  # type: ignore
                    select(UserOrgMembership)
                    .where(
                        UserOrgMembership.user_id == current_user.id,
                        UserOrgMembership.org_id == Account.org_id,
                    )
                    .exists(),
                )
            ),
        )
    proj_where = and_(
        proj_where,
        or_(
            Project.name.ilike(pattern),  # type: ignore
            Project.title.ilike(pattern),  # type: ignore
            Project.description.ilike(pattern),  # type: ignore
        ),
    )
    projects = session.exec(
        select(Project)
        .distinct()
        .where(proj_where)
        .order_by(Project.name)  # type: ignore
        .limit(limit)
    ).all()
    for p in projects:
        results.append(
            SearchResultItem(
                kind="project",
                name=p.name,
                title=p.title,
                description=p.description,
                owner_name=p.owner_account_name,
            )
        )
    # Orgs
    org_results = session.exec(
        select(Org)
        .join(Account, Account.org_id == Org.id)  # type: ignore
        .where(Account.name.ilike(pattern))  # type: ignore
        .limit(limit)
    ).all()
    for o in org_results:
        results.append(
            SearchResultItem(
                kind="org",
                name=o.account.name,
                title=o.display_name,
            )
        )
    # Datasets
    if current_user is None:
        ds_where = Project.is_public
    else:
        ds_where = or_(
            Project.is_public,
            Project.owner_account_id == current_user.account.id,
        )
    ds_where = and_(
        ds_where,
        or_(
            Dataset.path.ilike(pattern),  # type: ignore
            Dataset.title.ilike(pattern),  # type: ignore
            Dataset.description.ilike(pattern),  # type: ignore
        ),
    )
    datasets = session.exec(
        select(Dataset)
        .join(Project, Project.id == Dataset.project_id)  # type: ignore
        .where(ds_where)
        .limit(limit)
    ).all()
    for d in datasets:
        results.append(
            SearchResultItem(
                kind="dataset",
                name=d.path,
                title=d.title,
                description=d.description,
                owner_name=d.project.owner_account_name,
                project_name=d.project.name,
            )
        )
    return SearchResults(results=results)


@router.get("/notifications")
def get_notifications(
    current_user: CurrentUser,
    session: SessionDep,
    unread_only: bool = False,
) -> list[Notification]:
    query = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        query = query.where(Notification.read.is_(None))  # type: ignore
    query = query.order_by(Notification.created.desc()).limit(50)  # type: ignore
    return session.exec(query).fetchall()


@router.patch("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: CurrentUser,
    session: SessionDep,
) -> Notification:
    notification = session.get(Notification, notification_id)
    if notification is None or notification.user_id != current_user.id:
        raise HTTPException(404)
    if notification.read is None:
        notification.read = utcnow()
        session.add(notification)
        session.commit()
        session.refresh(notification)
    return notification


@router.post("/notifications/read-all", status_code=204)
def mark_all_notifications_read(
    current_user: CurrentUser,
    session: SessionDep,
) -> None:
    notifications = session.exec(
        select(Notification).where(
            Notification.user_id == current_user.id,
            Notification.read.is_(None),  # type: ignore
        )
    ).fetchall()
    now = utcnow()
    for n in notifications:
        n.read = now
        session.add(n)
    session.commit()
