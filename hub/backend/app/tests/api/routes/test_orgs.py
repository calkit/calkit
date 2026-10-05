"""Tests for the org routes."""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from httpx import Response


def test_post_org(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    github_name = f"Org-{uuid.uuid4().hex[:8]}"
    installed = False
    membership: tuple[int, dict[str, str]] = (404, {})

    def fake_get(
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> SimpleNamespace:
        if url.endswith("/installation"):
            code = 200 if installed else 404
            return SimpleNamespace(status_code=code, json=lambda: {"id": 1})
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
    # Someone outside the org can't add it
    installed = True
    membership = (404, {})
    assert post().status_code == 404
    # Nor can someone only invited to it
    membership = (200, {"role": "member", "state": "pending"})
    assert post().status_code == 400
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
