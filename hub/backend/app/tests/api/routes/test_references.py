"""Tests for app.api.routes.references endpoints."""

import os
from unittest.mock import patch

import git
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core import ryaml
from app.tests.api.routes.projects.test_core import _make_owner_with_project


def test_get_user_reference_matches(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    repo_dir = tmp_path / "repo"
    os.makedirs(repo_dir)
    repo = git.Repo.init(path=repo_dir)
    # The test container has no committer
    repo.git.config(["user.email", "test@example.com"])
    repo.git.config(["user.name", "Calkit Test"])
    with open(repo_dir / "calkit.yaml", "w") as f:
        ryaml.dump({"references": [{"path": "refs.bib"}]}, f)
    with open(repo_dir / "refs.bib", "w") as f:
        f.write(
            "@article{smith2020,\n"
            "  title = {A Study of Things},\n"
            "  doi = {10.1234/ABCD},\n"
            "  comment = {Some note},\n"
            "}\n"
            "@article{jones2021,\n"
            "  title = {Another Paper},\n"
            "  eprint = {2301.01234v2},\n"
            "}\n"
        )
    repo.git.add(["-A"])
    repo.git.commit(["-m", "Add references"])
    project_spec = f"{project.owner_account_name}/{project.name}"

    def _search(params: dict):
        with patch("app.api.routes.references.get_repo", return_value=repo):
            return client.get(
                "/references",
                params={"project": [project_spec], **params},
                headers=headers,
            )

    # A DOI matches regardless of case or a doi.org prefix
    resp = _search({"doi": "https://doi.org/10.1234/abcd"})
    assert resp.status_code == 200
    matches = resp.json()
    assert len(matches) == 1
    assert matches[0]["key"] == "smith2020"
    assert matches[0]["path"] == "refs.bib"
    assert matches[0]["matched_on"] == "doi"
    assert matches[0]["note_count"] == 1
    assert matches[0]["project_name"] == project.name
    # An arXiv ID matches with the version suffix stripped
    resp = _search({"arxiv_id": "arXiv:2301.01234"})
    assert resp.status_code == 200
    matches = resp.json()
    assert len(matches) == 1
    assert matches[0]["key"] == "jones2021"
    assert matches[0]["matched_on"] == "arxiv_id"
    assert matches[0]["note_count"] == 0
    # Titles match ignoring case and punctuation
    resp = _search({"title": "a study of things!"})
    assert resp.status_code == 200
    assert [m["key"] for m in resp.json()] == ["smith2020"]
    # A reference that isn't there comes back empty rather than erroring
    resp = _search({"doi": "10.9999/nope"})
    assert resp.status_code == 200
    assert resp.json() == []
    # With no filter, everything in the collection comes back, and nothing
    # in particular was matched against
    resp = _search({})
    assert resp.status_code == 200
    assert sorted(m["key"] for m in resp.json()) == ["jones2021", "smith2020"]
    assert {m["matched_on"] for m in resp.json()} == {None}
    # Naming no project searches the ones the user can write to, which is
    # what makes this "my references" rather than "this project's"
    with patch("app.api.routes.references.get_repo", return_value=repo):
        resp = client.get(
            "/references",
            params={"doi": "10.1234/abcd"},
            headers=headers,
        )
    assert resp.status_code == 200
    assert [m["key"] for m in resp.json()] == ["smith2020"]
    # A project the user can't read is skipped, not an error
    resp = client.get(
        "/references",
        params={
            "project": ["someone-else/private-project"],
            "doi": "10.1234/abcd",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []
