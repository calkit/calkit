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
