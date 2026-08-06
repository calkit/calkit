"""Functionality for working with Mixpanel."""

from app.config import settings
from app.models import User
from mixpanel import Mixpanel

mp = Mixpanel(settings.MIXPANEL_TOKEN)


def track(
    user: User,
    event_name: str,
    add_event_info: dict | None = None,
    meta: dict | None = None,
):
    return mp.track(
        str(user.id),
        event_name=event_name,
        properties=add_event_info,
        meta=meta,
    )


def user_created_new_token(user: User, scope: str | None, expires_days: int):
    track(
        user,
        "Created new token",
        add_event_info=dict(scope=scope, expires_days=expires_days),
    )


def user_logged_in(user: User):
    track(user, "Logged in")


def user_signed_up(user: User):
    track(user, "Signed up")


def user_dvc_pushed(user: User, owner_name: str, project_name: str):
    track(
        user,
        "DVC push",
        add_event_info=dict(owner_name=owner_name, project_name=project_name),
    )


def user_dvc_pulled(user: User, owner_name: str, project_name: str):
    track(
        user,
        "DVC pull",
        add_event_info=dict(owner_name=owner_name, project_name=project_name),
    )


def user_out_of_storage(user: User):
    track(user, "Out of storage")


def user_posted_figure_comment(
    user: User, owner_name: str, project_name: str, figure_path: str
):
    track(
        user,
        "Posted figure comment",
        add_event_info=dict(
            owner_name=owner_name,
            project_name=project_name,
            figure_path=figure_path,
        ),
    )


def user_posted_publication_comment(
    user: User,
    owner_name: str,
    project_name: str,
    publication_path: str,
    has_highlight: bool,
):
    track(
        user,
        "Posted publication comment",
        add_event_info=dict(
            owner_name=owner_name,
            project_name=project_name,
            publication_path=publication_path,
            has_highlight=has_highlight,
        ),
    )


def user_resolved_comment(
    user: User,
    owner_name: str,
    project_name: str,
    kind: str,
    resolved: bool,
):
    track(
        user,
        "Resolved comment" if resolved else "Unresolved comment",
        add_event_info=dict(
            owner_name=owner_name,
            project_name=project_name,
            kind=kind,
        ),
    )


def user_performed_fs_op(
    user: User,
    owner_name: str,
    project_name: str,
    operation: str,
):
    track(
        user,
        "Performed fs op",
        add_event_info=dict(
            owner_name=owner_name,
            project_name=project_name,
            operation=operation,
        ),
    )
