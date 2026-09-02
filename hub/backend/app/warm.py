"""Doing a project's expensive reads before anyone asks for them.

Almost everything the project view shows is derived from one commit, and the
derivations are not cheap: a pipeline's stage statuses walk object storage, a
file history parses every revision of ``dvc.lock``, a figure grid rasterizes
every figure. All of it is cached by content or by commit (see ``app.cache``),
so it only has to happen once--but today the first person to open the page
is the one who waits for it.

A push is the moment that work becomes necessary and the moment nobody is
waiting, so that is when it runs. The job is idempotent and safe to drop: the
worst case is the old behavior, where the first viewer pays.

It runs in a worker process rather than the API's threadpool, because it takes
minutes and the threadpool is what serves requests.
"""

import time

from sqlmodel import Session, select

from app import cache
from app.core import logger
from app.db import engine
from app.models import Account, Project, User


def warm_project(
    owner_name: str, project_name: str, force: bool = False
) -> dict:
    """Refresh a project's clone and recompute what the project view reads.

    Returns a summary of what ran, for the worker log. Never raises: a warm
    that fails costs a slow page, not a failed request, and the queue should
    not retry forever over a project that is simply broken.
    """
    started = time.perf_counter()
    done: list[str] = []
    failed: list[str] = []
    with Session(engine) as session:
        project = session.exec(
            select(Project)
            .join(Account, Account.id == Project.owner_account_id)  # type: ignore[arg-type]
            .where(Account.name == owner_name.lower())
            .where(Project.name == project_name.lower())
        ).first()
        if project is None:
            logger.warning(f"Nothing to warm: {owner_name}/{project_name}")
            return {"project": f"{owner_name}/{project_name}", "found": False}
        # A shared checkout carries the project's own credentials, so most
        # projects need no user here at all. The owner is the fallback for a
        # private project the GitHub App isn't installed on: there is no
        # shared copy for those, so someone's own checkout has to stand in.
        user: User | None = None
        if not project.is_public:
            user = session.exec(
                select(User).where(User.id == project.owner_account.user_id)
            ).first()
            if user is None:
                logger.warning(
                    f"No user to warm private {owner_name}/{project_name}"
                )
                return {
                    "project": f"{owner_name}/{project_name}",
                    "private_no_user": True,
                }
        # The clone is what tells us which commit we would be warming, so
        # it happens here rather than as a step: everything after it is
        # derived from that commit and keyed by it, so if the last warm
        # already ran at this commit there is nothing left to do. A push
        # reaches us twice -- once from the CLI and once from GitHub -- and
        # a restart re-queues what is already warm, so this is the common
        # case rather than the unusual one.
        from app.git import get_repo, resolve_commit_sha

        slug = f"{owner_name}/{project_name}".lower()
        warmed_key = cache.make_key("warmed", slug)
        try:
            # The shared checkout, because that is the one readers land
            # on: warming a single user's copy would leave everyone else to
            # clone it again for themselves.
            repo = get_repo(
                project=project,
                user=user,
                session=session,
                ttl=0,
                shared_read=True,
            )
            done.append("clone")
            sha = resolve_commit_sha(repo, None)
        except Exception as e:
            logger.warning(
                f"Could not read {slug} to warm it: {type(e).__name__}: {e}"
            )
            return {"project": slug, "failed": ["clone"]}
        if not force and sha and cache.get_json(warmed_key) == sha:
            logger.info(f"{slug} is already warm at {sha[:7]}")
            return {"project": slug, "already_warm_at": sha}
        for label, step in _steps():
            try:
                step(project, user, session)
                done.append(label)
            except Exception as e:
                # One unreadable artifact shouldn't stop the rest.
                logger.warning(
                    f"Warming {label} for {owner_name}/{project_name} "
                    f"failed: {type(e).__name__}: {e}"
                )
                failed.append(label)
    if sha and not failed:
        # Only when everything worked: a partial warm should be retried, not
        # remembered as done.
        cache.set_json(warmed_key, sha)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        f"Warmed {owner_name}/{project_name}",
        extra={
            "warm_project": f"{owner_name}/{project_name}",
            "warm_done": done,
            "warm_failed": failed,
            "duration_ms": duration_ms,
        },
    )
    return {
        "project": f"{owner_name}/{project_name}",
        "done": done,
        "failed": failed,
        "duration_ms": duration_ms,
    }


def _steps():
    """The warm steps, in the order the project view needs them.

    Imported lazily and listed here rather than called inline so one failing
    step is reported by name and the rest still run.

    Each step goes through the route the page calls, rather than reaching
    past it, so warming can't drift from what a request actually does. They
    each call ``get_repo`` again, which looks wasteful and measures at 0.4 ms
    once the first step has refreshed the clone: past that it is the TTL fast
    path, which returns the existing checkout without touching the lock or
    the network. For a private project it also re-reads the owner's token,
    which is a query against a row already in the session's identity map and
    only reaches GitHub when the credential is near expiry.
    """
    from app.api.routes.projects import core as routes

    def pipeline(project, user, session):
        routes.get_project_pipeline(
            owner_name=project.owner_account_name,
            project_name=project.name,
            current_user=user,
            session=session,
            ref=None,
        )

    def figures(project, user, session):
        # Every argument is passed, including the ones with defaults: called
        # outside a request, a FastAPI ``Query(...)`` default arrives as the
        # Query object rather than its value, and a Query object is truthy.
        routes.get_project_figures(
            owner_name=project.owner_account_name,
            project_name=project.name,
            current_user=user,
            session=session,
            ref=None,
            limit=20,
            offset=0,
            q=None,
            include_content=False,
            thumbnails=True,
        )

    def references(project, user, session):
        routes.get_project_references(
            owner_name=project.owner_account_name,
            project_name=project.name,
            current_user=user,
            session=session,
            ref=None,
        )

    def questions(project, user, session):
        routes.get_project_questions(
            owner_name=project.owner_account_name,
            project_name=project.name,
            current_user=user,
            session=session,
            ref=None,
        )

    def datasets(project, user, session):
        routes.get_project_datasets(
            owner_name=project.owner_account_name,
            project_name=project.name,
            current_user=user,
            session=session,
            ref=None,
        )

    def publications(project, user, session):
        routes.get_project_publications(
            owner_name=project.owner_account_name,
            project_name=project.name,
            current_user=user,
            session=session,
            ref=None,
            include_content=False,
        )

    return [
        ("pipeline", pipeline),
        ("figures", figures),
        ("references", references),
        ("publications", publications),
        ("questions", questions),
        ("datasets", datasets),
    ]
