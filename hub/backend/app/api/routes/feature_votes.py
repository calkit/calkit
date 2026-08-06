"""Routes for feature voting.

Lets users vote for features we haven't built yet so we can gauge demand. The
first such feature is creating external releases (publishing to Zenodo, arXiv,
etc.) from within Calkit rather than the CLI.
"""

from app import mixpanel
from app.api.deps import CurrentUser, SessionDep
from app.models import FeatureVote, FeatureVoteStatus
from fastapi import APIRouter, HTTPException
from sqlmodel import func, select

router = APIRouter()

# Features that can be voted on. Restricting to a known set keeps users from
# writing arbitrary rows.
VOTABLE_FEATURES = {"external-releases-in-app"}


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
