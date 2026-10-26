"""Tests for the org routes."""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session

from app.models import Account, Org


def test_post_org(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    github_name = f"Org-{uuid.uuid4().hex[:8]}"
    install_status = 404
    membership: tuple[int, dict[str, str]] = (404, {})

    def fake_get(
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> SimpleNamespace:
        if url.endswith("/installation"):
            return SimpleNamespace(
                status_code=install_status, json=lambda: {"id": 1}, text=""
            )
        if "/memberships/" in url:
            code, body = membership
            return SimpleNamespace(status_code=code, json=lambda: body)
        return SimpleNamespace(status_code=200, json=lambda: {"name": None})

    def post() -> Response:
        with (
            patch("app.api.routes.orgs.requests.get", side_effect=fake_get),
            patch("app.api.routes.orgs.get_github_token", return_value="t"),
            patch("app.github.create_app_token", return_value="jwt"),
        ):
            return client.post(
                "/orgs",
                json={"github_name": github_name},
                headers=normal_user_token_headers,
            )

    # Without the app installed, not even a GitHub admin can add the org
    membership = (200, {"role": "admin", "state": "active"})
    resp = post()
    assert resp.status_code == 400
    assert "not installed" in resp.json()["detail"]
    # A failed lookup isn't reported as a missing installation
    install_status = 500
    assert post().status_code == 502
    # Someone outside the org can't add it
    install_status = 200
    membership = (404, {})
    assert post().status_code == 404
    # Nor can someone only invited to it
    membership = (200, {"role": "member", "state": "pending"})
    resp = post()
    assert resp.status_code == 400
    assert "pending invitation" in resp.json()["detail"]
    # A plain member can, and becomes the owner in Calkit
    membership = (200, {"role": "member", "state": "active"})
    resp = post()
    assert resp.status_code == 200, resp.text
    org = resp.json()
    assert org["name"] == github_name.lower()
    assert org["github_name"] == github_name
    assert org["display_name"] == github_name
    assert org["role"] == "owner"
    # And it can only be added once
    resp = post()
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"]
    # One added along with a repo by an outside collaborator has no members,
    # so a member from GitHub can still claim it
    github_name = f"Org-{uuid.uuid4().hex[:8]}"
    org = Org(
        account=Account(
            name=github_name.lower(),
            display_name="Unclaimed",
            github_name=github_name,
        )
    )
    db.add(org)
    db.commit()
    membership = (200, {"role": "member", "state": "pending"})
    assert post().status_code == 400
    membership = (200, {"role": "member", "state": "active"})
    resp = post()
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(org.id)
    assert resp.json()["display_name"] == "Unclaimed"
    assert resp.json()["role"] == "owner"
    # After which it's taken
    resp = post()
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"]
