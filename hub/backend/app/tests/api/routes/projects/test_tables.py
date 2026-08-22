import base64
from types import SimpleNamespace
from unittest.mock import patch

import git
import polars as pl
from fastapi.testclient import TestClient

from app.config import settings

BASE = f"{settings.API_V1_STR}/projects/o/p/dataset-csv"


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
            "app.api.routes.projects.tables.app.projects.get_project",
            return_value=fake_project,
        ),
        patch("app.api.routes.projects.tables.get_repo", return_value=repo),
        patch(
            "app.api.routes.projects.tables.app.projects.dvc_outputs_from_tree",
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
    base = f"{settings.API_V1_STR}/projects/o/p/dataset-hdf5"
    with (
        patch(
            "app.api.routes.projects.tables.app.projects.get_project",
            return_value=fake_project,
        ),
        patch("app.api.routes.projects.tables.get_repo", return_value=repo),
        patch(
            "app.api.routes.projects.tables.app.projects.dvc_outputs_from_tree",
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
            "app.api.routes.projects.tables.app.projects.get_project",
            side_effect=fake_get_project,
        ),
        patch("app.api.routes.projects.tables.get_repo", return_value=repo),
        patch(
            "app.api.routes.projects.tables.get_data_fpath_for_md5",
            side_effect=fake_fpath,
        ),
        patch(
            "app.api.routes.projects.tables.get_object_fs",
            return_value=FakeFS(),
        ),
    ):
        resp = client.get(f"{BASE}/data/imported.csv")
    assert resp.status_code == 200, resp.text
    assert _csv(resp).splitlines() == ["a,b", "1,2"]
    # Looked up in the source project's storage, after an access check on it
    assert looked_up == [("src", "proj")]
    assert seen_projects == ["o/p", "src/proj"]
