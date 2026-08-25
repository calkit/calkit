"""Tests for declaring misc artifacts."""

import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import git
from fastapi.testclient import TestClient

from app.config import settings
from app.core import ryaml

URL = f"{settings.API_V1_STR}/projects/o/p/misc"


def test_post_project_misc(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    origin = git.Repo.init(tmp_path / "origin.git", bare=True)
    repo = git.Repo.init(tmp_path / "repo")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    wdir = tmp_path / "repo"
    os.makedirs(wdir / "figures")
    (wdir / "figures" / "x.png").write_bytes(b"png")
    (wdir / "photo.jpg").write_bytes(b"jpg")
    (wdir / "logo.png").write_bytes(b"logo")
    (wdir / "notes.txt").write_bytes(b"notes")
    with open(wdir / "calkit.yaml", "w") as f:
        ryaml.dump({"name": "p", "figures": [{"path": "figures/x.png"}]}, f)
    repo.git.add(all=True)
    repo.git.commit("-m", "Initial")
    repo.create_remote("origin", str(origin.working_dir))
    repo.git.push("origin", repo.active_branch.name)
    fake_project = SimpleNamespace(
        owner_account_name="o", name="p", id=uuid.uuid4()
    )
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch("app.api.routes.projects.core.get_repo", return_value=repo),
        patch("app.api.routes.projects.core.record_project_update"),
    ):
        # Attesting to who made a file
        resp = client.post(
            URL,
            json={
                "path": "./photo.jpg",
                "title": "Site photo",
                "created_by": [
                    {
                        "email": "a@example.com",
                        "name": "A",
                        "orcid": None,
                        "with_ai": ["Claude"],
                    }
                ],
                "message": "Attest photo",
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "path": "photo.jpg",
            "title": "Site photo",
            "description": None,
            "created_by": [
                {"email": "a@example.com", "name": "A", "with_ai": ["Claude"]}
            ],
            "imported_from": None,
        }
        assert repo.head.commit.message.strip() == "Attest photo"
        assert origin.head.commit.hexsha == repo.head.commit.hexsha
        # Recording where a file came from
        resp = client.post(
            URL,
            json={
                "path": "logo.png",
                "imported_from": {"url": "https://example.org/logo.png"},
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["imported_from"] == {
            "url": "https://example.org/logo.png"
        }
        assert repo.head.commit.message.strip() == "Add misc artifact logo.png"
        with open(wdir / "calkit.yaml") as f:
            ck_info = ryaml.load(f)
        assert ck_info["misc"] == [
            {
                "path": "photo.jpg",
                "title": "Site photo",
                "created_by": [
                    {
                        "email": "a@example.com",
                        "name": "A",
                        "with_ai": ["Claude"],
                    }
                ],
            },
            {
                "path": "logo.png",
                "imported_from": {"url": "https://example.org/logo.png"},
            },
        ]
        assert ck_info["figures"] == [{"path": "figures/x.png"}]
        # Made here or imported, not both, and not neither
        resp = client.post(
            URL,
            json={
                "path": "notes.txt",
                "created_by": [{"email": "a@example.com"}],
                "imported_from": {"url": "https://example.org/notes.txt"},
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 422, resp.text
        resp = client.post(
            URL, json={"path": "photo.jpg"}, headers=normal_user_token_headers
        )
        assert resp.status_code == 422, resp.text
        # Nobody named is not an attestation
        resp = client.post(
            URL,
            json={"path": "photo.jpg", "created_by": []},
            headers=normal_user_token_headers,
        )
        assert resp.status_code in (400, 422), resp.text
        # Something already declared is edited as what it is
        resp = client.post(
            URL,
            json={
                "path": "figures/x.png",
                "created_by": [{"email": "a@example.com"}],
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 400, resp.text
        assert "figure" in resp.json()["detail"]
        resp = client.post(
            URL,
            json={
                "path": "photo.jpg",
                "created_by": [{"email": "b@example.com"}],
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 400, resp.text
        assert "misc artifact" in resp.json()["detail"]
        # A path that isn't in the project can't be attributed
        resp = client.post(
            URL,
            json={
                "path": "missing.png",
                "created_by": [{"email": "a@example.com"}],
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 404, resp.text
    with open(wdir / "calkit.yaml") as f:
        assert len(ryaml.load(f)["misc"]) == 2
