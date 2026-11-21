"""Tests for app.api.routes.analytics endpoints."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import cache, mixpanel
from app.api.routes import analytics
from app.config import settings


def _post(
    client: TestClient,
    views: list[dict],
    signals: dict | None = None,
    ip: str = "1.2.3.4",
    ua: str = "Mozilla/5.0 (Macintosh)",
):
    body: dict = {"views": views}
    if signals is not None:
        body["signals"] = signals
    return client.post(
        "/pageviews",
        json=body,
        headers={"user-agent": ua, "cf-connecting-ip": ip},
    )


def test_pageviews_group_a_visitors_views_for_the_day(
    client: TestClient,
) -> None:
    with patch.object(mixpanel.mp, "track") as mp_track:
        resp = _post(
            client,
            [
                {"path": "/projects"},
                {"path": "/projects"},
                {"path": "/datasets"},
            ],
            signals={"interacted": True},
        )
    assert resp.status_code == 204
    assert mp_track.call_count == 3
    # One request is one visitor, so every view shares an identifier
    assert len({call.args[0] for call in mp_track.call_args_list}) == 1
    first = mp_track.call_args_list[0].kwargs["properties"]
    assert first["path"] == "/projects"
    assert first["bot"] is False
    assert first["human"] is True


def test_pageviews_carry_the_owner_and_project(client: TestClient) -> None:
    with patch.object(mixpanel.mp, "track") as mp_track:
        _post(
            client,
            [
                {
                    "path": "/pete/proj/datasets",
                    "owner_name": "pete",
                    "project_name": "proj",
                }
            ],
            signals={"interacted": True},
        )
    props = mp_track.call_args.kwargs["properties"]
    assert props["path"] == "/pete/proj/datasets"
    assert props["owner_name"] == "pete"
    assert props["project_name"] == "proj"


def test_pageviews_identify_a_visitor_per_day(client: TestClient) -> None:
    def visitor_id(ip: str, ua: str, day: str) -> str:
        with (
            patch.object(
                analytics,
                "utcnow",
                return_value=datetime.fromisoformat(day).replace(tzinfo=UTC),
            ),
            patch.object(mixpanel.mp, "track") as mp_track,
        ):
            _post(client, [{"path": "/"}], ip=ip, ua=ua)
        return mp_track.call_args.args[0]

    same = visitor_id("1.2.3.4", "UA", "2026-09-29")
    # Stable within the day, so a visitor's views can be counted together
    assert visitor_id("1.2.3.4", "UA", "2026-09-29") == same
    # A new day, address, or browser is a different visitor
    assert visitor_id("1.2.3.4", "UA", "2026-09-30") != same
    assert visitor_id("5.6.7.8", "UA", "2026-09-29") != same
    assert visitor_id("1.2.3.4", "Other", "2026-09-29") != same


def test_pageviews_flag_bots(client: TestClient) -> None:
    with patch.object(mixpanel.mp, "track") as mp_track:
        _post(
            client,
            [{"path": "/"}],
            signals={"webdriver": True, "interacted": True},
        )
        _post(client, [{"path": "/"}], ua="Googlebot/2.1")
        # A real browser that never showed any input is treated as one too
        _post(client, [{"path": "/"}], signals={"interacted": False})
    props = [call.kwargs["properties"] for call in mp_track.call_args_list]
    assert [p["bot"] for p in props] == [True, True, False]
    assert [p["human"] for p in props] == [False, False, False]


def test_pageviews_are_rate_limited(client: TestClient) -> None:
    if cache.get_client() is None:
        pytest.skip("Rate limiting needs the shared cache")
    with (
        patch.object(analytics, "RATE_LIMIT_REQUESTS", 1),
        patch.object(mixpanel.mp, "track"),
    ):
        assert _post(client, [{"path": "/"}]).status_code == 204
        assert _post(client, [{"path": "/"}]).status_code == 429


def test_pageviews_reject_an_oversized_batch(client: TestClient) -> None:
    resp = client.post(
        "/pageviews",
        content=b"x" * (analytics.MAX_BODY_BYTES + 1),
        headers={"content-type": "text/plain"},
    )
    assert resp.status_code == 413


def test_pageviews_reject_a_bad_batch(client: TestClient) -> None:
    resp = client.post(
        "/pageviews",
        content=b"not json",
        headers={"content-type": "text/plain"},
    )
    assert resp.status_code == 422


def test_pageviews_do_nothing_without_a_token(client: TestClient) -> None:
    with (
        patch.object(settings, "MIXPANEL_TOKEN", ""),
        patch.object(mixpanel.mp, "track") as mp_track,
    ):
        resp = _post(client, [{"path": "/"}])
    assert resp.status_code == 204
    mp_track.assert_not_called()
