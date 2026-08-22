import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import git
import yaml
from fastapi.testclient import TestClient

from app.config import settings

URL = f"{settings.API_V1_STR}/projects/o/p/datasets"


def _repo(tmp_path):
    origin = git.Repo.init(tmp_path / "origin.git", bare=True)
    repo = git.Repo.init(tmp_path / "repo")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    (tmp_path / "repo" / "calkit.yaml").write_text("name: p\n")
    repo.git.add(all=True)
    repo.git.commit("-m", "Initial")
    repo.create_remote("origin", str(origin.working_dir))
    repo.git.push("origin", repo.active_branch.name)
    return repo, origin


def _streaming(body: bytes, headers: dict | None = None):
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    resp.raise_for_status.return_value = None
    resp.headers = headers or {}
    resp.iter_content.return_value = [body]
    return resp


def test_post_project_dataset_fetches_imports(
    client: TestClient, normal_user_token_headers: dict[str, str], tmp_path
) -> None:
    repo, origin = _repo(tmp_path)
    fake_project = SimpleNamespace(
        owner_account_name="o", name="p", id=uuid.uuid4()
    )
    # A source repo to import from at a pinned commit
    src = git.Repo.init(tmp_path / "src")
    with src.config_writer() as cw:
        cw.set_value("user", "name", "Src")
        cw.set_value("user", "email", "src@example.com")
    (tmp_path / "src" / "data").mkdir()
    (tmp_path / "src" / "data" / "wind.csv").write_text("u,v\n1,2\n")
    src.git.add(all=True)
    src.git.commit("-m", "Data")
    rev = src.head.commit.hexsha
    with (
        patch(
            "app.api.routes.projects.core.app.projects.get_project",
            return_value=fake_project,
        ),
        patch("app.api.routes.projects.core.get_repo", return_value=repo),
        patch("app.api.routes.projects.core.mixpanel.user_added_dataset"),
        patch(
            "app.imports.requests.get",
            return_value=_streaming(b"x,y\n1,2\n3,4\n"),
        ) as http_get,
        patch(
            "app.imports.calkit.invenio.get_download_urls",
            return_value={
                "record.csv": "https://zenodo.org/api/files/1/record.csv"
            },
        ),
    ):
        # A URL lands at the named file path
        resp = client.post(
            URL,
            json={
                "path": "data/from-url.csv",
                "imported_from": {"url": "https://example.org/dl/file.csv"},
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert (tmp_path / "repo" / "data" / "from-url.csv").read_text() == (
            "x,y\n1,2\n3,4\n"
        )
        assert http_get.call_args.args[0] == "https://example.org/dl/file.csv"
        # A Zenodo DOI's files land under a folder path
        resp = client.post(
            URL,
            json={
                "path": "data/zenodo",
                "imported_from": {"doi": "10.5281/zenodo.1234567"},
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert (tmp_path / "repo" / "data" / "zenodo" / "record.csv").exists()
        # A doi.org link pasted into the URL box is a DOI, recorded as one
        # and fetched through the archive's API
        resp = client.post(
            URL,
            json={
                "path": "data/zenodo-via-url",
                "imported_from": {
                    "url": "https://doi.org/10.5281/zenodo.1234567"
                },
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert (
            tmp_path / "repo" / "data" / "zenodo-via-url" / "record.csv"
        ).exists()
        # A record with several files is a folder even if a file name was
        # given: the suffix is dropped and the entry records the folder
        with patch(
            "app.imports.calkit.invenio.get_download_urls",
            return_value={
                "a.csv": "https://zenodo.org/api/files/2/a.csv",
                "b.csv": "https://zenodo.org/api/files/2/b.csv",
            },
        ):
            resp = client.post(
                URL,
                json={
                    "path": "data/multi.csv",
                    "imported_from": {"doi": "10.5281/zenodo.2222"},
                },
                headers=normal_user_token_headers,
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["path"] == "data/multi"
        assert (tmp_path / "repo" / "data" / "multi" / "a.csv").exists()
        assert (tmp_path / "repo" / "data" / "multi" / "b.csv").exists()
        assert not (tmp_path / "repo" / "data" / "multi.csv").exists()
        # A Git repo path at a commit is copied over
        resp = client.post(
            URL,
            json={
                "path": "data/wind.csv",
                "imported_from": {
                    "git": {
                        "repo_url": str(tmp_path / "src"),
                        "rev": rev,
                        "path": "data/wind.csv",
                    }
                },
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert (tmp_path / "repo" / "data" / "wind.csv").read_text() == (
            "u,v\n1,2\n"
        )
        # Without a revision, the default branch's head is fetched and its
        # commit is what gets recorded
        resp = client.post(
            URL,
            json={
                "path": "data/wind-head.csv",
                "imported_from": {
                    "git": {
                        "repo_url": str(tmp_path / "src"),
                        "path": "data/wind.csv",
                    }
                },
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert (tmp_path / "repo" / "data" / "wind-head.csv").read_text() == (
            "u,v\n1,2\n"
        )
        # Everything small went into Git, each with its declaration, and
        # was pushed
        assert not repo.is_dirty(untracked_files=True)
        assert origin.head.commit.hexsha == repo.head.commit.hexsha
        tracked = repo.git.ls_files().split("\n")
        assert "data/from-url.csv" in tracked
        assert "data/zenodo/record.csv" in tracked
        assert "data/wind.csv" in tracked
        assert "data/multi/a.csv" in tracked
        ck = yaml.safe_load((tmp_path / "repo" / "calkit.yaml").read_text())
        by_path = {d["path"]: d for d in ck["datasets"]}
        assert by_path["data/zenodo"]["imported_from"] == {
            "doi": "10.5281/zenodo.1234567"
        }
        assert by_path["data/zenodo-via-url"]["imported_from"] == {
            "doi": "10.5281/zenodo.1234567"
        }
        assert by_path["data/wind.csv"]["imported_from"]["git"]["rev"] == rev
        assert (
            by_path["data/wind-head.csv"]["imported_from"]["git"]["rev"] == rev
        )
        assert "data/multi" in by_path and "data/multi.csv" not in by_path
        # Importing from another Calkit project copies Git-tracked files
        # and pins the source revision. (get_project/get_repo are patched to
        # the same project here, which exercises the Git-tracked branch.)
        resp = client.post(
            URL,
            json={
                "path": "data/wind-copy.csv",
                "imported_from": {"project": "o/p", "path": "data/wind.csv"},
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert (tmp_path / "repo" / "data" / "wind-copy.csv").read_text() == (
            "u,v\n1,2\n"
        )
        ck = yaml.safe_load((tmp_path / "repo" / "calkit.yaml").read_text())
        copied = next(
            d for d in ck["datasets"] if d["path"] == "data/wind-copy.csv"
        )
        assert copied["imported_from"]["project"] == "o/p"
        assert copied["imported_from"]["path"] == "data/wind.csv"
        assert len(copied["imported_from"]["git_rev"]) == 40
        # A path that's already there is refused rather than overwritten
        resp = client.post(
            URL,
            json={
                "path": "data/wind.csv",
                "imported_from": {"url": "https://example.org/other.csv"},
            },
            headers=normal_user_token_headers,
        )
        assert resp.status_code == 400, resp.text
        # A DOI nobody can resolve to files is a clear 400, not a bare entry
        with patch(
            "app.imports.requests.head",
            return_value=SimpleNamespace(
                ok=True,
                headers={"content-type": "text/html"},
                url="https://publisher.example/landing",
            ),
        ):
            resp = client.post(
                URL,
                json={
                    "path": "data/mystery",
                    "imported_from": {"doi": "10.1234/abc"},
                },
                headers=normal_user_token_headers,
            )
        assert resp.status_code == 400, resp.text
        assert "URL option" in resp.json()["detail"]
        assert not (tmp_path / "repo" / "data" / "mystery").exists()
