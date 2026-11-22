"""Tests for app.api.routes.projects.fs endpoints."""

import base64
import threading
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

from fastapi.testclient import TestClient

OWNER = "testowner"
PROJECT = "testproject"
FS_OPS_URL = f"/projects/{OWNER}/{PROJECT}/fs/ops"


def _fake_project() -> SimpleNamespace:
    return SimpleNamespace(
        name=PROJECT,
        owner_account_name=OWNER,
        dvc_storage=None,
        dvc_storage_id=None,
        storage_history=[],
    )


def test_lowercases_owner_and_project_name(client: TestClient):
    mixed_owner = "TestOwner"
    mixed_project = "TestProject"
    url = f"/projects/{mixed_owner}/{mixed_project}/fs/ops"
    fake_fs = MagicMock()
    fake_fs.exists.return_value = True
    fake_fs.ls.side_effect = FileNotFoundError
    with (
        patch(
            "app.api.routes.projects.fs.app.projects.get_project",
            return_value=_fake_project(),
        ) as mock_get_project,
        patch(
            "app.api.routes.projects.fs.storage.get_backend",
            return_value="s3",
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_object_fs",
            return_value=fake_fs,
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_data_prefix",
            return_value="s3://data",
        ),
    ):
        response = client.post(
            url,
            json={"operation": "exists", "path": "some/file.csv"},
        )
    assert response.status_code == 200
    mock_get_project.assert_called_once_with(
        owner_name="testowner",
        project_name="testproject",
        session=ANY,
        current_user=ANY,
        min_access_level="read",
    )


def test_lowercases_owner_only_capital(client: TestClient):
    url = f"/projects/OwnerWithCaps/{PROJECT}/fs/ops"
    fake_fs = MagicMock()
    fake_fs.exists.return_value = True
    fake_fs.ls.side_effect = FileNotFoundError
    with (
        patch(
            "app.api.routes.projects.fs.app.projects.get_project",
            return_value=_fake_project(),
        ) as mock_get_project,
        patch(
            "app.api.routes.projects.fs.storage.get_backend",
            return_value="s3",
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_object_fs",
            return_value=fake_fs,
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_data_prefix",
            return_value="s3://data",
        ),
    ):
        response = client.post(
            url,
            json={"operation": "exists", "path": "data.csv"},
        )
    assert response.status_code == 200
    mock_get_project.assert_called_once_with(
        owner_name="ownerwithcaps",
        project_name=PROJECT,
        session=ANY,
        current_user=ANY,
        min_access_level="read",
    )


def test_rejects_absolute_path(client: TestClient):
    with (
        patch(
            "app.api.routes.projects.fs.app.projects.get_project",
            return_value=_fake_project(),
        ),
    ):
        response = client.post(
            FS_OPS_URL,
            json={"operation": "get", "path": "/etc/passwd"},
        )
    assert response.status_code == 400


def test_rejects_path_traversal(client: TestClient):
    with (
        patch(
            "app.api.routes.projects.fs.app.projects.get_project",
            return_value=_fake_project(),
        ),
    ):
        response = client.post(
            FS_OPS_URL,
            json={"operation": "get", "path": "../../etc/shadow"},
        )
    assert response.status_code == 400


def test_rejects_negative_content_length(client: TestClient):
    with (
        patch(
            "app.api.routes.projects.fs.app.projects.get_project",
            return_value=_fake_project(),
        ),
    ):
        response = client.post(
            FS_OPS_URL,
            json={
                "operation": "put",
                "path": "data.csv",
                "content_length": -1,
            },
        )
    assert response.status_code == 422


def test_exists_operation_returns_false_for_missing_path(client: TestClient):
    fake_fs = MagicMock()
    fake_fs.exists.return_value = True
    fake_fs.ls.side_effect = FileNotFoundError
    with (
        patch(
            "app.api.routes.projects.fs.app.projects.get_project",
            return_value=_fake_project(),
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_backend",
            return_value="s3",
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_object_fs",
            return_value=fake_fs,
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_data_prefix",
            return_value="s3://data",
        ),
    ):
        response = client.post(
            FS_OPS_URL,
            json={"operation": "exists", "path": "missing.csv"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["exists"] is False


def test_list_returns_empty_for_missing_prefix(client: TestClient):
    fake_fs = MagicMock()
    fake_fs.exists.return_value = True
    fake_fs.ls.side_effect = FileNotFoundError
    with (
        patch(
            "app.api.routes.projects.fs.app.projects.get_project",
            return_value=_fake_project(),
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_backend",
            return_value="s3",
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_object_fs",
            return_value=fake_fs,
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_data_prefix",
            return_value="s3://data",
        ),
    ):
        response = client.post(
            FS_OPS_URL,
            json={"operation": "list", "path": ""},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["paths"] == []


def test_hf_storage_with_fallback(client: TestClient) -> None:
    from typing import Any

    from fsspec.implementations.memory import (  # type: ignore[import-untyped]
        MemoryFileSystem,
    )

    from app.storage import HfBucketBatchError, ProjectStorage

    class FakeHfFileSystem(MemoryFileSystem):  # type: ignore[misc]
        def info(self, path: str, **kwargs: Any) -> dict[str, Any]:
            info: dict[str, Any] = super().info(path, **kwargs)
            if info["type"] != "file":
                return info
            return info | {"xet_hash": "a" * 64}

    hf = ProjectStorage(
        backend="hf",
        fs=FakeHfFileSystem(),
        data_prefix="/buckets/ns/bkt",
        resource=SimpleNamespace(  # type: ignore[arg-type]
            bucket="ns/bkt", project_id=None
        ),
        token="hf-owner-token",
    )
    internal = ProjectStorage(
        backend="s3", fs=MemoryFileSystem(), data_prefix="/internal/data"
    )
    old_path = "files/md5/aa/old"
    new_path = "files/md5/bb/new"
    internal.fs.pipe(
        internal.make_project_path(OWNER, PROJECT, old_path), b"o"
    )
    hf.fs.pipe(hf.make_project_path(OWNER, PROJECT, new_path), b"new!")
    token = {"casUrl": "https://cas", "accessToken": "xet", "exp": 123}
    with (
        patch(
            "app.api.routes.projects.fs.app.projects.get_project",
            return_value=_fake_project(),
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_project_storages",
            return_value=[hf, internal],
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_project_storage",
            return_value=hf,
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_xet_token",
            return_value=token,
        ) as get_xet_token,
        patch(
            "app.api.routes.projects.fs.storage.post_hf_bucket_batch"
        ) as batch,
        patch(
            "app.api.routes.projects.fs.get_object_url",
            return_value="https://signed",
        ),
    ):
        # Objects pushed before the switch are still found
        for path, exists in [(old_path, True), (new_path, True), ("x", False)]:
            response = client.post(
                FS_OPS_URL, json={"operation": "exists", "path": path}
            )
            assert response.json()["result"]["exists"] is exists
        response = client.post(
            FS_OPS_URL, json={"operation": "get", "path": old_path}
        )
        assert response.json()["backend"] == "s3"
        assert response.json()["access"]["url"] == "https://signed"
        response = client.post(
            FS_OPS_URL, json={"operation": "get", "path": new_path}
        )
        access = response.json()["access"]
        assert access["kind"] == "hf-xet"
        assert access["operation"] == "download"
        assert access["bucket"] == "ns/bkt"
        assert access["xet_hash"] == "a" * 64
        assert access["size"] == 4
        get_xet_token.assert_called_with(hf, "read")
        response = client.post(
            FS_OPS_URL, json={"operation": "get", "path": "missing"}
        )
        assert response.status_code == 404
        # A folder in HF has nothing to download
        response = client.post(
            FS_OPS_URL, json={"operation": "get", "path": "files/md5/bb"}
        )
        assert response.status_code == 400
        # Listing merges what's in both
        response = client.post(
            FS_OPS_URL, json={"operation": "find", "path": "files/md5"}
        )
        names = sorted(response.json()["result"]["paths"])
        assert names == [
            f"{OWNER}/{PROJECT}/{old_path}",
            f"{OWNER}/{PROJECT}/{new_path}",
        ]
        # New objects go to HF, with a Xet token to upload the content
        response = client.post(
            FS_OPS_URL,
            json={"operation": "put", "path": "files/md5/cc/x"},
        )
        access = response.json()["access"]
        assert response.json()["backend"] == "hf"
        assert access == {
            "kind": "hf-xet",
            "operation": "upload",
            "bucket": "ns/bkt",
            "cas_url": "https://cas",
            "access_token": "xet",
            "expires_at_unix": 123,
            "xet_hash": None,
            "size": None,
        }
        get_xet_token.assert_called_with(hf, "write")
        # Then the hub adds the paths with the owner's credential, in one
        # call to HF however many there are
        register = {"operation": "register", "paths": ["files/md5/cc/x"]}
        response = client.post(
            f"{FS_OPS_URL}/batch",
            json=register | {"xet_hashes": {"files/md5/cc/x": "b" * 64}},
        )
        assert response.status_code == 200
        batch.assert_called_once_with(
            hf,
            [
                {
                    "type": "addFile",
                    "path": f"{OWNER}/{PROJECT}/files/md5/cc/x",
                    "xetHash": "b" * 64,
                }
            ],
        )
        for bad_hashes in [None, {}, {"files/md5/cc/x": "not-a-hash"}]:
            response = client.post(
                f"{FS_OPS_URL}/batch",
                json=register | {"xet_hashes": bad_hashes},
            )
            assert response.status_code == 422
        # Content uploaded to a bucket the project no longer uses isn't
        # added to the new one
        register |= {"xet_hashes": {"files/md5/cc/x": "b" * 64}}
        batch.reset_mock()
        response = client.post(
            f"{FS_OPS_URL}/batch", json=register | {"bucket": "ns/old"}
        )
        assert response.status_code == 409
        batch.assert_not_called()
        # Paths HF rejects are an error, though the others were added
        batch.side_effect = HfBucketBatchError(
            [
                {
                    "path": f"{OWNER}/{PROJECT}/files/md5/cc/x",
                    "error": "Unknown xet hash",
                }
            ]
        )
        response = client.post(
            f"{FS_OPS_URL}/batch", json=register | {"bucket": "ns/bkt"}
        )
        assert response.status_code == 422
        assert "1 of 1 files: files/md5/cc/x" in response.json()["detail"]
        batch.side_effect = None
        # The batch endpoint falls back too, looking up all of a batch's
        # paths in HF at once rather than one at a time

        def get_hf_paths_info(st, paths):
            infos = {}
            for path in paths:
                full = f"{st.data_prefix}/{path}"
                if st.fs.isfile(full):
                    infos[path] = st.fs.info(full)
            return infos

        with (
            patch(
                "app.api.routes.projects.fs.storage.get_hf_paths_info",
                side_effect=get_hf_paths_info,
            ) as paths_info,
            patch.object(
                hf.fs, "exists", side_effect=AssertionError("per path")
            ),
        ):
            response = client.post(
                f"{FS_OPS_URL}/batch",
                json={
                    "operation": "info",
                    "paths": [old_path, new_path],
                    "include": ["exists", "content"],
                },
            )
        assert response.status_code == 200, response.text
        paths_info.assert_called_once()
        results = response.json()["results"]
        assert results[old_path]["exists"] is True
        assert results[old_path]["info"]["size"] == 1
        assert results[new_path]["info"]["size"] == 4
        assert results[new_path]["content_base64"] == "bmV3IQ=="
        # HF objects come with what a client needs to download them
        assert results[new_path]["info"]["xet_hash"] == "a" * 64
        assert results[new_path]["info"]["bucket"] == "ns/bkt"
        assert "xet_hash" not in results[old_path]["info"]
    # A project on the hub's storage has nothing to register, which a client
    # that still has HF access learns from a 409, so it gets new access
    with (
        patch(
            "app.api.routes.projects.fs.app.projects.get_project",
            return_value=_fake_project(),
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_project_storages",
            return_value=[internal],
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_project_storage",
            return_value=internal,
        ),
    ):
        response = client.post(
            f"{FS_OPS_URL}/batch",
            json={
                "operation": "register",
                "paths": ["files/md5/cc/x"],
                "xet_hashes": {"files/md5/cc/x": "b" * 64},
            },
        )
        assert response.status_code == 409
    # A bucket dedicated to the project holds it at its root, though clients
    # see the same paths as anywhere else
    dedicated = ProjectStorage(
        backend="hf",
        fs=FakeHfFileSystem(),
        data_prefix="/buckets/ns/proj",
        resource=SimpleNamespace(  # type: ignore[arg-type]
            bucket="ns/proj", project_id="project-id"
        ),
        token="hf-owner-token",
    )
    dedicated.fs.pipe(f"/buckets/ns/proj/{new_path}", b"new!")
    with (
        patch(
            "app.api.routes.projects.fs.app.projects.get_project",
            return_value=_fake_project(),
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_project_storages",
            return_value=[dedicated, internal],
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_project_storage",
            return_value=dedicated,
        ),
        patch(
            "app.api.routes.projects.fs.storage.post_hf_bucket_batch"
        ) as batch,
    ):
        response = client.post(
            FS_OPS_URL, json={"operation": "find", "path": "files/md5"}
        )
        assert sorted(response.json()["result"]["paths"]) == [
            f"{OWNER}/{PROJECT}/{old_path}",
            f"{OWNER}/{PROJECT}/{new_path}",
        ]
        register = {
            "operation": "register",
            "paths": ["files/md5/cc/x"],
            "xet_hashes": {"files/md5/cc/x": "b" * 64},
        }
        response = client.post(f"{FS_OPS_URL}/batch", json=register)
        assert response.status_code == 200
        assert batch.call_args.args[1][0]["path"] == "files/md5/cc/x"
        batch.side_effect = HfBucketBatchError(
            [{"path": "files/md5/cc/x", "error": "Unknown xet hash"}]
        )
        response = client.post(f"{FS_OPS_URL}/batch", json=register)
        assert "1 of 1 files: files/md5/cc/x" in response.json()["detail"]


def test_batch_op_answers_every_path(client: TestClient):
    from app.storage import ProjectStorage

    stored = {f"s3://data/{OWNER}/{PROJECT}/f{i}": b"x" * i for i in range(50)}
    stored[f"s3://data/{OWNER}/{PROJECT}/big"] = b""
    # Paths answered one at a time would never all reach this together
    overlapping = {f"s3://data/{OWNER}/{PROJECT}/f{i}" for i in range(4)}
    barrier = threading.Barrier(len(overlapping), timeout=10)

    def info(path):
        if path in overlapping:
            barrier.wait()
        if path not in stored:
            raise FileNotFoundError(path)
        size = 2_000_000 if path.endswith("/big") else len(stored[path])
        return {"name": path, "size": size, "type": "file"}

    def cat_file(path):
        if path not in stored:
            raise FileNotFoundError(path)
        return stored[path]

    def ls(path, detail=False):
        if path not in stored:
            raise FileNotFoundError(path)
        return [path]

    fake_fs = MagicMock()
    fake_fs.exists.return_value = True
    fake_fs.info.side_effect = info
    fake_fs.cat_file.side_effect = cat_file
    fake_fs.ls.side_effect = ls
    paths = [f"f{i}" for i in range(50)] + ["missing", "big"]
    with (
        patch(
            "app.api.routes.projects.fs.app.projects.get_project",
            return_value=_fake_project(),
        ),
        patch(
            "app.api.routes.projects.fs.storage.get_project_storages",
            return_value=[
                ProjectStorage(
                    backend="s3", fs=fake_fs, data_prefix="s3://data"
                )
            ],
        ),
    ):
        response = client.post(
            f"{FS_OPS_URL}/batch",
            json={
                "operation": "info",
                "paths": paths,
                "include": ["info", "content"],
            },
        )
        # Asking only about existence reads no content
        exists_response = client.post(
            f"{FS_OPS_URL}/batch",
            json={"operation": "exists", "paths": ["f1", "missing"]},
        )
    assert response.status_code == 200
    results = response.json()["results"]
    assert list(results) == paths
    for i in range(50):
        result = results[f"f{i}"]
        assert result["info"]["size"] == i
        assert base64.b64decode(result["content_base64"]) == b"x" * i
    assert results["missing"] == {
        "exists": None,
        "info": None,
        "content_base64": None,
    }
    # Too big to send, but still there
    assert results["big"]["info"]["size"] == 2_000_000
    assert results["big"]["content_base64"] is None
    # Content's size check reuses the info rather than asking again
    assert fake_fs.info.call_count == len(paths)
    assert fake_fs.cat_file.call_count == 50
    assert exists_response.status_code == 200
    exists_results = exists_response.json()["results"]
    assert exists_results["f1"]["exists"] is True
    assert exists_results["missing"]["exists"] is False
    assert fake_fs.cat_file.call_count == 50
