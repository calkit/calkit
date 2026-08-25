"""Tests for app.api.routes.misc endpoints."""

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

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


def test_get_templates(client: TestClient) -> None:
    from calkit.templates.core import TEMPLATES

    # Every kind, no login needed
    r = client.get(f"{settings.API_V1_STR}/templates")
    assert r.status_code == 200, r.text
    names = {t["name"] for t in r.json()}
    assert names == {
        f"{kind}/{name}" for kind, ts in TEMPLATES.items() for name in ts
    }
    # One kind, with what a picker shows
    r = client.get(
        f"{settings.API_V1_STR}/templates", params={"kind": "latex"}
    )
    assert r.status_code == 200
    latex = r.json()
    assert len(latex) == len(TEMPLATES["latex"])
    article = next(t for t in latex if t["name"] == "latex/article")
    assert article == {
        "name": "latex/article",
        "kind": "latex",
        "title": "Article (generic)",
        "description": TEMPLATES["latex"]["article"].description,
    }
    assert all(t["kind"] == "latex" and t["title"] for t in latex)
    # A kind the registry doesn't have
    r = client.get(f"{settings.API_V1_STR}/templates", params={"kind": "nope"})
    assert r.status_code == 404
