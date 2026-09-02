"""The work queue.

One job matters here -- warming a project after a push -- and it has two
properties that shape everything: it is idempotent, and only the newest one
per project is worth running. So jobs are keyed by project and a push arriving
while a warm is already queued replaces it rather than piling up behind it.

Backed by the Valkey already in the stack, and consumed by the ``worker``
service rather than by an API process: a warm takes minutes, and the API's
threadpool is what serves requests.

Optional, like the cache: with no ``REDIS_URL`` there is no queue, enqueuing
is a no-op, and the first viewer pays for the work as they did before.
"""

import re
from typing import Any

from app import cache
from app.cache import get_client
from app.config import settings
from app.core import logger

QUEUE_NAME = "warm"
# Long enough for a first clone of a large project plus everything derived
# from it, short enough that a wedged job doesn't hold the worker all day.
JOB_TIMEOUT = 1800
# A warm is only worth doing while it is still roughly current.
JOB_TTL = 600
# How long a startup sweep counts as having happened. Long enough to cover a
# rolling deploy and a development server reloading on every save.
STARTUP_WARM_INTERVAL = 900


def get_queue() -> Any:
    """The warm queue, or None when there's nothing to enqueue onto."""
    client = get_client()
    if client is None or not settings.REDIS_URL:
        return None
    try:
        from rq import Queue

        return Queue(QUEUE_NAME, connection=client)
    except Exception as e:
        logger.warning(f"Could not open the work queue: {e}")
        return None


def enqueue_warm(owner_name: str, project_name: str) -> bool:
    """Queue a warm for one project. True if it was queued.

    The job id is the project, so a burst of pushes coalesces into one
    pending warm instead of one per push.
    """
    queue = get_queue()
    if queue is None:
        return False
    slug = f"{owner_name}/{project_name}".lower()
    # RQ ids take letters, numbers, underscores and dashes only, so the slug
    # is flattened rather than used as-is.
    job_id = "warm-" + re.sub(r"[^a-z0-9_-]", "-", slug)
    try:
        queue.enqueue(
            "app.warm.warm_project",
            owner_name,
            project_name,
            job_id=job_id,
            job_timeout=JOB_TIMEOUT,
            ttl=JOB_TTL,
            # Replace a pending warm for the same project rather than
            # queueing a second one behind it.
            at_front=False,
        )
    except Exception as e:
        logger.warning(f"Could not queue a warm for {slug}: {e}")
        return False
    logger.info(f"Queued a warm for {slug}")
    return True


def enqueue_startup_warms(limit: int) -> int:
    """Queue warms for the projects most likely to be opened next.

    A deploy replaces the containers, and with them every in-process cache;
    the shared ones survive, but a release that changes how something is
    computed invalidates those too. Rather than let the next visitor to each
    project discover that, walk the recently-active ones on the way up.

    Ordered by when each project last changed, because a project nobody has
    touched in a year is also one nobody is about to open. Returns how many
    were queued.
    """
    if limit <= 0:
        return 0
    # Every process that starts would otherwise sweep, and in development
    # the app restarts on every file save: without this the queue is never
    # empty and the worker never stops, which makes the whole stack feel
    # slow for the sake of pages nobody asked for. One sweep per interval,
    # whoever gets there first.
    if not cache.claim(cache.make_key("startup-warm"), STARTUP_WARM_INTERVAL):
        logger.info("Skipping startup warms; one ran recently")
        return 0
    from sqlmodel import Session, select

    from app.db import engine
    from app.models import Project

    queued = 0
    try:
        with Session(engine) as session:
            projects = session.exec(
                select(Project)
                .order_by(Project.updated.desc())  # type: ignore[union-attr]
                .limit(limit)
            ).all()
            for project in projects:
                if enqueue_warm(project.owner_account_name, project.name):
                    queued += 1
    except Exception as e:
        # Starting up matters more than starting up warm.
        logger.warning(f"Could not queue startup warms: {e}")
        return queued
    logger.info(f"Queued {queued} warms on startup")
    return queued
