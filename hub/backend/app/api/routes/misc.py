"""Miscellaneous routes."""

import html
import logging
import os
import uuid
from typing import Literal

import requests
import sqlalchemy
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pydantic.networks import EmailStr
from sqlalchemy.exc import DataError
from sqlmodel import and_, or_, select
from starlette.requests import Request

from app import arxiv, mixpanel, version
from app.api.deps import (
    CurrentUser,
    CurrentUserOptional,
    SessionDep,
    get_current_active_superuser,
)
from app.config import settings
from app.core import utcnow
from app.messaging import generate_test_email, send_email
from app.models import (
    PLAN_IDS,
    Account,
    Dataset,
    DiscountCode,
    DiscountCodePost,
    Feedback,
    FeedbackPatch,
    FeedbackPublic,
    Message,
    Notification,
    Org,
    Project,
    User,
    UserOrgMembership,
    UserProjectAccess,
)
from app.stripe import stripe
from app.subscriptions import SubscriptionPlan, get_plans

logger = logging.getLogger(__name__)
router = APIRouter()


class HubVersion(BaseModel):
    version: str


@router.get("/version")
def get_hub_version() -> HubVersion:
    """Return the version of the hub serving this request.

    Deliberately unauthenticated: the frontend shows it before anyone signs
    in, and a client deciding whether it's talking to a hub new enough for
    a given feature shouldn't have to authenticate to find out.
    """
    return HubVersion(version=version.get_version())


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


class FeedbackPost(BaseModel):
    kind: Literal["feedback", "bug", "help"] = "feedback"
    message: str = Field(min_length=1, max_length=5000)
    # Where the user was when they opened the form. A bug report without it
    # usually costs a round trip to ask "which page?".
    page: str | None = Field(default=None, max_length=2048)


@router.post("/feedback")
def post_feedback(
    req: FeedbackPost, session: SessionDep, current_user: CurrentUser
) -> Message:
    """Record a user's feedback, bug report, or question.

    The row is written first and the email is best-effort after it: a relay
    that's down is a notification problem, not a reason to tell someone
    their feedback didn't go through and lose what they typed.
    """
    feedback = Feedback(
        user_id=current_user.id,
        kind=req.kind,
        message=req.message,
        page=req.page,
    )
    session.add(feedback)
    session.commit()
    labels = {
        "feedback": "Feedback",
        "bug": "Bug report",
        "help": "Help request",
    }
    label = labels[req.kind]
    # Composed here rather than from a template, since the built templates
    # come out of the MJML sources and this has no styling worth the round
    # trip. The message is user-controlled, so every interpolated value is
    # escaped -- render_email_template's autoescape doesn't apply here.
    lines = [
        f"<p><strong>{html.escape(label)}</strong> from "
        f"{html.escape(current_user.full_name or 'a user')} "
        f'(<a href="mailto:{html.escape(current_user.email)}">'
        f"{html.escape(current_user.email)}</a>, account "
        f"{html.escape(current_user.account.name)})</p>",
    ]
    if req.page:
        lines.append(f"<p>Sent from: {html.escape(req.page)}</p>")
    lines.append(
        f'<pre style="white-space: pre-wrap">{html.escape(req.message)}</pre>'
    )
    if settings.emails_enabled:
        try:
            send_email(
                email_to=settings.feedback_email,
                subject=f"{settings.PROJECT_NAME} - {label}",
                html_content="\n".join(lines),
            )
        except Exception as e:
            # Already saved, and visible on the admin page, so a failed
            # notification is worth a log and nothing more.
            logger.warning(f"Failed to email feedback {feedback.id}: {e}")
    logger.info(f"Recorded {req.kind} from user {current_user.id}")
    mixpanel.user_sent_feedback(
        user=current_user, kind=req.kind, page=req.page
    )
    return Message(message="Thanks! We'll get back to you.")


@router.get("/feedback", dependencies=[Depends(get_current_active_superuser)])
def get_feedback(
    session: SessionDep, limit: int = 100, offset: int = 0
) -> list[FeedbackPublic]:
    """List what users have sent in, newest first."""
    rows = session.exec(
        select(Feedback)
        .order_by(sqlalchemy.desc(Feedback.created))  # type: ignore
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        FeedbackPublic(
            id=row.id,
            kind=row.kind,
            message=row.message,
            page=row.page,
            created=row.created,
            resolved=row.resolved,
            user_email=row.user.email,
            user_full_name=row.user.full_name,
        )
        for row in rows
    ]


@router.patch(
    "/feedback/{feedback_id}",
    dependencies=[Depends(get_current_active_superuser)],
)
def patch_feedback(
    feedback_id: uuid.UUID, req: FeedbackPatch, session: SessionDep
) -> Message:
    """Mark a piece of feedback dealt with, or put it back."""
    row = session.get(Feedback, feedback_id)
    if row is None:
        raise HTTPException(404, "Feedback not found")
    row.resolved = req.resolved
    session.add(row)
    session.commit()
    return Message(message="Success")


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


ARXIV_PDF_TIMEOUT = 30
# arXiv asks that automated readers identify themselves
ARXIV_USER_AGENT = "Calkit/1.0 (+https://calkit.io; support@calkit.io)"


@router.get("/arxiv/{arxiv_id:path}/pdf")
def get_arxiv_pdf(arxiv_id: str, current_user: CurrentUser) -> Response:
    """Stream a paper's PDF from arXiv.

    Proxied rather than pointed at directly because arXiv sends no CORS
    headers, so the PDF viewer can't fetch it from the browser. The ID is
    matched against arXiv's own format, which is what keeps this from
    being a proxy for arbitrary URLs.

    Old-style IDs contain a slash, hence the path converter.
    """
    if not arxiv.is_id(arxiv_id):
        raise HTTPException(422, "Invalid arXiv ID")
    url = arxiv.pdf_url(arxiv_id)
    try:
        resp = requests.get(
            url,
            timeout=ARXIV_PDF_TIMEOUT,
            stream=True,
            headers={"User-Agent": ARXIV_USER_AGENT},
        )
    except requests.RequestException as e:
        logger.warning(f"Failed to fetch arXiv PDF {arxiv_id}: {e}")
        raise HTTPException(502, "Could not reach arXiv")
    # Anything that gives up before streaming has to close the response
    # itself; once streaming starts, the generator below owns it
    try:
        if resp.status_code == 404:
            raise HTTPException(404, "No PDF for this arXiv ID")
        if not resp.ok:
            logger.warning(
                f"arXiv returned {resp.status_code} for PDF {arxiv_id}"
            )
            raise HTTPException(502, "arXiv could not provide this PDF")
        if "pdf" not in resp.headers.get("Content-Type", ""):
            # A withdrawn or unreleased paper answers with an HTML notice
            raise HTTPException(404, "No PDF for this arXiv ID")
    except HTTPException:
        resp.close()
        raise
    headers = {
        # A paper at a given version never changes, so let the browser keep it
        "Cache-Control": "private, max-age=86400",
    }
    if length := resp.headers.get("Content-Length"):
        headers["Content-Length"] = length

    def stream():
        # Closed however the download ends, including a client that
        # disconnects part way through, so the connection goes back to
        # the pool instead of leaking
        try:
            yield from resp.iter_content(chunk_size=64 * 1024)
        finally:
            resp.close()

    return StreamingResponse(
        stream(), media_type="application/pdf", headers=headers
    )
