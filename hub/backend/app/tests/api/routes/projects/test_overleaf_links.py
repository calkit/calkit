"""Tests for Overleaf link indexing, lookup, and reference search."""

import json
import os
import uuid
from unittest.mock import patch

import git
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import projects as projects_module
from app import users
from app.config import settings
from app.core import ryaml
from app.models import OverleafLink, Project, UserCreate
from app.models.core import ROLE_IDS, UserProjectAccess
from app.tests import authentication_token_from_email


def _make_owner_with_project(
    db: Session, client: TestClient
) -> tuple[Project, dict[str, str]]:
    suffix = uuid.uuid4().hex[:8]
    owner = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"owner-{suffix}@example.com",
            password="ownerpassword123",
            account_name=f"owner{suffix}",
            github_username=f"owner{suffix}",
        ),
    )
    project = Project(
        name=f"proj-{suffix}",
        title="Overleaf Link Test Project",
        git_repo_url=f"https://github.com/owner{suffix}/proj-{suffix}",
        owner_account_id=owner.account.id,
        owner_account=owner.account,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    headers = authentication_token_from_email(
        client=client, email=owner.email, db=db
    )
    return project, headers


def _set_identity(repo: git.Repo) -> None:
    """Give the repo a committer, which the test container lacks."""
    repo.git.config(["user.email", "test@example.com"])
    repo.git.config(["user.name", "Calkit Test"])


def _make_repo(tmp_path, ck_info: dict, sync_info: dict | None = None):
    """Build a Git repo standing in for a project's clone."""
    repo_dir = tmp_path / uuid.uuid4().hex[:8]
    os.makedirs(repo_dir)
    repo = git.Repo.init(path=repo_dir)
    _set_identity(repo)
    with open(repo_dir / "calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    if sync_info is not None:
        os.makedirs(repo_dir / ".calkit", exist_ok=True)
        with open(repo_dir / ".calkit" / "overleaf-sync.json", "w") as f:
            json.dump(sync_info, f)
    repo.git.add(["-A"])
    repo.git.commit(["-m", "Initial commit"])
    return repo


def test_record_overleaf_links_and_lookup(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    _, other_headers = _make_owner_with_project(db, client)
    repo = _make_repo(
        tmp_path,
        ck_info={
            "overleaf_sync": {
                "paper": {"url": "https://www.overleaf.com/project/ol111"},
                "poster": {"url": "https://www.overleaf.com/project/ol222"},
            }
        },
    )
    links = projects_module.record_overleaf_links(
        session=db, project=project, repo=repo
    )
    assert {link.path for link in links} == {"paper", "poster"}
    assert {link.overleaf_project_id for link in links} == {"ol111", "ol222"}
    # Re-recording is idempotent, and a link removed from calkit.yaml is
    # dropped from the index rather than lingering
    repo2 = _make_repo(
        tmp_path,
        ck_info={
            "overleaf_sync": {
                "paper": {"url": "https://www.overleaf.com/project/ol333"}
            }
        },
    )
    links = projects_module.record_overleaf_links(
        session=db, project=project, repo=repo2
    )
    assert len(links) == 1
    assert links[0].path == "paper"
    assert links[0].overleaf_project_id == "ol333"
    stored = db.exec(
        select(OverleafLink).where(OverleafLink.project_id == project.id)
    ).all()
    assert len(stored) == 1
    # The owner can resolve the Overleaf project back to their project
    resp = client.get(
        f"{settings.API_V1_STR}/overleaf-links",
        params={"overleaf_project_id": "ol333"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["project_name"] == project.name
    assert data[0]["path"] == "paper"
    assert data[0]["current_user_access"] == "owner"
    # An unrelated user gets nothing back for the same private project
    resp = client.get(
        f"{settings.API_V1_STR}/overleaf-links",
        params={"overleaf_project_id": "ol333"},
        headers=other_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []
    # An Overleaf project nobody has linked resolves to nothing
    resp = client.get(
        f"{settings.API_V1_STR}/overleaf-links",
        params={"overleaf_project_id": "nonexistent"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_projects_min_access_level_write(
    client: TestClient, db: Session
) -> None:
    # A project the user owns, plus one owned by somebody else that they can
    # only read
    owned, headers = _make_owner_with_project(db, client)
    others, _ = _make_owner_with_project(db, client)
    others.is_public = True
    db.add(others)
    db.commit()
    suffix = uuid.uuid4().hex[:8]
    reader = users.create_user(
        session=db,
        user_create=UserCreate(
            email=f"reader-{suffix}@example.com",
            password="readerpassword123",
            account_name=f"reader{suffix}",
            github_username=f"reader{suffix}",
        ),
    )
    reader_headers = authentication_token_from_email(
        client=client, email=reader.email, db=db
    )

    def _list(headers: dict[str, str], **params):
        resp = client.get(
            f"{settings.API_V1_STR}/projects", params=params, headers=headers
        )
        assert resp.status_code == 200
        return {
            f"{p['owner_account_name']}/{p['name']}"
            for p in resp.json()["data"]
        }

    owned_spec = f"{owned.owner_account_name}/{owned.name}"
    others_spec = f"{others.owner_account_name}/{others.name}"
    # Reading lists the public project belonging to someone else; asking for
    # write access drops it, since a reader can't write to it
    assert others_spec in _list(reader_headers)
    assert others_spec not in _list(reader_headers, min_access_level="write")
    # An owner keeps their own project under either level
    assert owned_spec in _list(headers)
    assert owned_spec in _list(headers, min_access_level="write")
    # A read-level grant isn't enough, but a write-level one is
    db.add(
        UserProjectAccess(
            project_id=others.id, user_id=reader.id, role_id=ROLE_IDS["read"]
        )
    )
    db.commit()
    assert others_spec not in _list(reader_headers, min_access_level="write")
    access = db.exec(
        select(UserProjectAccess)
        .where(UserProjectAccess.project_id == others.id)
        .where(UserProjectAccess.user_id == reader.id)
    ).one()
    access.role_id = ROLE_IDS["write"]
    db.add(access)
    db.commit()
    assert others_spec in _list(reader_headers, min_access_level="write")
    # GitHub-derived access counts too, but only at write or better
    access.role_id = None
    access.github_access = "read"
    db.add(access)
    db.commit()
    assert others_spec not in _list(reader_headers, min_access_level="write")
    access.github_access = "admin"
    db.add(access)
    db.commit()
    assert others_spec in _list(reader_headers, min_access_level="write")
    # Anonymous callers can't ask for write access at all
    resp = client.get(
        f"{settings.API_V1_STR}/projects", params={"min_access_level": "write"}
    )
    assert resp.status_code == 403


def test_get_projects_filters_by_github_repo(
    client: TestClient, db: Session
) -> None:
    project, headers = _make_owner_with_project(db, client)
    github_repo = project.git_repo_url.removeprefix("https://github.com/")
    resp = client.get(
        f"{settings.API_V1_STR}/projects",
        params={"github_repo": github_repo},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["data"][0]["name"] == project.name
    # Matching is exact, so a repo whose name merely starts the same doesn't
    # come back
    resp = client.get(
        f"{settings.API_V1_STR}/projects",
        params={"github_repo": f"{github_repo}-other"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_get_user_reference_matches(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    repo_dir = tmp_path / uuid.uuid4().hex[:8]
    os.makedirs(repo_dir)
    repo = git.Repo.init(path=repo_dir)
    _set_identity(repo)
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
        with patch("app.api.routes.projects.core.get_repo", return_value=repo):
            return client.get(
                f"{settings.API_V1_STR}/user/references/search",
                params={"projects": [project_spec], **params},
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
    # Searching needs something to search for, and something to search in
    resp = _search({})
    assert resp.status_code == 422
    resp = client.get(
        f"{settings.API_V1_STR}/user/references/search",
        params={"doi": "10.1234/abcd"},
        headers=headers,
    )
    assert resp.status_code == 422
    # A project the user can't read is skipped, not an error
    resp = client.get(
        f"{settings.API_V1_STR}/user/references/search",
        params={
            "projects": ["someone-else/private-project"],
            "doi": "10.1234/abcd",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []
