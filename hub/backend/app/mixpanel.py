"""Functionality for working with Mixpanel."""

import json
import time
from datetime import UTC, datetime, timedelta

import requests
from mixpanel import Mixpanel

from app import cache
from app.config import settings
from app.core import logger
from app.models import Project, User

mp = Mixpanel(settings.MIXPANEL_TOKEN)


# Frontend events that fire without input, for events from before the
# frontend sent ``interacted`` with every event
AUTOMATIC_EVENTS = {"404 (front end)", "Session auto-logout"}


def get_active_people(
    days: int = 30,
) -> dict[str, tuple[float, float, bool]] | None:
    """Everyone tracked in the last ``days`` days, keyed by distinct ID.

    Values are when they were last seen and when they last looked like a
    person, as Unix times (0 if never), and whether the ID is an account's
    rather than a device's. A device looks like a person on a day it sent two
    or more events, at least one after input: bots that rotate their user
    agent or address get a fresh device for each request, and a page left
    open sends no input. A device's events from before signing in are folded
    into the account when a later event links the two. Read from the raw
    event export, since the Query API can't count unique people across all
    events without a saved report. Anonymous page views are left out, since
    their IDs change daily, as are events from automated browsers. None when
    reading isn't configured or fails.
    """
    username = settings.MIXPANEL_SERVICE_ACCOUNT_USERNAME
    secret = settings.MIXPANEL_SERVICE_ACCOUNT_SECRET
    if not (username and secret and settings.MIXPANEL_PROJECT_ID):
        return None
    # Cached since the export allows 60 requests an hour
    key = cache.make_key("mixpanel", "people", str(days))
    cached = cache.get_json(key)
    if cached is not None:
        return {k: (v[0], v[1], v[2]) for k, v in cached.items()}
    since = time.time() - days * 86400
    # Export dates are UTC for projects created since 2023
    today = datetime.now(UTC).date()
    last_seen: dict[str, float] = {}
    accounts: set[str] = set()
    # Event count, whether any followed input, and the latest, by ID and day
    days_seen: dict[tuple[str, str], tuple[int, bool, float]] = {}
    device_accounts: dict[str, str] = {}
    try:
        resp = requests.get(
            f"https://{settings.MIXPANEL_EXPORT_HOST}/api/2.0/export",
            params={
                "project_id": settings.MIXPANEL_PROJECT_ID,
                "from_date": (today - timedelta(days=days)).isoformat(),
                "to_date": today.isoformat(),
                "where": 'not defined(properties["anonymous"])',
            },
            auth=(username, secret),
            timeout=10,
            stream=True,
        )
        if not resp.ok:
            # The body says why, e.g., a permission the account lacks
            raise RuntimeError(
                f"export returned {resp.status_code}: {resp.text[:500]}"
            )
        for line in resp.iter_lines():
            if not line:
                continue
            event = json.loads(line)
            props = event.get("properties", {})
            t = props.get("time", 0)
            if (
                props.get("anonymous")
                or props.get("bot")
                or props.get("webdriver")
                or t < since
            ):
                continue
            user_id = props.get("$user_id")
            distinct_id = str(props.get("distinct_id") or "")
            device_id = props.get("$device_id")
            if user_id and device_id:
                device_accounts[f"$device:{device_id}"] = str(user_id)
            person = str(user_id or distinct_id)
            if not person:
                continue
            # The browser SDK prefixes IDs that aren't signed in
            if user_id or not distinct_id.startswith("$device:"):
                accounts.add(person)
            last_seen[person] = max(t, last_seen.get(person, 0.0))
            # The frontend sends whether there was input yet with every
            # event; older custom events mostly came from clicks
            name = str(event.get("event", ""))
            if "interacted" in props:
                had_input = props["interacted"] is True
            else:
                had_input = not name.startswith("$") and (
                    name not in AUTOMATIC_EVENTS
                )
            day = datetime.fromtimestamp(t, UTC).date().isoformat()
            n, any_input, latest = days_seen.get(
                (person, day), (0, False, 0.0)
            )
            days_seen[(person, day)] = (
                n + 1,
                any_input or had_input,
                max(latest, t),
            )
    except Exception as e:
        # Usage numbers aren't worth failing a response over
        logger.warning(f"Could not read events from Mixpanel: {e}")
        return None
    # Fold devices into the accounts they signed in as
    for device, account in device_accounts.items():
        if device in last_seen and device not in accounts:
            t = last_seen.pop(device)
            last_seen[account] = max(t, last_seen.get(account, 0.0))
    last_engaged: dict[str, float] = {}
    for (person, _), (n, any_input, latest) in days_seen.items():
        if n >= 2 and any_input and person in last_seen:
            last_engaged[person] = max(latest, last_engaged.get(person, 0.0))
    people = {
        person: (t, last_engaged.get(person, 0.0), person in accounts)
        for person, t in last_seen.items()
    }
    cache.set_json(key, people, ttl=3600)
    return people


def track(
    user: User,
    event_name: str,
    add_event_info: dict | None = None,
    meta: dict | None = None,
):
    # Users who haven't answered the consent question are treated as having
    # said no, the same as in the browser
    if user.analytics_consent is not True:
        return
    return mp.track(
        str(user.id),
        event_name=event_name,
        properties=add_event_info,
        meta=meta,
    )


def track_anonymous_pageview(
    visitor_id: str,
    path: str,
    bot: bool,
    interacted: bool,
    dwell_ms: int = 0,
    owner_name: str | None = None,
    project_name: str | None = None,
) -> None:
    """A page view from a visitor who hasn't opted in.

    ``visitor_id`` is a per-day hash computed by the caller, so views from one
    visitor group for the day without being linkable across days, and nothing
    is ever stored on the visitor's device. ``interacted`` says whether any
    real input happened, which is what tells a person apart from a
    browser-driving bot that reports no such signal. ``owner_name`` and
    ``project_name`` name the page for project views, which is what lets
    interest in a project be seen.
    """
    properties: dict[str, object] = {
        "path": path,
        "bot": bot,
        "interacted": interacted,
        "human": not bot and interacted,
        "dwell_ms": dwell_ms,
        "anonymous": True,
        # Tells Mixpanel not to geolocate or store the request's IP
        "$ip": "0",
    }
    if owner_name is not None:
        properties["owner_name"] = owner_name
    if project_name is not None:
        properties["project_name"] = project_name
    mp.track(
        visitor_id,
        event_name="$mp_web_page_view",
        properties=properties,
    )


def user_created_new_token(user: User, scope: str | None, expires_days: int):
    track(
        user,
        "Created new token",
        add_event_info=dict(scope=scope, expires_days=expires_days),
    )


def user_logged_in(user: User, provider: str, first: bool):
    track(
        user, "Logged in", add_event_info=dict(provider=provider, first=first)
    )


def user_signed_up(user: User, provider: str):
    track(user, "Signed up", add_event_info=dict(provider=provider))


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

    ``source`` is one of created/url/doi/git/project, which is what says
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
