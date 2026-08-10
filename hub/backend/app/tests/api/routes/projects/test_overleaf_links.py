"""Tests for Overleaf link indexing, lookup, and reference search."""

import io
import json
import os
import uuid
from types import SimpleNamespace
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


def ryaml_dumps(data: dict) -> str:
    buffer = io.StringIO()
    ryaml.dump(data, buffer)
    return buffer.getvalue()


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
    # The owner can resolve the Overleaf project back to their project,
    # straight from the index
    resp = client.get(
        f"{settings.API_V1_STR}/user/overleaf-syncs/ol333",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()["links"]
    assert len(data) == 1
    assert data[0]["project_name"] == project.name
    assert data[0]["path"] == "paper"
    assert data[0]["current_user_access"] == "owner"
    # An unrelated user gets nothing back for the same private project
    resp = client.get(
        f"{settings.API_V1_STR}/user/overleaf-syncs/ol333",
        headers=other_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["links"] == []


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
        with patch("app.api.routes.references.get_repo", return_value=repo):
            return client.get(
                f"{settings.API_V1_STR}/references",
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
            f"{settings.API_V1_STR}/references",
            params={"doi": "10.1234/abcd"},
            headers=headers,
        )
    assert resp.status_code == 200
    assert [m["key"] for m in resp.json()] == ["smith2020"]
    # A project the user can't read is skipped, not an error
    resp = client.get(
        f"{settings.API_V1_STR}/references",
        params={
            "project": ["someone-else/private-project"],
            "doi": "10.1234/abcd",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_post_reference_item_creates_missing_collection(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    repo_dir = tmp_path / uuid.uuid4().hex[:8]
    os.makedirs(repo_dir)
    repo = git.Repo.init(path=repo_dir)
    _set_identity(repo)
    with open(repo_dir / "calkit.yaml", "w") as f:
        ryaml.dump({}, f)
    repo.git.add(["-A"])
    repo.git.commit(["-m", "Initial commit"])
    remote_dir = tmp_path / f"{uuid.uuid4().hex[:8]}-remote"
    git.Repo.init(path=remote_dir, bare=True)
    repo.git.remote(["add", "origin", str(remote_dir)])
    repo.git.push(["-u", "origin", repo.active_branch.name])
    url = (
        f"{settings.API_V1_STR}/projects/{project.owner_account_name}/"
        f"{project.name}/references/items"
    )
    with patch("app.api.routes.projects.core.get_repo", return_value=repo):
        resp = client.post(
            url,
            json={
                "path": "references.bib",
                "key": "thomas2026",
                "type": "article",
                "fields": {"title": "Reversing biodiversity decline"},
            },
            headers=headers,
        )
    assert resp.status_code == 200
    # The first reference in a project creates the collection rather than
    # failing because the .bib doesn't exist yet
    bib_path = repo_dir / "references.bib"
    assert bib_path.is_file()
    assert "thomas2026" in bib_path.read_text()
    ck_info = ryaml.load((repo_dir / "calkit.yaml").read_text())
    assert ck_info["references"] == [{"path": "references.bib"}]
    # A second reference lands in the collection that now exists, and
    # doesn't re-declare it
    with patch("app.api.routes.projects.core.get_repo", return_value=repo):
        resp = client.post(
            url,
            json={
                "path": "references.bib",
                "key": "smith2025",
                "type": "article",
                "fields": {"title": "Another paper"},
            },
            headers=headers,
        )
    assert resp.status_code == 200
    assert "smith2025" in bib_path.read_text()
    ck_info = ryaml.load((repo_dir / "calkit.yaml").read_text())
    assert ck_info["references"] == [{"path": "references.bib"}]


def test_get_user_overleaf_sync_scans_lazily(
    client: TestClient, db: Session, tmp_path
) -> None:
    project, headers = _make_owner_with_project(db, client)
    url = f"{settings.API_V1_STR}/user/overleaf-syncs/54b68eff0ee71ad2767b704a"
    ck_info = {
        "overleaf_sync": {
            "paper2": {
                "url": "https://www.overleaf.com/project/54b68eff0ee71ad2767b704a"
            },
            "report": {
                "url": "https://www.overleaf.com/project/699f2a0fb20a38960a52bc26"
            },
        }
    }

    def _lookup(**params):
        # The scan reads calkit.yaml from GitHub rather than cloning, so a
        # stubbed response stands in for the repo
        with (
            patch(
                "app.projects.requests.get",
                return_value=SimpleNamespace(
                    status_code=200, text=ryaml_dumps(ck_info)
                ),
            ),
            patch(
                "app.projects.app.users.get_github_token",
                return_value="gh-token",
            ),
        ):
            return client.get(url, params=params, headers=headers)

    # Nothing is indexed yet, so the lookup finds it by reading the project
    resp = _lookup()
    assert resp.status_code == 200
    data = resp.json()
    assert data["projects_scanned"] == 1
    assert [link["path"] for link in data["links"]] == ["paper2"]
    assert data["links"][0]["project_name"] == project.name
    # Both syncs declared in one calkit.yaml are indexed together, so the
    # second Overleaf project resolves without reading anything again
    resp = client.get(
        f"{settings.API_V1_STR}/user/overleaf-syncs/699f2a0fb20a38960a52bc26",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["projects_scanned"] == 0
    assert [link["path"] for link in data["links"]] == ["report"]
    # A second lookup is answered from the index, without scanning again
    resp = _lookup()
    assert resp.status_code == 200
    assert resp.json()["projects_scanned"] == 0
    # A project already scanned isn't re-read until the TTL lapses, so an
    # Overleaf project nobody syncs with doesn't cost a scan per lookup
    resp = client.get(
        f"{settings.API_V1_STR}/user/overleaf-syncs/nonexistent",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "links": [],
        "projects_scanned": 0,
        "projects_remaining": 0,
    }
    # refresh re-reads regardless, for a link that was only just added
    resp = _lookup(refresh=True)
    assert resp.status_code == 200
    assert resp.json()["projects_scanned"] == 1
