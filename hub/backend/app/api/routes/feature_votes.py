"""Routes for feature voting.

Lets users vote for features we haven't built yet so we can gauge demand. The
first such feature is creating external releases (publishing to Zenodo, arXiv,
etc.) from within Calkit rather than the CLI.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, func, select

from app import mixpanel
from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
from app.models import (
    FeatureVote,
    FeatureVoter,
    FeatureVoteStatus,
    FeatureVoteSummary,
    User,
)

router = APIRouter()

# Features that can be voted on. Restricting to a known set keeps users from
# writing arbitrary rows.
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
