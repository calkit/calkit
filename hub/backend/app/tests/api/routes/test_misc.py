"""Tests for app.api.routes.misc endpoints."""

import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import git
import pytest
from fastapi.testclient import TestClient

from app.api.routes import misc
from app.config import settings


def _make_repo(tmp_path) -> str:
    """A committed repo with a pipeline and calkit.yaml but no README."""
    path = tmp_path / "src"
    repo = git.Repo.init(path)
    (path / "calkit.yaml").write_text("datasets: []\n")
    (path / "dvc.yaml").write_text(
        "stages:\n  plot:\n    cmd: python plot.py\n    outs:\n      - fig.png\n"
    )
    (path / "plot.py").write_text("print('hi')\n")
    (path / "loose.py").write_text("print('nobody runs me')\n")
    repo.index.add(["calkit.yaml", "dvc.yaml", "plot.py", "loose.py"])
    repo.index.commit("Initial")
    return str(path)


@pytest.mark.parametrize(
    "url", ["https://gitlab.com/a/b", "github.com/onlyowner", "not a url"]
)
def test_check_public_repo_rejects_bad_urls(client: TestClient, url) -> None:
    with patch.object(misc, "_public_repo_head") as head:
        resp = client.get("/repo-check", params={"url": url})
    assert resp.status_code == 422
    head.assert_not_called()


def test_check_public_repo_reports_on_a_shallow_clone(
    client: TestClient, tmp_path
) -> None:
    src = _make_repo(tmp_path)
    with (
        patch.object(misc, "_public_repo_head", return_value="abc123"),
        patch.object(
            misc,
            "_clone_public_repo",
            side_effect=lambda url, dest: shutil.copytree(src, dest),
        ) as clone,
    ):
        resp = client.get(
            "/repo-check", params={"url": "github.com/someone/repo.git"}
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["owner"] == "someone"
    assert body["name"] == "repo"
    assert body["commit"] == "abc123"
    assert clone.call_args.args[0] == "https://github.com/someone/repo.git"
    check = body["check"]
    assert check["has_pipeline"] is True
    assert check["has_calkit_info"] is True
    assert check["has_readme"] is False
    assert check["n_stages"] == 1
    assert check["scripts_not_in_pipeline"] == ["loose.py"]


def test_check_public_repo_not_found(client: TestClient) -> None:
    with patch.object(misc, "_public_repo_head", return_value=None):
        resp = client.get("/repo-check", params={"url": "github.com/a/b"})
    assert resp.status_code == 404
    with (
        patch.object(misc, "_public_repo_head", return_value="abc123"),
        patch.object(
            misc,
            "_clone_public_repo",
            side_effect=subprocess.CalledProcessError(128, "git"),
        ),
    ):
        resp = client.get("/repo-check", params={"url": "github.com/a/b"})
    assert resp.status_code == 404


def test_check_public_repo_rate_limits(client: TestClient) -> None:
    misc._repo_check_hits.clear()
    with (
        patch.object(misc, "REPO_CHECK_LIMIT_PER_CLIENT", (2, 600)),
        patch.object(misc, "_public_repo_head", return_value=None) as head,
    ):
        for _ in range(2):
            resp = client.get("/repo-check", params={"url": "github.com/a/b"})
            assert resp.status_code == 404
        resp = client.get("/repo-check", params={"url": "github.com/a/b"})
        assert resp.status_code == 429
        # Another client is counted separately
        resp = client.get(
            "/repo-check",
            params={"url": "github.com/a/b"},
            headers={"x-forwarded-for": "203.0.113.9, 10.0.0.1"},
        )
        assert resp.status_code == 404
    assert head.call_count == 3
    misc._repo_check_hits.clear()


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
    from calkit.templates.core import TEMPLATES

    # Every kind, no login needed
    r = client.get("/templates")
    assert r.status_code == 200, r.text
    names = {t["name"] for t in r.json()}
    assert names == {
        f"{kind}/{name}" for kind, ts in TEMPLATES.items() for name in ts
    }
    # One kind, with what a picker shows
    r = client.get("/templates", params={"kind": "latex"})
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
