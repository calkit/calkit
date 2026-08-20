"""Tests for app.api.routes.misc endpoints."""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import settings


def test_get_arxiv_pdf_requires_auth(client: TestClient) -> None:
    resp = client.get(f"{settings.API_V1_STR}/arxiv/2301.01234/pdf")
    assert resp.status_code == 401


def test_get_arxiv_pdf_rejects_a_non_id(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """The ID check is what keeps this from proxying arbitrary URLs."""
    with patch("app.api.routes.misc.requests.get") as get:
        resp = client.get(
            f"{settings.API_V1_STR}/arxiv/..%2F..%2Fetc%2Fpasswd/pdf",
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
            f"{settings.API_V1_STR}/arxiv/math.GT%2F0309136v2/pdf",
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
            f"{settings.API_V1_STR}/arxiv/2301.01234/pdf",
            headers=normal_user_token_headers,
        )
    assert resp.status_code == 404
    # Giving up before streaming has to close it too
    assert fake.closed == [True]


def test_get_version_needs_no_auth(client: TestClient) -> None:
    """Clients check what a hub supports before they have credentials."""
    resp = client.get(f"{settings.API_V1_STR}/version")
    assert resp.status_code == 200
    assert resp.json()["version"]


def test_post_feedback(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    """Feedback is stored, listed for superusers, and emailed best-effort."""
    url = f"{settings.API_V1_STR}/feedback"
    assert client.post(url, json={"message": "hi"}).status_code == 401
    with (
        patch("app.config.settings.SMTP_HOST", "smtp.example.com"),
        patch("app.config.settings.EMAILS_FROM_EMAIL", "hub@example.com"),
        patch("app.config.settings.FEEDBACK_EMAIL", "ops@example.com"),
        patch("app.api.routes.misc.send_email") as send,
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
            "app.api.routes.misc.send_email",
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
