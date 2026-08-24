"""Tests for app.api.routes.projects.dvc endpoints."""

import hashlib
import io
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

from fastapi.testclient import TestClient

from app.config import settings

OWNER = "testowner"
PROJECT = "testproject"
IDX = "ab"
MD5 = "cdef1234567890abcdef1234567890ab"
GET_URL = (
    f"{settings.API_V1_STR}/projects/{OWNER}/{PROJECT}"
    f"/dvc/files/md5/{IDX}/{MD5}"
)


def _fake_project() -> SimpleNamespace:
    sub = SimpleNamespace(storage_limit=10.0)
    owner = SimpleNamespace(subscription=sub)
    return SimpleNamespace(owner=owner)


def _dvc_scope_headers(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> dict[str, str]:
    response = client.post(
        f"{settings.API_V1_STR}/user/tokens",
        headers=normal_user_token_headers,
        json={"expires_days": 7, "scope": "dvc", "description": "test"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_get_dvc_file_lowercases_owner_and_project_name(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    headers = _dvc_scope_headers(client, normal_user_token_headers)
    fake_fs = MagicMock()
    fake_fs.exists.return_value = True
    fake_fs.open.return_value.__enter__.return_value = io.BytesIO(b"data")
    fake_fs.open.return_value.__exit__.return_value = False
    mixed_owner = "TestOwner"
    mixed_project = "TestProject"
    url = (
        f"{settings.API_V1_STR}/projects/{mixed_owner}/{mixed_project}"
        f"/dvc/files/md5/{IDX}/{MD5}"
    )
    with (
        patch(
            "app.api.routes.projects.dvc.app.projects.get_project",
            return_value=_fake_project(),
        ) as mock_get_project,
        patch("app.api.routes.projects.dvc.mixpanel.user_dvc_pulled"),
        patch(
            "app.api.routes.projects.dvc.get_object_fs",
            return_value=fake_fs,
        ),
        patch(
            "app.api.routes.projects.dvc.make_data_fpath",
            return_value="s3://data/testowner/testproject/files/md5/ab/cdef",
        ) as mock_make_fpath,
    ):
        response = client.get(url, headers=headers)
    assert response.status_code == 200
    mock_get_project.assert_called_once_with(
        session=ANY,
        owner_name="testowner",
        project_name="testproject",
        current_user=ANY,
        min_access_level="read",
    )
    mock_make_fpath.assert_called_once_with(
        owner_name="testowner",
        project_name="testproject",
        idx=IDX,
        md5=MD5,
    )


def test_get_dvc_file_not_found_returns_404(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    headers = _dvc_scope_headers(client, normal_user_token_headers)
    fake_fs = MagicMock()
    fake_fs.exists.return_value = False
    with (
        patch(
            "app.api.routes.projects.dvc.app.projects.get_project",
            return_value=_fake_project(),
        ),
        patch("app.api.routes.projects.dvc.mixpanel.user_dvc_pulled"),
        patch(
            "app.api.routes.projects.dvc.get_object_fs",
            return_value=fake_fs,
        ),
        patch(
            "app.api.routes.projects.dvc.make_data_fpath",
            return_value="s3://data/testowner/testproject/files/md5/ab/cdef",
        ),
    ):
        response = client.get(GET_URL, headers=headers)
    assert response.status_code == 404


def test_post_dvc_file_lowercases_owner_and_project_name(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    headers = _dvc_scope_headers(client, normal_user_token_headers)
    fake_fs = MagicMock()
    fake_fs.exists.return_value = True
    fake_fs.open.return_value.__enter__.return_value = io.BytesIO()
    fake_fs.open.return_value.__exit__.return_value = False
    fake_fs.mv = MagicMock()
    body = b"\x00" * 4
    digest = hashlib.md5(body).hexdigest()
    idx = digest[:2]
    md5 = digest[2:]
    mixed_owner = "MyOrg"
    mixed_project = "MyProject"
    post_url = (
        f"{settings.API_V1_STR}/projects/{mixed_owner}/{mixed_project}"
        f"/dvc/files/md5/{idx}/{md5}"
    )
    with (
        patch(
            "app.api.routes.projects.dvc.app.projects.get_project",
            return_value=_fake_project(),
        ) as mock_get_project,
        patch("app.api.routes.projects.dvc.mixpanel.user_dvc_pushed"),
        patch(
            "app.api.routes.projects.dvc.get_object_fs",
            return_value=fake_fs,
        ),
        patch(
            "app.api.routes.projects.dvc.get_storage_usage",
            return_value=0.1,
        ),
        patch(
            "app.api.routes.projects.dvc.get_data_prefix",
            return_value="s3://data",
        ),
        patch(
            "app.api.routes.projects.dvc.make_data_fpath",
            return_value=f"s3://data/myorg/myproject/files/md5/{idx}/{md5}",
        ) as mock_make_fpath,
        patch("app.api.routes.projects.dvc.remove_gcs_content_type"),
        patch(
            "app.api.routes.projects.dvc.invalidate_storage_usage_cache"
        ) as mock_invalidate,
    ):
        response = client.post(post_url, headers=headers, content=body)
    assert response.status_code == 200
    mock_get_project.assert_called_once_with(
        session=ANY,
        owner_name="myorg",
        project_name="myproject",
        current_user=ANY,
        min_access_level="write",
    )
    mock_make_fpath.assert_called_once_with(
        owner_name="myorg",
        project_name="myproject",
        idx=idx,
        md5=md5,
    )
    mock_invalidate.assert_called_once_with("myorg")


def test_post_dvc_file_storage_limit_exceeded_returns_400(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    headers = _dvc_scope_headers(client, normal_user_token_headers)
    fake_fs = MagicMock()
    fake_fs.exists.return_value = True
    body = b"x"
    digest = hashlib.md5(body).hexdigest()
    idx = digest[:2]
    md5 = digest[2:]
    post_url = (
        f"{settings.API_V1_STR}/projects/{OWNER}/{PROJECT}"
        f"/dvc/files/md5/{idx}/{md5}"
    )
    with (
        patch(
            "app.api.routes.projects.dvc.app.projects.get_project",
            return_value=_fake_project(),
        ),
        patch("app.api.routes.projects.dvc.mixpanel.user_dvc_pushed"),
        patch(
            "app.api.routes.projects.dvc.get_object_fs",
            return_value=fake_fs,
        ),
        patch(
            "app.api.routes.projects.dvc.get_storage_usage",
            return_value=999.0,
        ),
        patch(
            "app.api.routes.projects.dvc.get_data_prefix",
            return_value="s3://data",
        ),
        patch(
            "app.api.routes.projects.dvc.make_data_fpath",
            return_value=f"s3://data/{OWNER}/{PROJECT}/files/md5/{idx}/{md5}",
        ),
        patch("app.api.routes.projects.dvc.mixpanel.user_out_of_storage"),
    ):
        response = client.post(post_url, headers=headers, content=body)
    assert response.status_code == 400
    assert "Storage limit exceeded" in response.json()["detail"]


def test_post_dvc_file_md5_mismatch_cleans_pending_file(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    headers = _dvc_scope_headers(client, normal_user_token_headers)
    fake_fs = MagicMock()
    fake_fs.exists.return_value = True
    fake_fs.open.return_value.__enter__.return_value = io.BytesIO()
    fake_fs.open.return_value.__exit__.return_value = False
    body = b"mismatch"
    idx = "aa"
    md5 = "bb" * 16
    post_url = (
        f"{settings.API_V1_STR}/projects/{OWNER}/{PROJECT}"
        f"/dvc/files/md5/{idx}/{md5}"
    )
    with (
        patch(
            "app.api.routes.projects.dvc.app.projects.get_project",
            return_value=_fake_project(),
        ),
        patch("app.api.routes.projects.dvc.mixpanel.user_dvc_pushed"),
        patch(
            "app.api.routes.projects.dvc.get_object_fs",
            return_value=fake_fs,
        ),
        patch(
            "app.api.routes.projects.dvc.get_storage_usage",
            return_value=0.1,
        ),
        patch(
            "app.api.routes.projects.dvc.get_data_prefix",
            return_value="s3://data",
        ),
        patch(
            "app.api.routes.projects.dvc.make_data_fpath",
            return_value=f"s3://data/{OWNER}/{PROJECT}/files/md5/{idx}/{md5}",
        ),
        patch("app.api.routes.projects.dvc.remove_gcs_content_type"),
    ):
        response = client.post(post_url, headers=headers, content=body)
    assert response.status_code == 400
    fake_fs.rm.assert_called_once()
