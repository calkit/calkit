import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import settings

FEATURE = "external-releases-in-app"


def test_get_feature_vote_status(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"/feature-votes/{FEATURE}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["feature"] == FEATURE
    assert data["has_voted"] is False


def test_unknown_feature_404(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.get(
        "/feature-votes/bogus",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 404


def test_cast_feature_vote_is_idempotent(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"/feature-votes/{FEATURE}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    first = r.json()
    assert first["has_voted"] is True
    assert first["count"] >= 1
    r = client.post(
        f"/feature-votes/{FEATURE}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    second = r.json()
    assert second["has_voted"] is True
    # Voting again must not increment the count.
    assert second["count"] == first["count"]


def test_remove_feature_vote(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    client.post(
        f"/feature-votes/{FEATURE}",
        headers=normal_user_token_headers,
    )
    r = client.delete(
        f"/feature-votes/{FEATURE}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    assert r.json()["has_voted"] is False
    # Removing again is a no-op, not an error.
    r = client.delete(
        f"/feature-votes/{FEATURE}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    assert r.json()["has_voted"] is False


def test_get_feature_votes_for_admin(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    base = "/feature-votes"
    resp = client.post(
        f"{base}/local-workspace-compute", headers=normal_user_token_headers
    )
    assert resp.status_code == 200, resp.text
    # Only an admin sees the tally with names
    resp = client.get(base, headers=normal_user_token_headers)
    assert resp.status_code == 403
    resp = client.get(base, headers=superuser_token_headers)
    assert resp.status_code == 200, resp.text
    by_feature = {f["feature"]: f for f in resp.json()}
    # Every feature on offer is listed, voted for or not
    assert "external-releases-in-app" in by_feature
    votes = by_feature["local-workspace-compute"]
    assert votes["count"] >= 1
    voter = next(v for v in votes["voters"] if v["email"])
    assert set(voter) == {"email", "full_name", "account_name", "created"}
    # Unvoting takes the user off the list
    client.delete(
        f"{base}/local-workspace-compute", headers=normal_user_token_headers
    )
    resp = client.get(base, headers=superuser_token_headers)
    after = {f["feature"]: f for f in resp.json()}["local-workspace-compute"]
    assert after["count"] == votes["count"] - 1


def test_post_feedback(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    """Feedback is stored, listed for superusers, and emailed best-effort."""
    url = "/feedback"
    assert client.post(url, json={"message": "hi"}).status_code == 401
    with (
        patch("app.config.settings.SMTP_HOST", "smtp.example.com"),
        patch("app.config.settings.EMAILS_FROM_EMAIL", "hub@example.com"),
        patch("app.config.settings.FEEDBACK_EMAIL", "ops@example.com"),
        patch("app.api.routes.feedback.send_email") as send,
    ):
        resp = client.post(
            url,
            headers=normal_user_token_headers,
            json={
                "kind": "bug",
                "message": "It broke <script>alert(1)</script>",
                "page": "/some/project",
            },
        )
    assert resp.status_code == 200
    send.assert_called_once()
    kwargs = send.call_args.kwargs
    assert kwargs["email_to"] == "ops@example.com"
    assert "Bug report" in kwargs["subject"]
    body = kwargs["html_content"]
    assert "/some/project" in body
    assert settings.EMAIL_TEST_USER in body
    # A message is user-controlled text, so it can't carry markup into the
    # email we send ourselves.
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    # A relay that's down loses the notification, not the feedback.
    with (
        patch("app.config.settings.SMTP_HOST", "smtp.example.com"),
        patch("app.config.settings.EMAILS_FROM_EMAIL", "hub@example.com"),
        patch(
            "app.api.routes.feedback.send_email",
            side_effect=RuntimeError("relay down"),
        ),
    ):
        resp = client.post(
            url,
            headers=normal_user_token_headers,
            json={"message": "Sent while the relay was down"},
        )
    assert resp.status_code == 200
    # A hub with no SMTP at all still accepts it.
    with patch("app.config.settings.SMTP_HOST", None):
        resp = client.post(
            url, headers=normal_user_token_headers, json={"message": "no smtp"}
        )
    assert resp.status_code == 200
    # Listing is superuser-only, newest first.
    assert client.get(url).status_code == 401
    assert (
        client.get(url, headers=normal_user_token_headers).status_code == 403
    )
    listed = client.get(url, headers=superuser_token_headers).json()
    messages = [f["message"] for f in listed]
    assert "no smtp" in messages
    assert "Sent while the relay was down" in messages
    assert listed[0]["message"] == "no smtp"
    # A page has a ceiling; the whole table is not one request.
    resp = client.get(
        url, headers=superuser_token_headers, params={"limit": 1000}
    )
    assert resp.status_code == 422
    assert listed[0]["user_email"] == settings.EMAIL_TEST_USER
    assert listed[0]["resolved"] is False
    # Resolving, and putting it back.
    item_id = listed[0]["id"]
    patch_url = f"{url}/{item_id}"
    assert (
        client.patch(
            patch_url,
            headers=normal_user_token_headers,
            json={"resolved": True},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            patch_url, headers=superuser_token_headers, json={"resolved": True}
        ).status_code
        == 200
    )
    listed = client.get(url, headers=superuser_token_headers).json()
    assert next(f for f in listed if f["id"] == item_id)["resolved"] is True
    assert (
        client.patch(
            f"{url}/{uuid.uuid4()}",
            headers=superuser_token_headers,
            json={"resolved": True},
        ).status_code
        == 404
    )
    # An empty message has nothing to send, and one over the cap is rejected
    # rather than truncated.
    for bad in [{"message": ""}, {"message": "x" * 5001}]:
        resp = client.post(url, headers=normal_user_token_headers, json=bad)
        assert resp.status_code == 422
