"""Tests for ``app.mixpanel``."""

from unittest.mock import patch

import pytest

from app import mixpanel
from app.models import User


@pytest.mark.parametrize("consent", [None, False])
def test_track_skips_users_without_consent(consent):
    user = User(email="a@example.com", hashed_password="x")
    user.analytics_consent = consent
    with patch.object(mixpanel.mp, "track") as mp_track:
        mixpanel.track(user, "Created new project")
    mp_track.assert_not_called()


def test_track_sends_events_for_users_who_consented():
    user = User(email="a@example.com", hashed_password="x")
    user.analytics_consent = True
    with patch.object(mixpanel.mp, "track") as mp_track:
        mixpanel.track(user, "Created new project", {"source": "wizard"})
    mp_track.assert_called_once_with(
        str(user.id),
        event_name="Created new project",
        properties={"source": "wizard"},
        meta=None,
    )


@pytest.mark.parametrize(
    "bot,interacted,human",
    [(False, True, True), (True, True, False), (False, False, False)],
)
def test_track_anonymous_pageview(bot, interacted, human):
    with patch.object(mixpanel.mp, "track") as mp_track:
        mixpanel.track_anonymous_pageview(
            visitor_id="abc123",
            path="/$accountName/$projectName",
            bot=bot,
            interacted=interacted,
            dwell_ms=12,
            owner_name="pete",
            project_name="proj",
        )
    mp_track.assert_called_once_with(
        "abc123",
        event_name="$mp_web_page_view",
        properties={
            "path": "/$accountName/$projectName",
            "bot": bot,
            "interacted": interacted,
            "human": human,
            "dwell_ms": 12,
            "anonymous": True,
            "owner_name": "pete",
            "project_name": "proj",
            "$ip": "0",
        },
    )


def test_track_anonymous_pageview_omits_names_when_absent():
    with patch.object(mixpanel.mp, "track") as mp_track:
        mixpanel.track_anonymous_pageview(
            visitor_id="abc123",
            path="/projects",
            bot=False,
            interacted=True,
        )
    properties = mp_track.call_args.kwargs["properties"]
    assert "owner_name" not in properties
    assert "project_name" not in properties
