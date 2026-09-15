import base64
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import git
import polars as pl
import yaml
from fastapi.testclient import TestClient

BASE = "/projects/o/p/dataset-csv"


def _csv(resp) -> str:
    return base64.b64decode(resp.json()["content"]).decode()


def test_get_project_dataset_csv(client: TestClient, tmp_path) -> None:
    repo = git.Repo.init(tmp_path / "repo")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    d = tmp_path / "repo" / "data"
    d.mkdir()
    (d / "raw.csv").write_text(
        "x,y,label\n" + "".join(f"{i},{i * i},row{i}\n" for i in range(250))
    )
    (d / "raw.tsv").write_text("a\tb\n1\thello world\n2\tbye\n")
    pl.DataFrame(
        {"u": [1.5, 2.5, None], "name": ["a", "b", "c"]}
    ).write_parquet(d / "wind.parquet")
    (d / "notes.txt").write_text("not a table\n")
    repo.git.add(all=True)
    repo.git.commit("-m", "Data")
    fake_project = SimpleNamespace(owner_account_name="o", name="p")
    with (
        patch(
            "app.api.routes.projects.datasets.app.projects.get_project",
            return_value=fake_project,
        ),
        patch("app.api.routes.projects.datasets.get_repo", return_value=repo),
        patch(
            "app.api.routes.projects.datasets.app.projects.dvc_outputs_from_tree",
            return_value={},
        ),
    ):
        # A CSV comes back as CSV, with its shape described
        resp = client.get(f"{BASE}/data/raw.csv")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["columns"] == ["x", "y", "label"]
        assert body["n_rows"] == 250
        assert body["truncated"] is False
        lines = _csv(resp).splitlines()
        assert lines[0] == "x,y,label"
        assert lines[4] == "3,9,row3"
        assert len(lines) == 251
        # TSV and parquet are converted; nulls become empty cells
        assert _csv(client.get(f"{BASE}/data/raw.tsv")).splitlines() == [
            "a,b",
            "1,hello world",
            "2,bye",
        ]
        resp = client.get(f"{BASE}/data/wind.parquet")
        assert resp.status_code == 200, resp.text
        assert _csv(resp).splitlines() == ["u,name", "1.5,a", "2.5,b", ",c"]
        # Not a table format, and not a file
        assert client.get(f"{BASE}/data/notes.txt").status_code == 415
        assert client.get(f"{BASE}/data/missing.csv").status_code == 404
        # Windows in both dimensions, with the whole's size reported
        resp = client.get(
            f"{BASE}/data/raw.csv",
            params={"row_offset": 240, "row_limit": 10, "col_limit": 2},
        )
        body = resp.json()
        assert body["truncated"] is True
        assert body["n_rows"] == 250 and body["n_cols"] == 3
        assert body["columns"] == ["x", "y"]
        assert _csv(resp).splitlines() == ["x,y"] + [
            f"{i},{i * i}" for i in range(240, 250)
        ]
        resp = client.get(
            f"{BASE}/data/raw.csv", params={"col_offset": 2, "row_limit": 1}
        )
        assert _csv(resp).splitlines() == ["label", "row0"]
        assert (
            client.get(
                f"{BASE}/data/raw.csv", params={"row_limit": 99999}
            ).status_code
            == 422
        )


def test_get_project_dataset_hdf5(client: TestClient, tmp_path) -> None:
    import h5py
    import numpy as np

    repo = git.Repo.init(tmp_path / "repo")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    d = tmp_path / "repo" / "data"
    d.mkdir()
    with h5py.File(d / "profiles.h5", "w") as f:
        g = f.create_group("mean")
        g.create_dataset("u", data=np.array([1.0, 2.0, 3.0]))
        g.create_dataset("uv", data=np.arange(6.0).reshape(3, 2))
        f.create_dataset("cube", data=np.zeros((2, 2, 2)))
        f.create_dataset(
            "table",
            data=np.array(
                [(1, b"a"), (2, b"b")], dtype=[("n", "i4"), ("s", "S1")]
            ),
        )
    repo.git.add(all=True)
    repo.git.commit("-m", "Data")
    fake_project = SimpleNamespace(owner_account_name="o", name="p")
    base = "/projects/o/p/dataset-hdf5"
    with (
        patch(
            "app.api.routes.projects.datasets.app.projects.get_project",
            return_value=fake_project,
        ),
        patch("app.api.routes.projects.datasets.get_repo", return_value=repo),
        patch(
            "app.api.routes.projects.datasets.app.projects.dvc_outputs_from_tree",
            return_value={},
        ),
    ):
        resp = client.get(f"{base}/data/profiles.h5")
        assert resp.status_code == 200, resp.text
        keys = {k["key"]: k for k in resp.json()["keys"]}
        assert keys["mean"]["kind"] == "group"
        assert keys["mean/u"] == {
            "key": "mean/u",
            "kind": "dataset",
            "shape": [3],
            "dtype": "float64",
            "tabular": True,
        }
        assert keys["mean/uv"]["shape"] == [3, 2]
        # 3D isn't something a table can show
        assert keys["cube"]["tabular"] is False
        assert keys["table"]["tabular"] is True
        # One dataset as CSV: 1D, 2D, and compound
        assert _csv(
            client.get(f"{base}/data/profiles.h5", params={"key": "mean/u"})
        ).splitlines() == [
            "u",
            "1.0",
            "2.0",
            "3.0",
        ]
        assert _csv(
            client.get(f"{base}/data/profiles.h5", params={"key": "mean/uv"})
        ).splitlines()[:2] == [
            "col0,col1",
            "0.0,1.0",
        ]
        assert _csv(
            client.get(f"{base}/data/profiles.h5", params={"key": "table"})
        ).splitlines() == [
            "n,s",
            "1,a",
            "2,b",
        ]
        assert (
            client.get(
                f"{base}/data/profiles.h5", params={"key": "cube"}
            ).status_code
            == 415
        )
        assert (
            client.get(
                f"{base}/data/profiles.h5", params={"key": "nope"}
            ).status_code
            == 404
        )


def test_imported_dataset_reads_from_source_project(
    client: TestClient, tmp_path
) -> None:
    """A pointer with a calkit: remote is read from that project's storage."""
    import io

    repo = git.Repo.init(tmp_path / "repo")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    d = tmp_path / "repo" / "data"
    d.mkdir()
    (d / "imported.csv.dvc").write_text(
        "outs:\n- md5: abc123\n  size: 12\n  hash: md5\n"
        "  path: imported.csv\n  remote: calkit:src/proj\n  push: false\n"
    )
    repo.git.add(all=True)
    repo.git.commit("-m", "Pointer")
    fake_project = SimpleNamespace(owner_account_name="o", name="p")
    looked_up: list[tuple[str, str]] = []

    def fake_fpath(owner_name, project_name, md5, fs):
        looked_up.append((owner_name, project_name))
        return "src/proj/ab/c123" if owner_name == "src" else None

    class FakeFS:
        def open(self, path, mode="rb"):
            assert path == "src/proj/ab/c123"
            return io.BytesIO(b"a,b\n1,2\n")

    seen_projects: list[str] = []

    def fake_get_project(**kwargs):
        seen_projects.append(
            f"{kwargs['owner_name']}/{kwargs['project_name']}"
        )
        return fake_project

    with (
        patch(
            "app.api.routes.projects.datasets.app.projects.get_project",
            side_effect=fake_get_project,
        ),
        patch("app.api.routes.projects.datasets.get_repo", return_value=repo),
        patch("app.dvc.get_data_fpath_for_md5", side_effect=fake_fpath),
        patch("app.projects.get_object_fs", return_value=FakeFS()),
    ):
        resp = client.get(f"{BASE}/data/imported.csv")
    assert resp.status_code == 200, resp.text
    assert _csv(resp).splitlines() == ["a,b", "1,2"]
    # Looked up in the source project's storage, after an access check on it
    assert looked_up == [("src", "proj")]
    assert seen_projects == ["o/p", "src/proj"]


URL = "/projects/o/p/datasets"


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
                    "git_repo_url": str(tmp_path / "src"),
                    "git_ref": rev,
                    "path": "data/wind.csv",
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
                    "git_repo_url": str(tmp_path / "src"),
                    "path": "data/wind.csv",
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
        assert by_path["data/wind.csv"]["imported_from"]["git_rev"] == rev
        assert by_path["data/wind-head.csv"]["imported_from"]["git_rev"] == rev
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
