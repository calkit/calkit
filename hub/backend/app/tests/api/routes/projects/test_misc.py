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


def test_post_project_import_update(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    import json

    import pytest
    from fastapi import HTTPException

    import app.imports

    repos = {}
    for name in ["p", "src"]:
        origin = git.Repo.init(tmp_path / f"{name}.git", bare=True)
        repo = git.Repo.init(tmp_path / name)
        with repo.config_writer() as cw:
            cw.set_value("user", "name", "Test")
            cw.set_value("user", "email", "test@example.com")
        os.makedirs(tmp_path / name / "figures")
        (tmp_path / name / "figures" / "plot.png").write_bytes(b"v1")
        (tmp_path / name / "calkit.yaml").write_text(f"name: {name}\n")
        repo.git.add(all=True)
        repo.git.commit("-m", "Initial")
        repo.create_remote("origin", str(origin.working_dir))
        repo.git.push("origin", repo.active_branch.name)
        repos[name] = repo
    repo, src = repos["p"], repos["src"]
    wdir = tmp_path / "p"

    def project(**kwargs):
        name = kwargs["project_name"]
        return SimpleNamespace(
            owner_account_name="o",
            name=name,
            id=uuid.uuid4(),
            owner_github_name="o",
            git_repo_url=f"https://github.com/o/{name}",
        )

    def fetch_git_path(repo_url, rev, src_path, repo_dir, dest):
        assert (repo_url, rev, src_path) == (
            "https://github.com/a/b",
            "main",
            "fig.png",
        )
        Path(repo_dir, dest).write_bytes(b"from git")
        return "abc1234"

    def locks():
        return json.loads((wdir / ".calkit" / "imports.json").read_text())

    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            side_effect=project,
        ),
        patch(
            "app.api.routes.projects.core.get_repo",
            side_effect=lambda project, **kwargs: repos[project.name],
        ),
        patch("app.api.routes.projects.core.record_project_update"),
        patch(
            "app.api.routes.projects.core.app.imports.fetch_git_path",
            side_effect=fetch_git_path,
        ),
    ):
        # Imported from another project, which is fetched, even over what
        # Overleaf had, and recorded at the commit it came from
        (wdir / "paper").mkdir()
        (wdir / "paper" / "plot.png").write_bytes(b"pasted")
        resp = client.post(
            URL,
            json={
                "path": "paper/plot.png",
                "imported_from": {
                    "project": "o/src",
                    "path": "figures/plot.png",
                },
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert (wdir / "paper" / "plot.png").read_bytes() == b"v1"
        assert locks()["paper/plot.png"]["rev"] == src.head.commit.hexsha
        assert not repo.git.status("--porcelain")
        # Nothing new
        update = "/projects/o/p/imports/update"
        resp = client.post(
            update,
            json={"path": "paper/plot.png"},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["changed"] is False
        assert (
            repo.head.commit.message.strip()
            == "Add misc artifact paper/plot.png"
        )
        # Something new
        (tmp_path / "src" / "figures" / "plot.png").write_bytes(b"v2")
        src.git.commit("-am", "Update plot")
        resp = client.post(
            update,
            json={"path": "paper/plot.png"},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "path": "paper/plot.png",
            "changed": True,
            "rev": src.head.commit.hexsha,
        }
        assert (wdir / "paper" / "plot.png").read_bytes() == b"v2"
        assert locks()["paper/plot.png"]["rev"] == src.head.commit.hexsha
        assert repo.head.commit.message.strip() == (
            "Update paper/plot.png from its source"
        )
        # Edited here since, which updating would discard
        (wdir / "paper" / "plot.png").write_bytes(b"mine")
        resp = client.post(
            update,
            json={"path": "paper/plot.png"},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 409, resp.text
        (wdir / "paper" / "plot.png").write_bytes(b"v2")
        # Imported from a Git repo, which needn't be here yet
        resp = client.post(
            URL,
            json={
                "path": "paper/fig.png",
                "imported_from": {
                    "git_repo_url": "https://github.com/a/b",
                    "git_ref": "main",
                    "path": "fig.png",
                },
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert (wdir / "paper" / "fig.png").read_bytes() == b"from git"
        assert locks()["paper/fig.png"]["rev"] == "abc1234"
        # Only a Git repo or project can be updated from
        resp = client.post(
            URL,
            json={
                "path": "figures/plot.png",
                "imported_from": {"doi": "10.5281/zenodo.1234567"},
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        resp = client.post(
            update,
            json={"path": "figures/plot.png"},
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 422, resp.text
    # A Git repo has to be fetched over https, not from the server's disk
    with pytest.raises(HTTPException) as e:
        app.imports.fetch_git_path(
            f"file://{tmp_path / 'src'}",
            None,
            "figures/plot.png",
            str(wdir),
            "x",
        )
    assert e.value.status_code == 422
