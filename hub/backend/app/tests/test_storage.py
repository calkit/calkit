"""Tests for ``app.storage``."""

import dataclasses
import io
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
import requests
from huggingface_hub.errors import BucketNotFoundError
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
            bucket="someone/my-project",
            project_id="project-id",
            created=datetime(2026, 11, 1),
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
    # Worker threads don't need the resource's database row
    detached = dataclasses.replace(dedicated)
    detached.resource = None
    assert detached.bucket == "someone/my-project"
    assert detached.make_container_path("someone", "My-Project", path) == path
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
        storage.set_project_bucket_visibility(session, project, True)  # type: ignore[arg-type]
        storage.set_project_bucket_visibility(session, project, False)  # type: ignore[arg-type]
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
        hf_created = datetime(2026, 11, 1, tzinfo=timezone.utc)
        dvc_object = SimpleNamespace(
            type="file", path=f"files/md5/ab/{'c' * 30}"
        )
        dvc_dir = SimpleNamespace(
            type="file", path=f"files/md5/ab/{'d' * 30}.dir"
        )
        folder = SimpleNamespace(type="directory", path="files")
        api.return_value.bucket_info.return_value = SimpleNamespace(
            created_at=hf_created
        )
        api.return_value.list_bucket_tree.return_value = [
            folder,
            dvc_object,
            dvc_dir,
        ]
        # A bucket recreated since, or with anything else in it, stops
        # everything before any storage is touched
        for created_at, files in (
            (hf_created + timedelta(days=1), [dvc_object]),
            (hf_created, [dvc_object, SimpleNamespace(type="file", path="a")]),
            (
                hf_created,
                [SimpleNamespace(type="file", path="files/md5/ab/cd")],
            ),
        ):
            api.return_value.bucket_info.return_value.created_at = created_at
            api.return_value.list_bucket_tree.return_value = files
            with pytest.raises(storage.UnsafeStorageDeleteError):
                storage.delete_project_objects(None, project, "user-id")  # type: ignore[arg-type]
        api.return_value.delete_bucket.assert_not_called()
        api.return_value.batch_bucket_files.assert_not_called()
        assert internal.fs.exists(f"/internal/data/someone/my-project/{path}")
        # Clock differences between the hub and HF are allowed for
        api.return_value.bucket_info.return_value.created_at = (
            hf_created + timedelta(minutes=1)
        )
        api.return_value.list_bucket_tree.return_value = [
            folder,
            dvc_object,
            dvc_dir,
        ]
        storage.delete_project_objects(None, project, "user-id")  # type: ignore[arg-type]
        api.return_value.delete_bucket.assert_called_once_with(
            "someone/my-project", missing_ok=True
        )
        api.return_value.batch_bucket_files.assert_called_once_with(
            "someone/calkit", delete=[f"someone/my-project/{path}"]
        )
        # A bucket already gone is fine
        api.return_value.bucket_info.side_effect = BucketNotFoundError(
            "gone",
            response=httpx.Response(
                404, request=httpx.Request("GET", "https://huggingface.co")
            ),
        )
        storage.check_safe_to_delete(dedicated)
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
    # Cut off, so it's copied again
    partial = internal.make_project_path("someone", "two", path)
    internal.fs.pipe(partial, b"t")

    class BrokenRead(io.BytesIO):
        def read(self, *args: object) -> bytes:
            raise OSError("HF down")

    class ExpiredFs(MemoryFileSystem):
        def open(self, *args: object, **kwargs: object) -> None:
            raise PermissionError("expired token")

    expired = dataclasses.replace(shared, fs=ExpiredFs())
    with (
        patch.object(
            storage, "get_resource_storage", return_value=shared
        ) as get_storage,
        patch.object(storage, "get_internal_storage", return_value=internal),
        patch.object(storage, "get_resource_projects", return_value=projects),
        patch("app.config.settings.ENVIRONMENT", "local"),
    ):
        # Only what's left to copy counts toward the plan
        assert storage.get_resource_gb_to_copy(None, None) == {  # type: ignore[arg-type]
            "someone": 3 / 1e9
        }
        # A failed or short read leaves the hub's copy alone
        for source_file in (BrokenRead(b"two"), io.BytesIO(b"tw")):
            with (
                patch.object(shared.fs, "open", return_value=source_file),
                pytest.raises(OSError),
            ):
                storage.copy_resource_to_internal(None, None)  # type: ignore[arg-type]
            assert internal.fs.cat(partial) == b"t"
        # Each object gets a current token
        get_storage.side_effect = [expired, expired, shared]
        assert storage.copy_resource_to_internal(None, None) == 1  # type: ignore[arg-type]
        get_storage.side_effect = None
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
    project.dvc_storage_id = resource.id
    db.add(project)
    db.commit()
    resource_id = resource.id
    project_id = project.id
    # A failed copy leaves everything as it was, to try again
    with (
        patch.object(
            storage,
            "copy_resource_to_internal",
            side_effect=OSError("HF down"),
        ),
        patch("app.mixpanel.user_transferred_storage") as tracked,
    ):
        with pytest.raises(OSError):
            storage.transfer_storage_and_disconnect(str(user.id))
    assert tracked.call_args.kwargs == {"succeeded": False}
    db.expire_all()
    assert db.get(StorageResource, resource_id) is not None
    with (
        patch.object(
            storage, "copy_resource_to_internal", return_value=3
        ) as copy,
        patch("app.mixpanel.user_transferred_storage") as tracked,
    ):
        storage.transfer_storage_and_disconnect(str(user.id))
    copy.assert_called_once()
    assert tracked.call_args.args[1:] == (1, 3)
    assert tracked.call_args.kwargs == {"succeeded": True}
    db.expire_all()
    assert db.get(StorageResource, resource_id) is None
    # Its project went to the hub's own storage before the copy
    moved = db.get(Project, project_id)
    assert moved is not None and moved.dvc_storage_id is None
    assert (
        users.get_external_credential(
            session=db, user=user, provider="huggingface"
        )
        is None
    )


def test_get_hf_paths_info() -> None:
    from datetime import datetime

    target = storage.ProjectStorage(
        backend="hf",
        fs=None,
        data_prefix="buckets/ns/bkt",
        resource=SimpleNamespace(  # type: ignore[arg-type]
            bucket="ns/bkt", project_id=None
        ),
        token="hf-token",
    )
    found = SimpleNamespace(
        path="a/b", size=3, xet_hash="h" * 64, mtime=datetime(2026, 1, 1)
    )
    with patch("huggingface_hub.HfApi") as api:
        api.return_value.get_bucket_paths_info.return_value = [found]
        infos = storage.get_hf_paths_info(target, ["a/b", "missing"])
    api.assert_called_once_with(token="hf-token")
    api.return_value.get_bucket_paths_info.assert_called_once_with(
        "ns/bkt", ["a/b", "missing"]
    )
    # Missing paths are left out, like FileNotFoundError from fs.info
    assert infos == {
        "a/b": {
            "name": "buckets/ns/bkt/a/b",
            "size": 3,
            "type": "file",
            "mtime": datetime(2026, 1, 1),
            "xet_hash": "h" * 64,
        }
    }


def test_unreachable_storage() -> None:
    from fastapi import HTTPException

    resource = SimpleNamespace(
        id="resource-id",
        name=None,
        bucket="someone/proj",
        project_id="p",
        credential_user_id="member-id",
    )
    project = SimpleNamespace(
        id="p", dvc_storage=resource, dvc_storage_id="resource-id"
    )
    project.storage_history = []
    session = SimpleNamespace(
        exec=lambda _: SimpleNamespace(all=lambda: [resource])
    )
    unreachable = HTTPException(401, "User needs to authenticate")
    with (
        patch.object(storage, "get_resource_storage", side_effect=unreachable),
        patch("huggingface_hub.HfApi") as api,
    ):
        # Reads skip it, so everything else stays readable
        storages = storage.get_project_storages(session, project)  # type: ignore[arg-type]
        assert [st.resource for st in storages] == [None]
        # Deleting and changing visibility don't, so nothing is left behind
        # or left public without anyone knowing
        with pytest.raises(storage.UnreachableStorageError) as e:
            storage.get_project_storages(
                session,  # type: ignore[arg-type]
                project,  # type: ignore[arg-type]
                skip_unreachable=False,
            )
        assert e.value.resource is resource
        # Someone else's storage is left alone, reachable or not
        storages = storage.get_project_storages(
            session,  # type: ignore[arg-type]
            project,  # type: ignore[arg-type]
            skip_unreachable=False,
            credential_user_id="other-id",
        )
        assert [st.resource for st in storages] == [None]
        with pytest.raises(storage.UnreachableStorageError):
            storage.get_project_storages(
                session,  # type: ignore[arg-type]
                project,  # type: ignore[arg-type]
                skip_unreachable=False,
                credential_user_id="member-id",
            )
        with pytest.raises(storage.UnreachableStorageError):
            storage.set_project_bucket_visibility(session, project, False)  # type: ignore[arg-type]
    api.return_value.update_bucket_settings.assert_not_called()
