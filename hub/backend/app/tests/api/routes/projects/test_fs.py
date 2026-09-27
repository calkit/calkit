"""Tests for app.api.routes.projects.fs endpoints."""

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

    from app.storage import ProjectStorage

    class FakeHfFileSystem(MemoryFileSystem):  # type: ignore[misc]
        def info(self, path: str, **kwargs: Any) -> dict[str, Any]:
            info: dict[str, Any] = super().info(path, **kwargs)
            return info | {"xet_hash": "a" * 64}

    hf = ProjectStorage(
        backend="hf",
        fs=FakeHfFileSystem(),
        data_prefix="/buckets/ns/bkt",
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
        assert access["xet_hash"] == "a" * 64
        assert access["size"] == 4
        get_xet_token.assert_called_with(hf, "read")
        response = client.post(
            FS_OPS_URL, json={"operation": "get", "path": "missing"}
        )
        assert response.status_code == 404
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
            "cas_url": "https://cas",
            "access_token": "xet",
            "expires_at_unix": 123,
            "xet_hash": None,
            "size": None,
        }
        get_xet_token.assert_called_with(hf, "write")
        # Then the hub adds the path with the owner's credential
        response = client.post(
            FS_OPS_URL,
            json={
                "operation": "register",
                "path": "files/md5/cc/x",
                "xet_hash": "b" * 64,
            },
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
        for bad_hash in [None, "not-a-hash"]:
            response = client.post(
                FS_OPS_URL,
                json={
                    "operation": "register",
                    "path": "files/md5/cc/x",
                    "xet_hash": bad_hash,
                },
            )
            assert response.status_code == 422
        # The batch endpoint falls back too
        response = client.post(
            f"{FS_OPS_URL}/batch",
            json={
                "operation": "info",
                "paths": [old_path, new_path],
                "include": ["exists", "content"],
            },
        )
        results = response.json()["results"]
        assert results[old_path]["exists"] is True
        assert results[old_path]["info"]["size"] == 1
        assert results[new_path]["info"]["size"] == 4
        assert results[new_path]["content_base64"] == "bmV3IQ=="
    # A project on the hub's storage has nothing to register
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
            FS_OPS_URL,
            json={
                "operation": "register",
                "path": "files/md5/cc/x",
                "xet_hash": "b" * 64,
            },
        )
        assert response.status_code == 400
