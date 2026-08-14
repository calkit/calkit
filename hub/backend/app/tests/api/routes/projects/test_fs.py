"""Tests for app.api.routes.projects.fs endpoints."""

from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

from fastapi.testclient import TestClient

from app.config import settings

OWNER = "testowner"
PROJECT = "testproject"
FS_OPS_URL = f"{settings.API_V1_STR}/projects/{OWNER}/{PROJECT}/fs/ops"


def _fake_project():
    return SimpleNamespace()


def test_lowercases_owner_and_project_name(client: TestClient):
    mixed_owner = "TestOwner"
    mixed_project = "TestProject"
    url = (
        f"{settings.API_V1_STR}/projects/{mixed_owner}/{mixed_project}/fs/ops"
    )
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
    url = f"{settings.API_V1_STR}/projects/OwnerWithCaps/{PROJECT}/fs/ops"
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
