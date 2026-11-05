"""Tests for declaring misc artifacts."""

import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import git
from fastapi.testclient import TestClient

from app.core import ryaml

URL = "/projects/o/p/misc"


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
    (wdir / "box.csv").write_bytes(b"a,b")
    (wdir / "sheet.csv").write_bytes(b"c,d")
    with open(wdir / "calkit.yaml", "w") as f:
        ryaml.dump(
            {
                "name": "p",
                "figures": [{"path": "figures/x.png"}],
                "datasets": [
                    {"path": "box.csv", "imported_from": "Our Box folder"},
                    {"path": "sheet.csv", "imported_from": "My laptop"},
                ],
            },
            f,
        )
    repo.git.add(all=True)
    repo.git.commit("-m", "Initial")
    repo.create_remote("origin", str(origin.working_dir))
    repo.git.push("origin", repo.active_branch.name)
    fake_project = SimpleNamespace(
        owner_account_name="o",
        name="p",
        id=uuid.uuid4(),
        owner_github_name="o",
        git_repo_url="https://github.com/o/p",
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
        # A person can't be the origin of an exported format like PNG
        resp = client.post(
            URL,
            json={
                "path": "figures/x.png",
                "created_by": [{"email": "a@example.com"}],
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 422, resp.text
        # A declared figure without an origin gets one on its own entry,
        # and after that is edited as what it is
        resp = client.post(
            URL,
            json={
                "path": "figures/x.png",
                "imported_from": {"url": "https://example.org/x.png"},
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        with open(wdir / "calkit.yaml") as f:
            assert ryaml.load(f)["figures"] == [
                {
                    "path": "figures/x.png",
                    "imported_from": {"url": "https://example.org/x.png"},
                }
            ]
        resp = client.post(
            URL,
            json={
                "path": "figures/x.png",
                "imported_from": {"url": "https://example.org/y.png"},
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
        # An import that only describes where it's from can be given a
        # source someone can check, or be attested to instead
        resp = client.post(
            URL,
            json={
                "path": "box.csv",
                "imported_from": {"url": "https://example.org/box.csv"},
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        resp = client.post(
            URL,
            json={
                "path": "sheet.csv",
                "created_by": [{"email": "a@example.com"}],
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        with open(wdir / "calkit.yaml") as f:
            assert ryaml.load(f)["datasets"] == [
                {
                    "path": "box.csv",
                    "imported_from": {"url": "https://example.org/box.csv"},
                },
                {
                    "path": "sheet.csv",
                    "created_by": [{"email": "a@example.com"}],
                },
            ]
        # Once it's checkable, it's edited as what it is
        resp = client.post(
            URL,
            json={
                "path": "box.csv",
                "created_by": [{"email": "a@example.com"}],
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 400, resp.text
        # A path that isn't in the project can't be attributed
        resp = client.post(
            URL,
            json={
                "path": "missing.jpg",
                "created_by": [{"email": "a@example.com"}],
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 404, resp.text
    with open(wdir / "calkit.yaml") as f:
        assert len(ryaml.load(f)["misc"]) == 2
