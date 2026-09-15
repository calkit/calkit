"""Routes for what users tell us they want: feedback and feature votes.

Feedback is a message; a vote is the cheap version of one, a click on a
feature that isn't built yet. Both are read together on the admin page.
"""

import html
import logging
import uuid
from typing import Annotated, Literal

import sqlalchemy
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import selectinload
from sqlmodel import col, func, select

from app import mixpanel
from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
from app.config import settings
from app.messaging import send_email
from app.models import (
    FeatureVote,
    FeatureVoter,
    FeatureVoteStatus,
    FeatureVoteSummary,
    Feedback,
    FeedbackPatch,
    FeedbackPublic,
    Message,
    User,
)

logger = logging.getLogger(__name__)

router = APIRouter()


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
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[FeedbackPublic]:
    """List what users have sent in, newest first."""
    rows = session.exec(
        select(Feedback)
        # The sender's name and email are on the user, which would
        # otherwise be a query per row.
        .options(selectinload(Feedback.user))  # type: ignore[arg-type]
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


VOTABLE_FEATURES = {
    "external-releases-in-app",
    # Running notebooks and scripts on a connected local workspace, for
    # the Julia and R environments the browser can't run
    "local-workspace-compute",
}


def _build_feature_vote_status(
    *, session: SessionDep, feature: str, user: CurrentUser
) -> FeatureVoteStatus:
    count = session.exec(
        select(func.count())
        .select_from(FeatureVote)
        .where(FeatureVote.feature == feature)
    ).one()
    has_voted = session.exec(
        select(FeatureVote.id).where(
            FeatureVote.feature == feature,
            FeatureVote.user_id == user.id,
        )
    ).first()
    return FeatureVoteStatus(
        feature=feature, count=count, has_voted=has_voted is not None
    )


@router.get("/feature-votes/{feature}")
def get_feature_vote_status(
    feature: str, current_user: CurrentUser, session: SessionDep
) -> FeatureVoteStatus:
    if feature not in VOTABLE_FEATURES:
        raise HTTPException(404, "Unknown feature")
    return _build_feature_vote_status(
        session=session, feature=feature, user=current_user
    )


@router.post("/feature-votes/{feature}")
def post_feature_vote(
    feature: str, current_user: CurrentUser, session: SessionDep
) -> FeatureVoteStatus:
    """Record the current user's vote for a feature. Idempotent."""
    if feature not in VOTABLE_FEATURES:
        raise HTTPException(404, "Unknown feature")
    existing = session.exec(
        select(FeatureVote).where(
            FeatureVote.feature == feature,
            FeatureVote.user_id == current_user.id,
        )
    ).first()
    if existing is None:
        session.add(FeatureVote(feature=feature, user_id=current_user.id))
        session.commit()
        mixpanel.track(current_user, "Voted for feature", {"feature": feature})
    return _build_feature_vote_status(
        session=session, feature=feature, user=current_user
    )


@router.delete("/feature-votes/{feature}")
def delete_feature_vote(
    feature: str, current_user: CurrentUser, session: SessionDep
) -> FeatureVoteStatus:
    """Remove the current user's vote for a feature. Idempotent."""
    if feature not in VOTABLE_FEATURES:
        raise HTTPException(404, "Unknown feature")
    existing = session.exec(
        select(FeatureVote).where(
            FeatureVote.feature == feature,
            FeatureVote.user_id == current_user.id,
        )
    ).first()
    if existing is not None:
        session.delete(existing)
        session.commit()
        mixpanel.track(
            current_user, "Unvoted for feature", {"feature": feature}
        )
    return _build_feature_vote_status(
        session=session, feature=feature, user=current_user
    )


@router.get(
    "/feature-votes", dependencies=[Depends(get_current_active_superuser)]
)
def get_feature_votes(session: SessionDep) -> list[FeatureVoteSummary]:
    """Every feature's votes with who cast them, for the admin page.

    Listed alongside feedback, since both answer the same question: what
    do users want that isn't there yet? Features nobody has voted for
    still appear, at zero, so the list is the full set on offer.
    """
    rows = session.exec(
        select(FeatureVote, User)
        .join(User, col(User.id) == col(FeatureVote.user_id))
        .order_by(col(FeatureVote.created).desc())
    ).all()
    by_feature: dict[str, list[FeatureVoter]] = {
        f: [] for f in sorted(VOTABLE_FEATURES)
    }
    for vote, user in rows:
        by_feature.setdefault(vote.feature, []).append(
            FeatureVoter(
                email=user.email,
                full_name=user.full_name,
                account_name=user.account.name if user.account else None,
                created=vote.created,
            )
        )
    return [
        FeatureVoteSummary(feature=f, count=len(v), voters=v)
        for f, v in by_feature.items()
    ]
