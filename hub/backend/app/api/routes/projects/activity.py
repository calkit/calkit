"""A project's recent activity, in one list.

The project home shows what's been happening lately, which is more than
commits: data pushed to storage, a collaborator joining, a comment, a
release. Each of those is tracked somewhere already, so this reads the
newest of each and merges them by time rather than keeping a separate
event log that would have to be written from every one of those places.
"""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlmodel import col, select

import app.projects
from app.api.deps import CurrentUserOptional, SessionDep
from app.api.routes.projects.core import FULL_HISTORY_REPO_TTL
from app.git import get_commit_history, get_repo
from app.models import (
    Project,
    ProjectComment,
    ProjectDvcPush,
    Release,
    User,
    UserProjectAccess,
)

router = APIRouter()

ActivityKind = Literal[
    "commit", "dvc-push", "collaborator", "todo", "comment", "release"
]


class ProjectActivityItem(BaseModel):
    """One thing that happened in a project.

    ``id`` is stable across reads (a commit hash or a row ID) so the
    frontend can key on it; ``link`` is a route relative to the project
    page, or None when there's nowhere better to send the reader.
    """

    kind: ActivityKind
    timestamp: datetime
    title: str
    actor: str | None = None
    id: str
    link: str | None = None


def _actor(user: User | None) -> str | None:
    if user is None:
        return None
    return user.full_name or user.account.name


@router.get("/projects/{owner_name}/{project_name}/activity")
def get_project_activity(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
    limit: int = Query(20, ge=1, le=100),
) -> list[ProjectActivityItem]:
    """The newest ``limit`` things that happened in the project.

    Each source contributes at most ``limit`` items before the merge, so
    a busy commit history can't crowd out a release from last week within
    the window, only past it. To-dos are GitHub issues, which nothing here
    records, so that kind isn't produced yet.
    """
    project = app.projects.get_project(
        session=session,
        owner_name=owner_name,
        project_name=project_name,
        current_user=current_user,
        min_access_level="read",
    )
    items: list[ProjectActivityItem] = []
    repo = get_repo(
        project=project,
        user=current_user,
        session=session,
        ttl=FULL_HISTORY_REPO_TTL,
    )
    for commit in get_commit_history(repo, max_count=limit):
        items.append(
            ProjectActivityItem(
                kind="commit",
                # Commit times carry the author's offset; the database's
                # are naive UTC, so they're compared on the same footing
                timestamp=datetime.fromisoformat(commit["timestamp"])
                .astimezone(timezone.utc)
                .replace(tzinfo=None),
                title=commit["summary"],
                actor=commit["author"],
                id=commit["hash"],
                link=f"history?commit={commit['hash']}",
            )
        )
    items += _db_activity(session, project, limit)
    items.sort(key=lambda item: item.timestamp, reverse=True)
    return items[:limit]


def _db_activity(
    session: SessionDep, project: Project, limit: int
) -> list[ProjectActivityItem]:
    """What the hub's own tables know happened, newest ``limit`` of each."""
    items: list[ProjectActivityItem] = []
    pushes = session.exec(
        select(ProjectDvcPush)
        .where(ProjectDvcPush.project_id == project.id)
        .order_by(col(ProjectDvcPush.updated).desc())
        .limit(limit)
    ).all()
    for push in pushes:
        n = push.n_files
        items.append(
            ProjectActivityItem(
                kind="dvc-push",
                timestamp=push.updated,
                title=f"Pushed {n} file{'' if n == 1 else 's'} to DVC storage",
                actor=_actor(push.user),
                id=str(push.id),
                link="files",
            )
        )
    # Only access granted through the hub has a meaningful time; a row
    # cached from GitHub says when it was looked up, not when the person
    # was added there
    access_rows = session.exec(
        select(UserProjectAccess)
        .where(UserProjectAccess.project_id == project.id)
        .where(col(UserProjectAccess.role_id).is_not(None))
        .order_by(col(UserProjectAccess.created).desc())
        .limit(limit)
    ).all()
    for access in access_rows:
        who = _actor(access.user)
        items.append(
            ProjectActivityItem(
                kind="collaborator",
                timestamp=access.created,
                title=f"{who} joined as {access.role_name}",
                actor=who,
                id=f"{access.user_id}:{access.project_id}",
                link="collaborators",
            )
        )
    comments = session.exec(
        select(ProjectComment)
        .where(ProjectComment.project_id == project.id)
        .order_by(col(ProjectComment.created).desc())
        .limit(limit)
    ).all()
    for comment in comments:
        what = (
            f" on {comment.artifact_path}"
            if comment.artifact_path
            else " on the project"
        )
        items.append(
            ProjectActivityItem(
                kind="comment",
                timestamp=comment.created,
                title=(
                    f"{'Replied' if comment.parent_id else 'Commented'}{what}"
                ),
                actor=_actor(comment.user),
                id=str(comment.id),
                link="comments",
            )
        )
    releases = session.exec(
        select(Release)
        .where(Release.project_id == project.id)
        .order_by(col(Release.created).desc())
        .limit(limit)
    ).all()
    for release in releases:
        items.append(
            ProjectActivityItem(
                kind="release",
                timestamp=release.created,
                title=f"Released {release.name}",
                actor=_actor(release.created_by),
                id=str(release.id),
                link="releases",
            )
        )
    return items
