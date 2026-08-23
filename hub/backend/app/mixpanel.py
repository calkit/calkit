"""Functionality for working with Mixpanel."""

from mixpanel import Mixpanel

from app.config import settings
from app.models import Project, User

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


def user_created_environment(
    user: User,
    owner_name: str,
    project_name: str,
    kind: str,
    n_packages: int,
) -> None:
    """An environment declared, and what it was made of.

    ``kind`` is the activation question here: whether the defaults steer
    people toward uv, or whether they keep reaching for conda.
    """
    track(
        user,
        "Created environment",
        add_event_info=dict(
            owner_name=owner_name,
            project_name=project_name,
            kind=kind,
            n_packages=n_packages,
        ),
    )


def user_added_dataset(
    user: User,
    owner_name: str,
    project_name: str,
    source: str,
) -> None:
    """A dataset declared, by where it came from.

    ``source`` is one of collected/url/doi/git/project, which is what says
    whether recording provenance is something people actually do.
    """
    track(
        user,
        "Added dataset",
        add_event_info=dict(
            owner_name=owner_name,
            project_name=project_name,
            source=source,
        ),
    )


def user_sent_feedback(user: User, kind: str, page: str | None) -> None:
    track(
        user,
        "Sent feedback",
        add_event_info=dict(kind=kind, page=page),
    )


def user_set_onboarding_flag(
    user: User, step: str, project_id: str | None, done: bool
) -> None:
    """A checklist step marked done or a checklist dismissed.

    Tracked server-side because this is funnel data, and the browser events
    that mirror it are the ones ad blockers drop.
    """
    track(
        user,
        "Set onboarding flag",
        add_event_info=dict(
            step=step,
            scope="project" if project_id else "account",
            done=done,
        ),
    )


def user_reset_onboarding(user: User, n_flags: int) -> None:
    track(
        user,
        "Reset onboarding checklists",
        add_event_info=dict(n_flags=n_flags),
    )


def user_added_question(
    user: User, owner_name: str, project_name: str, has_hypothesis: bool
) -> None:
    track(
        user,
        "Added question",
        add_event_info=dict(
            owner_name=owner_name,
            project_name=project_name,
            has_hypothesis=has_hypothesis,
        ),
    )


def user_uploaded_project(
    user: User,
    owner_name: str,
    project_name: str,
    n_bytes: int,
    n_dvc_objects: int,
) -> None:
    """A project brought in as a zip rather than from a GitHub repo.

    ``n_dvc_objects`` says how much of it was big enough to land in DVC,
    which is the thing the upload path is really for.
    """
    track(
        user,
        "Uploaded project",
        add_event_info=dict(
            owner_name=owner_name,
            project_name=project_name,
            n_bytes=n_bytes,
            n_dvc_objects=n_dvc_objects,
        ),
    )


def user_saved_figure_script(
    user: User,
    project: Project,
    env_created: bool,
    n_inputs: int,
    n_packages: int,
) -> None:
    """A figure drafted in the browser was committed as a pipeline stage.

    The save is the activation moment the figure editor exists for: a run in the
    browser proves nothing, a stage in the repo does. ``env_created`` says
    whether the figure editor also had to stand up the project's first Python
    environment, which is the setup work it's meant to absorb.
    """
    track(
        user,
        "Saved figure script",
        add_event_info=dict(
            owner_name=project.owner_account_name,
            project_name=project.name,
            env_created=env_created,
            n_inputs=n_inputs,
            n_packages=n_packages,
        ),
    )
