"""Tests for app.api.routes.misc endpoints."""

import json
import time
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest
import requests
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import users
from app.config import settings
from app.core import utcnow
from app.models import (
    ROLE_IDS,
    Project,
    RefreshToken,
    User,
    UserCreate,
    UserExternalCredential,
    UserProjectAccess,
    UserToken,
)
from app.tests import random_email, random_lower_string


def test_get_arxiv_pdf_requires_auth(client: TestClient) -> None:
    resp = client.get("/arxiv/2301.01234/pdf")
    assert resp.status_code == 401


def test_get_arxiv_pdf_rejects_a_non_id(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """The ID check is what keeps this from proxying arbitrary URLs."""
    with patch("app.api.routes.misc.requests.get") as get:
        resp = client.get(
            "/arxiv/..%2F..%2Fetc%2Fpasswd/pdf",
            headers=normal_user_token_headers,
        )
    assert resp.status_code == 422
    get.assert_not_called()


def _fake_response(**kwargs) -> SimpleNamespace:
    """An arXiv response that records whether it was closed."""
    closed = []
    resp = SimpleNamespace(closed=closed, **kwargs)
    resp.close = lambda: closed.append(True)
    return resp


def test_get_arxiv_pdf_streams_the_paper(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    fake = _fake_response(
        status_code=200,
        ok=True,
        headers={"Content-Type": "application/pdf", "Content-Length": "5"},
        iter_content=lambda chunk_size: iter([b"%PDF-"]),
    )
    with patch("app.api.routes.misc.requests.get", return_value=fake) as get:
        resp = client.get(
            "/arxiv/math.GT%2F0309136v2/pdf",
            headers=normal_user_token_headers,
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-"
    # Closed once the download ends, so the connection goes back to the
    # pool rather than leaking
    assert fake.closed == [True]
    # An old-style ID keeps its slash, and the version suffix names the exact
    # PDF the citation refers to
    assert get.call_args.args[0] == "https://arxiv.org/pdf/math.GT/0309136v2"


def test_get_arxiv_pdf_when_there_is_no_pdf(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """A withdrawn paper answers with an HTML notice, not a PDF."""
    fake = _fake_response(
        status_code=200,
        ok=True,
        headers={"Content-Type": "text/html"},
        iter_content=lambda chunk_size: iter([b"<html>"]),
    )
    with patch("app.api.routes.misc.requests.get", return_value=fake):
        resp = client.get(
            "/arxiv/2301.01234/pdf",
            headers=normal_user_token_headers,
        )
    assert resp.status_code == 404
    # Giving up before streaming has to close it too
    assert fake.closed == [True]


def test_get_version_needs_no_auth(client: TestClient) -> None:
    """Clients check what a hub supports before they have credentials."""
    resp = client.get("/version")
    assert resp.status_code == 200
    assert resp.json()["version"]


def test_get_templates(client: TestClient) -> None:
    import calkit.templates

    # Every kind, no login needed
    r = client.get("/templates")
    assert r.status_code == 200, r.text
    names = [t["name"] for t in r.json()]
    assert names == [t.ref for t in calkit.templates.get_templates()]
    # One kind, with what a picker shows
    r = client.get("/templates", params={"kind": "latex"})
    assert r.status_code == 200
    latex = r.json()
    assert len(latex) == len(calkit.templates.get_templates(kind="latex"))
    article = next(t for t in latex if t["name"] == "latex/article")
    assert article == {
        "name": "latex/article",
        "kind": "latex",
        "title": "Article (generic)",
        "description": calkit.templates.find_template(
            "latex/article"
        ).description,
    }
    assert all(t["kind"] == "latex" and t["title"] for t in latex)
    # A project template is named the way a hub names a project, since that
    # is what gets sent back to create one -- not `project/example-r`
    r = client.get("/templates", params={"kind": "project"})
    assert r.status_code == 200
    projects = r.json()
    assert projects[0]["name"] == "calkit/example-basic"
    assert {t["kind"] for t in projects} == {"project"}
    assert all(t["title"] and t["description"] for t in projects)
    # Registry order, so the list is offered in the order it was written
    assert [t["name"] for t in projects] == [
        t.ref for t in calkit.templates.get_templates(kind="project")
    ]
    # A kind the registry doesn't have
    r = client.get("/templates", params={"kind": "nope"})
    assert r.status_code == 404


def test_github_webhook_only_accepts_signed_pushes(
    client: TestClient, monkeypatch
) -> None:
    import hashlib
    import hmac
    import json

    import app.tasks

    queued: list[tuple[str, str]] = []
    monkeypatch.setattr(
        app.tasks,
        "enqueue_warm",
        lambda owner, name: bool(queued.append((owner, name))) or True,
    )
    body = json.dumps({"repository": {"full_name": "someone/nothing"}})

    def post(content, event="push", signature=None, secret="s3cret"):
        raw = content.encode() if isinstance(content, str) else content
        if signature is None:
            signature = (
                "sha256="
                + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
            )
        return client.post(
            "/events/github",
            content=raw,
            headers={
                "x-hub-signature-256": signature,
                "x-github-event": event,
            },
        )

    # With no secret configured there is no way to tell a real delivery from
    # anyone who found the URL, so nothing is accepted
    monkeypatch.setattr(settings, "GH_WEBHOOK_SECRET", None)
    assert post(body).status_code == 503
    monkeypatch.setattr(settings, "GH_WEBHOOK_SECRET", "s3cret")
    # A payload naming a project to spend server time on has to be signed
    assert post(body, signature="sha256=deadbeef").status_code == 401
    assert post(body, secret="wrong").status_code == 401
    # Signed, but not something to act on
    assert post(body, event="ping").json() == {"message": "Ignored"}
    # Signed and well-formed, but no project tracks that repo
    assert post(body).json() == {"message": "Ignored"}
    assert queued == []
    # Signed by GitHub but not the shape we expect: a bad request, not a
    # server error
    assert post("{not json").status_code == 400
    assert post("[1, 2, 3]").status_code == 400
    assert post("{}").json() == {"message": "Ignored"}


def test_get_hub_stats(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def add_project(account_id: uuid.UUID, **kwargs: Any) -> Project:
        project = Project(
            name=f"proj-{uuid.uuid4().hex[:8]}",
            title="Project",
            git_repo_url="https://github.com/someone/proj",
            owner_account_id=account_id,
            **kwargs,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return project

    # Mixpanel isn't read from until a scenario below configures it, even
    # where a local .env has the credentials
    for name in [
        "MIXPANEL_SERVICE_ACCOUNT_USERNAME",
        "MIXPANEL_SERVICE_ACCOUNT_SECRET",
        "MIXPANEL_PROJECT_ID",
    ]:
        monkeypatch.setattr(settings, name, None)
    # Superusers only
    assert client.get("/stats").status_code == 401
    r = client.get("/stats", headers=normal_user_token_headers)
    assert r.status_code == 403
    # A personal access token works, so a script can fetch these
    r = client.post(
        "/user/tokens",
        headers=superuser_token_headers,
        json={"expires_days": 1, "scope": None, "description": "stats"},
    )
    assert r.status_code == 200
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    before = client.get("/stats", headers=headers).json()
    # A user with a project worked on, one left after creation, and a
    # subproject, which counts with its parent rather than on its own
    now = utcnow()
    user = users.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(), password=random_lower_string()
        ),
    )
    user.email_verified_at = now
    db.add(user)
    other = users.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(), password=random_lower_string()
        ),
    )
    superuser = users.get_user_by_email(
        session=db, email=settings.FIRST_SUPERUSER
    )
    assert superuser is not None
    worked_on = add_project(
        user.account.id,
        is_public=True,
        created=now - timedelta(days=10),
        updated=now,
    )
    add_project(
        user.account.id,
        created=now - timedelta(days=200),
        updated=now - timedelta(days=200),
    )
    add_project(user.account.id, parent_project_id=worked_on.id)
    add_project(other.account.id)
    add_project(superuser.account.id)
    after = client.get("/stats", headers=headers).json()
    assert superuser.account.name in after["excluded_accounts"]
    assert after["users"]["total"] - before["users"]["total"] == 2
    assert after["users"]["verified"] - before["users"]["verified"] == 1
    # Verified is a sign of a person; a bare password signup isn't
    assert (
        after["users"]["likely_human"] - before["users"]["likely_human"] == 1
    )
    diff = {
        k: after["projects"][k] - before["projects"][k]
        for k in after["projects"]
    }
    assert diff == {
        "total": 3,
        "public": 1,
        "private": 2,
        "owners": 2,
        "worked_on": 1,
        "updated_last_90_days": 2,
    }
    # Leaving out another account by name, and putting superusers back in
    r = client.get(
        "/stats",
        headers=headers,
        params={
            "exclude": [other.account.name.upper()],
            "include_superusers": True,
        },
    )
    stats = r.json()
    assert stats["excluded_accounts"] == [other.account.name]
    assert stats["users"]["total"] == after["users"]["total"] - 1 + len(
        after["excluded_accounts"]
    )
    # One project fewer for the excluded account, at least one more for
    # superusers
    assert stats["projects"]["total"] >= after["projects"]["total"]

    # Each sign of a person counts a user as likely human on its own, while
    # sessions on just one day don't
    def add_user(github_username: str | None = None) -> User:
        return users.create_user(
            session=db,
            user_create=UserCreate(
                email=random_email(),
                password=random_lower_string(),
                github_username=github_username,
            ),
        )

    def add_refresh_token(user_id: uuid.UUID, created: datetime) -> None:
        db.add(
            RefreshToken(
                user_id=user_id,
                token_hash=uuid.uuid4().hex,
                created=created,
                expires=now + timedelta(days=30),
            )
        )

    add_user(github_username=f"gh-{uuid.uuid4().hex[:8]}")
    db.add(
        UserExternalCredential(
            user_id=add_user().id, provider="overleaf", secret_payload="x"
        )
    )
    db.add(
        UserProjectAccess(
            user_id=add_user().id,
            project_id=worked_on.id,
            role_id=ROLE_IDS["write"],
        )
    )
    # Access cached from GitHub with no role isn't an invitation
    db.add(UserProjectAccess(user_id=add_user().id, project_id=worked_on.id))
    db.add(
        UserToken(
            user_id=add_user().id,
            expires=now + timedelta(days=1),
            is_active=True,
        )
    )
    returning = add_user()
    add_refresh_token(returning.id, now)
    add_refresh_token(returning.id, now - timedelta(days=2))
    one_day = add_user()
    add_refresh_token(one_day.id, now)
    add_refresh_token(one_day.id, now - timedelta(minutes=5))
    db.commit()
    base = client.get("/stats", headers=headers).json()
    assert base["users"]["total"] - after["users"]["total"] == 7
    assert base["users"]["likely_human"] - after["users"]["likely_human"] == 5
    # Without Mixpanel read access configured there are no analytics
    assert base["analytics"] is None
    # With it, people are counted from the event export. Users count if
    # they're likely human, and others only if they did something, with a
    # device's events folded into the user it later signed in as. Anonymous
    # page views, automated browsers, old events, and excluded users don't.
    now_ts = time.time()
    pageview = "$mp_web_page_view"
    events = [
        ("Logged in", {"distinct_id": str(user.id), "time": now_ts - 3600}),
        (
            pageview,
            {"distinct_id": str(user.id), "time": now_ts - 20 * 86400},
        ),
        (
            "Clicked login",
            {
                "distinct_id": str(other.id),
                "$user_id": str(other.id),
                "$device_id": "abc",
                "time": now_ts - 3 * 86400,
            },
        ),
        (
            pageview,
            {
                "distinct_id": "$device:abc",
                "interacted": True,
                "time": now_ts - 5 * 86400,
            },
        ),
        (
            pageview,
            {
                "distinct_id": "$device:def",
                "interacted": True,
                "time": now_ts - 10 * 86400,
            },
        ),
        (
            pageview,
            {
                "distinct_id": "$device:idle",
                "interacted": False,
                "time": now_ts - 2 * 86400,
            },
        ),
        ("Logged in", {"distinct_id": str(superuser.id), "time": now_ts - 60}),
        (
            pageview,
            {"distinct_id": "a1b2", "anonymous": True, "time": now_ts - 60},
        ),
        (
            "Clicked",
            {"distinct_id": "$device:bot", "bot": True, "time": now_ts},
        ),
        (
            pageview,
            {
                "distinct_id": "$device:driven",
                "webdriver": True,
                "interacted": True,
                "time": now_ts,
            },
        ),
        (
            "Clicked",
            {"distinct_id": "$device:old", "time": now_ts - 40 * 86400},
        ),
    ]
    lines = [
        json.dumps({"event": e, "properties": p}).encode() for e, p in events
    ]
    resp = SimpleNamespace(
        raise_for_status=lambda: None, iter_lines=lambda: iter([*lines, b""])
    )
    with (
        patch.multiple(
            settings,
            MIXPANEL_SERVICE_ACCOUNT_USERNAME="sa",
            MIXPANEL_SERVICE_ACCOUNT_SECRET="secret",
            MIXPANEL_PROJECT_ID=123,
        ),
        patch("app.mixpanel.cache.get_json", return_value=None),
        patch("app.mixpanel.cache.set_json") as set_json,
        patch("app.mixpanel.requests.get", return_value=resp) as get,
    ):
        stats = client.get("/stats", headers=headers).json()
        assert get.call_args.kwargs["auth"] == ("sa", "secret")
        params = get.call_args.kwargs["params"]
        assert params["project_id"] == 123
        assert "anonymous" in params["where"]
        set_json.assert_called_once()
        assert stats["users"] == base["users"]
        # The other user isn't likely human yet, so is in neither count
        assert stats["analytics"] == {
            "active_users": {
                "last_day": 1,
                "last_7_days": 1,
                "last_30_days": 1,
            },
            "active_visitors": {
                "last_day": 1,
                "last_7_days": 1,
                "last_30_days": 2,
            },
        }
        # Once they are, they count, with their earlier device folded in
        db.add(
            UserToken(
                user_id=other.id,
                expires=now + timedelta(days=1),
                is_active=True,
            )
        )
        db.commit()
        stats = client.get("/stats", headers=headers).json()
        assert stats["analytics"] == {
            "active_users": {
                "last_day": 1,
                "last_7_days": 2,
                "last_30_days": 2,
            },
            "active_visitors": {
                "last_day": 1,
                "last_7_days": 2,
                "last_30_days": 3,
            },
        }
        # Excluded accounts are left out here too, and superusers come back
        stats = client.get(
            "/stats",
            headers=headers,
            params={
                "exclude": [other.account.name],
                "include_superusers": True,
            },
        ).json()
        assert stats["analytics"]["active_users"] == {
            "last_day": 2,
            "last_7_days": 2,
            "last_30_days": 2,
        }
        # A cached result is used without asking Mixpanel again
        get.reset_mock()
        cached = {str(user.id): [now_ts - 60, True]}
        with patch("app.mixpanel.cache.get_json", return_value=cached):
            stats = client.get("/stats", headers=headers).json()
        get.assert_not_called()
        assert stats["analytics"]["active_users"]["last_day"] == 1
        # Mixpanel failing, by connection or status, leaves analytics out
        # rather than failing the request
        get.side_effect = requests.ConnectionError("down")
        r = client.get("/stats", headers=headers)
        assert r.status_code == 200
        assert r.json()["analytics"] is None
        assert r.json()["users"]["total"] == base["users"]["total"]
        get.side_effect = None
        get.return_value = SimpleNamespace(
            raise_for_status=Mock(side_effect=requests.HTTPError("401"))
        )
        stats = client.get("/stats", headers=headers).json()
        assert stats["analytics"] is None
        assert stats["projects"] == base["projects"]
