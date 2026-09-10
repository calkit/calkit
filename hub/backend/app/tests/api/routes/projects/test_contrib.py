"""Tests for contribution request routes: the review-by-link round trip."""

import shutil
import uuid
from pathlib import Path
from unittest.mock import patch

import git
import yaml
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import settings
from app.models import Project
from app.users import get_user_by_email

FIXTURES = Path(__file__).parents[7] / "test" / "docx"


def _make_repo(tmp_path):
    origin = git.Repo.init(tmp_path / "origin.git", bare=True)
    repo = git.Repo.init(tmp_path / "repo")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    wdir = Path(repo.working_dir)
    (wdir / "paper").mkdir()
    for name in ["main.tex", "methods.tex"]:
        shutil.copy(FIXTURES / name, wdir / "paper" / name)
    shutil.copy(
        FIXTURES / "export.docx", wdir / "paper" / "main-for-review.docx"
    )
    (wdir / "calkit.yaml").write_text("")
    repo.git.add(all=True)
    repo.git.commit("-m", "Initial")
    repo.create_remote("origin", str(origin.working_dir))
    repo.git.push("origin", repo.active_branch.name)
    return repo, origin


def _make_project(db: Session) -> Project:
    user = get_user_by_email(session=db, email=settings.EMAIL_TEST_USER)
    assert user is not None
    project = Project(
        id=uuid.uuid4(),
        name=f"contrib-{uuid.uuid4().hex[:8]}",
        title="Contrib test",
        git_repo_url="https://github.com/x/y",
        owner_account_id=user.account.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def test_review_request_round_trip(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
    tmp_path,
) -> None:
    project = _make_project(db)
    owner = project.owner_account_name
    url = f"/projects/{owner}/{project.name}/contrib-requests"
    repo, origin = _make_repo(tmp_path)
    wdir = Path(repo.working_dir)
    stored: dict[str, bytes] = {}
    sent: list[dict] = []
    with (
        patch("app.api.routes.projects.contrib.get_repo", return_value=repo),
        patch(
            "app.api.routes.projects.contrib.messaging.send_email",
            side_effect=lambda **kw: sent.append(kw),
        ),
        patch.object(settings, "SMTP_HOST", "smtp.example.org"),
        patch.object(settings, "EMAILS_FROM_EMAIL", "noreply@example.org"),
        patch("app.api.routes.projects.reviews.get_repo", return_value=repo),
        patch(
            "app.api.routes.projects.reviews._store",
            side_effect=lambda project, md5, data: stored.__setitem__(
                md5, data
            ),
        ),
    ):
        # A document that isn't in the project is refused
        resp = client.post(
            url,
            json={
                "title": "Please review the draft",
                "target_kind": "publication",
                "target_path": "paper/main.pdf",
                "document_path": "paper/nope.docx",
                "email": "pi@example.org",
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 422, resp.text
        # Sending records the request in the repo and mints a link
        resp = client.post(
            url,
            json={
                "title": "Please review the draft",
                "message": "Section 3 especially.",
                "target_kind": "publication",
                "target_path": "paper/main.pdf",
                "document_path": "paper/main-for-review.docx",
                "permission": "suggest",
                "email": "PI@example.org",
                "contributor_name": "P. I.",
                "expires_days": 30,
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        created = resp.json()
        token = created["token"]
        assert created["url"].endswith(f"/review/{token}")
        assert created["email"] == "pi@example.org"
        assert created["git_rev"] == origin.head.commit.parents[0].hexsha
        assert created["email_sent"] is True
        assert sent[0]["email_to"] == "pi@example.org"
        assert created["url"] in sent[0]["html_content"]
        assert "Section 3 especially." in sent[0]["html_content"]
        request_id = created["id"]
        record_path = wdir / ".calkit" / "requests" / f"{request_id}.yaml"
        record = yaml.safe_load(record_path.read_text())
        assert record["target"] == {
            "kind": "publication",
            "path": "paper/main.pdf",
        }
        assert record["document"] == "paper/main-for-review.docx"
        assert record["to"] == {"name": "P. I.", "email": "pi@example.org"}
        assert record["status"] == "open"
        assert record["responses"] == []
        assert repo.git.log("--format=%s", "-1") == (
            "Request review of paper/main.pdf from P. I."
        )
        assert origin.head.commit.hexsha == repo.head.commit.hexsha
        # The lead's list never includes the token
        resp = client.get(
            url,
            params={"target_path": "paper/main.pdf"},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert [r["id"] for r in resp.json()] == [request_id]
        assert "token" not in resp.json()[0]
        assert resp.json()[0]["response_count"] == 0
        # The recipient sees the ask without signing in
        resp = client.get(f"/contrib-requests/{token}")
        assert resp.status_code == 200, resp.text
        view = resp.json()
        assert view["title"] == "Please review the draft"
        assert view["project_name"] == project.name
        assert view["document_path"] == "paper/main-for-review.docx"
        assert view["can_respond"] is True
        assert view["responder_email"] == "pi@example.org"
        assert client.get("/contrib-requests/not-a-token").status_code == 404
        # And downloads the Word copy
        resp = client.get(f"/contrib-requests/{token}/document")
        assert resp.status_code == 200, resp.text
        assert resp.content == (FIXTURES / "export.docx").read_bytes()
        assert "main-for-review.docx" in resp.headers["content-disposition"]
        # Sending it back saves it under reviews/, authored by the reviewer
        resp = client.post(
            f"/contrib-requests/{token}/responses",
            data={"responder_name": "P. I.", "message": "Some thoughts."},
            files={
                "file": (
                    "main-for-review.docx",
                    (FIXTURES / "returned.docx").read_bytes(),
                    "application/octet-stream",
                )
            },
        )
        assert resp.status_code == 200, resp.text
        response = resp.json()
        assert response["status"] == "submitted"
        assert response["responder_email"] == "pi@example.org"
        assert response["attachments"][0]["filename"] == (
            "reviews/main-for-review-P-I.docx"
        )
        assert (wdir / "reviews/main-for-review-P-I.docx.dvc").is_file()
        assert len(stored) == 1
        head = repo.head.commit
        assert (
            head.message.strip() == "Add review of paper/main.pdf from P. I."
        )
        assert head.author.name == "P. I."
        assert head.author.email == "pi@example.org"
        assert origin.head.commit.hexsha == head.hexsha
        record = yaml.safe_load(record_path.read_text())
        assert record["responses"][0]["path"] == (
            "reviews/main-for-review-P-I.docx"
        )
        assert record["responses"][0]["message"] == "Some thoughts."
        # The lead sees the response on the request, and the review shows
        # up where reviews are triaged
        resp = client.get(url, headers=normal_user_token_headers)
        assert resp.json()[0]["response_count"] == 1
        assert resp.json()[0]["responses"][0]["responder_name"] == "P. I."
        resp = client.get(
            f"/projects/{owner}/{project.name}/latex-reviews",
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert [r["path"] for r in resp.json()] == [
            "reviews/main-for-review-P-I.docx"
        ]
        assert resp.json()[0]["open_edits"] == 2
        # Closing is recorded in the repo and stops further responses
        resp = client.patch(
            f"{url}/{request_id}",
            json={"closed": True},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["closed_at"] is not None
        assert yaml.safe_load(record_path.read_text())["status"] == "closed"
        assert repo.git.log("--format=%s", "-1") == (
            "Close review request for paper/main.pdf"
        )
        assert client.get(f"/contrib-requests/{token}").json()[
            "can_respond"
        ] is (False)
        resp = client.post(
            f"/contrib-requests/{token}/responses",
            files={"file": ("x.docx", b"x", "application/octet-stream")},
        )
        assert resp.status_code == 403


def test_contrib_requests_require_write_access(
    client: TestClient, db: Session
) -> None:
    project = _make_project(db)
    url = f"/projects/{project.owner_account_name}/{project.name}/contrib-requests"
    assert client.get(url).status_code == 401
    assert client.post(url, json={"title": "x"}).status_code == 401
