"""Tests for app.api.routes.projects.fs endpoints."""

import base64
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

from fastapi.testclient import TestClient

OWNER = "testowner"
PROJECT = "testproject"
FS_OPS_URL = f"/projects/{OWNER}/{PROJECT}/fs/ops"


def _fake_project():
    return SimpleNamespace()


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


def test_batch_op_answers_every_path(client: TestClient):
    stored = {f"s3://data/{OWNER}/{PROJECT}/f{i}": b"x" * i for i in range(50)}
    stored[f"s3://data/{OWNER}/{PROJECT}/big"] = b""

    def info(path):
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
