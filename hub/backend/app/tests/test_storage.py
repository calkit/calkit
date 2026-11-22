"""Tests for ``app.storage``."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from sqlmodel import Session

from app import storage


def test_post_hf_bucket_batch() -> None:
    target = storage.ProjectStorage(
        backend="hf",
        fs=None,
        data_prefix="buckets/ns/bkt",
        resource=SimpleNamespace(  # type: ignore[arg-type]
            bucket="ns/bkt", project_id=None
        ),
        token="hf-token",
    )
    ops = [{"type": "addFile", "path": "a", "xetHash": "x"}]

    def respond(status_code: int, body: dict) -> requests.Response:
        resp = requests.Response()
        resp.status_code = status_code
        resp._content = json.dumps(body).encode()
        resp.url = "https://huggingface.co/api/buckets/ns/bkt/batch"
        return resp

    # HF lists the operations that failed in a 200 if only some did, or a 422
    # if all did
    failed = {"failed": [{"path": "a", "error": "Unknown xet hash"}]}
    for status_code in (200, 422):
        with (
            patch.object(
                requests, "post", return_value=respond(status_code, failed)
            ) as post,
            pytest.raises(storage.HfBucketBatchError) as e,
        ):
            storage.post_hf_bucket_batch(target, ops)
        assert e.value.failures == failed["failed"]
        assert "Unknown xet hash" in str(e.value)
    assert post.call_args.kwargs["headers"]["Authorization"] == (
        "Bearer hf-token"
    )
    with patch.object(requests, "post", return_value=respond(200, {})):
        storage.post_hf_bucket_batch(target, ops)
    with (
        patch.object(requests, "post", return_value=respond(500, {})),
        pytest.raises(requests.HTTPError),
    ):
        storage.post_hf_bucket_batch(target, ops)


def test_dedicated_storage() -> None:
    from fsspec.implementations.memory import (  # type: ignore[import-untyped]
        MemoryFileSystem,
    )

    project = SimpleNamespace(
        id="project-id",
        name="My-Project",
        owner_account_name="someone",
        is_public=True,
    )
    dedicated = storage.ProjectStorage(
        backend="hf",
        fs=MemoryFileSystem(),
        data_prefix="/buckets/someone/my-project",
        resource=SimpleNamespace(  # type: ignore[arg-type]
            bucket="someone/my-project", project_id="project-id"
        ),
        token="hf-token",
    )
    shared = storage.ProjectStorage(
        backend="hf",
        fs=MemoryFileSystem(),
        data_prefix="/buckets/someone/calkit",
        resource=SimpleNamespace(  # type: ignore[arg-type]
            bucket="someone/calkit", project_id=None
        ),
        token="hf-token",
    )
    internal = storage.ProjectStorage(
        backend="s3", fs=MemoryFileSystem(), data_prefix="/internal/data"
    )
    # A dedicated bucket holds the project at its root, and others under its
    # owner and name
    path = "files/md5/ab/cd"
    assert dedicated.make_project_path("someone", "My-Project", path) == (
        f"/buckets/someone/my-project/{path}"
    )
    assert dedicated.make_container_path("someone", "My-Project", path) == path
    assert shared.make_container_path("someone", "My-Project", path) == (
        f"someone/my-project/{path}"
    )
    assert internal.make_project_path("someone", "My-Project") == (
        "/internal/data/someone/my-project"
    )
    # Dedicated buckets follow their project's visibility
    session = SimpleNamespace(
        exec=lambda _: SimpleNamespace(all=lambda: [dedicated.resource])
    )
    with (
        patch.object(storage, "get_resource_storage", return_value=dedicated),
        patch("huggingface_hub.HfApi") as api,
    ):
        storage.set_project_bucket_visibility(session, project)  # type: ignore[arg-type]
        project.is_public = False
        storage.set_project_bucket_visibility(session, project)  # type: ignore[arg-type]
    api.assert_called_with(token="hf-token")
    settings = api.return_value.update_bucket_settings
    assert [c.kwargs["private"] for c in settings.call_args_list] == [
        False,
        True,
    ]
    assert settings.call_args.args == ("someone/my-project",)
    # Deleting a project's objects deletes its dedicated bucket and its
    # folders elsewhere, and nothing of other projects
    for st in (shared, internal):
        st.fs.pipe(st.make_project_path("someone", "My-Project", path), b"x")
        st.fs.pipe(st.make_project_path("someone", "other", path), b"x")
    with (
        patch.object(
            storage,
            "get_project_storages",
            return_value=[dedicated, shared, internal],
        ),
        patch("huggingface_hub.HfApi") as api,
    ):
        storage.delete_project_objects(None, project)  # type: ignore[arg-type]
    api.return_value.delete_bucket.assert_called_once_with(
        "someone/my-project", missing_ok=True
    )
    api.return_value.batch_bucket_files.assert_called_once_with(
        "someone/calkit", delete=[f"someone/my-project/{path}"]
    )
    assert not internal.fs.exists("/internal/data/someone/my-project")
    assert internal.fs.exists(f"/internal/data/someone/other/{path}")


def test_copy_resource_to_internal() -> None:
    from fsspec.implementations.memory import (  # type: ignore[import-untyped]
        MemoryFileSystem,
    )

    projects = [
        SimpleNamespace(owner_account_name="someone", name="one"),
        SimpleNamespace(owner_account_name="someone", name="two"),
    ]
    shared = storage.ProjectStorage(
        backend="hf",
        fs=MemoryFileSystem(),
        data_prefix="/buckets/someone/calkit",
        resource=SimpleNamespace(  # type: ignore[arg-type]
            bucket="someone/calkit", project_id=None
        ),
    )
    internal = storage.ProjectStorage(
        backend="s3", fs=MemoryFileSystem(), data_prefix="/internal/data"
    )
    path = "files/md5/ab/cd"
    for project in projects:
        shared.fs.pipe(
            shared.make_project_path("someone", project.name, path),
            project.name.encode(),
        )
    # Already copied, e.g., by an earlier run that stopped partway
    internal.fs.pipe(
        internal.make_project_path("someone", "one", path), b"one"
    )
    with (
        patch.object(storage, "get_resource_storage", return_value=shared),
        patch.object(storage, "get_internal_storage", return_value=internal),
        patch.object(storage, "get_resource_projects", return_value=projects),
        patch("app.config.settings.ENVIRONMENT", "local"),
    ):
        assert storage.get_resource_usage(None, None) == {  # type: ignore[arg-type]
            "someone": 6 / 1e9
        }
        assert storage.copy_resource_to_internal(None, None) == 1  # type: ignore[arg-type]
    for project in projects:
        assert (
            internal.fs.cat(
                internal.make_project_path("someone", project.name, path)
            )
            == project.name.encode()
        )


def test_transfer_storage_and_disconnect(db: Session) -> None:
    import uuid
    from datetime import timedelta

    from app import users
    from app.core import utcnow
    from app.models import Project, ProjectStorageHistory, StorageResource
    from app.tests import create_random_user

    user = create_random_user(db)
    users.save_external_credential(
        session=db,
        user=user,
        provider="huggingface",
        secret_payload=json.dumps({"access_token": "hf"}),
        expires=utcnow() + timedelta(hours=1),
    )
    project = Project(
        name=f"hf-{uuid.uuid4().hex[:8]}",
        title="HF project",
        git_repo_url="https://github.com/someone/hf",
        owner_account_id=user.account.id,
        owner_account=user.account,
    )
    db.add(project)
    db.commit()
    resource = StorageResource(
        owner_account_id=user.account.id,
        project_id=project.id,
        kind="hf-bucket",
        bucket=f"someone/{project.name}",
        credential_user_id=user.id,
    )
    db.add(resource)
    db.commit()
    db.add(
        ProjectStorageHistory(
            project_id=project.id, storage_resource_id=resource.id
        )
    )
    db.commit()
    resource_id = resource.id
    # A failed copy leaves everything as it was, to try again
    with patch.object(
        storage, "copy_resource_to_internal", side_effect=OSError("HF down")
    ):
        with pytest.raises(OSError):
            storage.transfer_storage_and_disconnect(str(user.id))
    db.expire_all()
    assert db.get(StorageResource, resource_id) is not None
    with patch.object(
        storage, "copy_resource_to_internal", return_value=3
    ) as copy:
        storage.transfer_storage_and_disconnect(str(user.id))
    copy.assert_called_once()
    db.expire_all()
    assert db.get(StorageResource, resource_id) is None
    assert (
        users.get_external_credential(
            session=db, user=user, provider="huggingface"
        )
        is None
    )
