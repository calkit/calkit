"""Tests for ``app.storage``."""

import dataclasses
import io
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
    # The hub never deletes from connected storage
    with patch.object(requests, "post") as post, pytest.raises(ValueError):
        storage.post_hf_bucket_batch(
            target, ops + [{"type": "deleteFile", "path": "b"}]
        )
    post.assert_not_called()

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
    # Deleting a project's objects only touches the hub's own storage
    for st in (shared, internal):
        st.fs.pipe(st.make_project_path("someone", "My-Project", path), b"x")
        st.fs.pipe(st.make_project_path("someone", "other", path), b"x")
    with (
        patch.object(storage, "get_internal_storage", return_value=internal),
        patch("huggingface_hub.HfApi") as api,
    ):
        storage.delete_project_objects(project)  # type: ignore[arg-type]
    api.assert_not_called()
    assert shared.fs.exists(
        shared.make_project_path("someone", "My-Project", path)
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
    assert tracked.call_args.kwargs == {
        "succeeded": False,
        "provider": "huggingface",
    }
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
    assert tracked.call_args.kwargs == {
        "succeeded": True,
        "provider": "huggingface",
    }
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
        id="resource-id", name=None, bucket="someone/proj", project_id="p"
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
        storage_locations = storage.get_project_storage_locations(
            session, project
        )  # type: ignore[arg-type]
        assert [st.resource for st in storage_locations] == [None]
        # Changing visibility doesn't, so nothing is left public without
        # anyone knowing
        with pytest.raises(storage.UnreachableStorageError) as e:
            storage.set_project_bucket_visibility(session, project, False)  # type: ignore[arg-type]
        assert e.value.resource is resource
    api.return_value.update_bucket_settings.assert_not_called()


def test_box_storage(db: Session) -> None:
    import time
    import uuid
    from datetime import timedelta

    from app import users
    from app.core import utcnow
    from app.models import Project, ProjectStorageHistory, StorageResource
    from app.tests import create_random_user
    from calkit.tests.test_box import FakeBox, make_response

    # Folder IDs from other tests' fakes would collide
    storage._box_access.clear()
    storage._box_folder_ids.clear()
    box = FakeBox()
    calkit_folder = box.add("folder", "Calkit", "0")["id"]
    user = create_random_user(db)
    for provider in ("box", "huggingface"):
        users.save_external_credential(
            session=db,
            user=user,
            provider=provider,
            secret_payload=json.dumps(
                {"access_token": "token", "refresh_token": "r"}
            ),
            expires=utcnow() + timedelta(hours=1),
        )
    project = Project(
        name=f"box-{uuid.uuid4().hex[:8]}",
        title="Box project",
        git_repo_url="https://github.com/someone/box",
        owner_account_id=user.account.id,
        owner_account=user.account,
    )
    db.add(project)
    db.commit()
    resources = {}
    for kind, bucket in (("box-folder", calkit_folder), ("hf-bucket", "a/b")):
        resources[kind] = StorageResource(
            owner_account_id=user.account.id,
            name=kind,
            kind=kind,
            bucket=bucket,
            credential_user_id=user.id,
        )
        db.add(resources[kind])
    db.commit()
    db.add(
        ProjectStorageHistory(
            project_id=project.id,
            storage_resource_id=resources["box-folder"].id,
        )
    )
    project.dvc_storage_id = resources["box-folder"].id
    db.add(project)
    db.commit()
    db.refresh(project)
    # Each provider's connection only reaches its own storage
    for provider, kind in (
        ("box", "box-folder"),
        ("huggingface", "hf-bucket"),
    ):
        assert [
            r.kind
            for r in storage.get_credential_resources(db, user.id, provider)
        ] == [kind]
    owner = user.account.name
    downscopes = []

    def downscope(url, data, timeout):
        downscopes.append(data)
        return make_response(
            200, {"access_token": "token", "expires_in": 3600}
        )

    with (
        patch.object(
            requests.Session,
            "request",
            side_effect=lambda method, url, **kw: box.request(
                method, url, **kw
            ),
        ),
        patch.object(requests, "post", side_effect=downscope),
    ):
        target = storage.get_project_storage(db, project)
        assert target.backend == "box"
        locations = storage.get_project_storage_locations(db, project)
        assert [s.backend for s in locations] == ["box", storage.get_backend()]
        # Objects go under the owner and project in the Calkit folder
        path = "files/md5/ab/cdef"
        storage.put_project_objects(
            target, owner, project.name, [(path, b"content")]
        )
        fpath = target.make_project_path(owner, project.name, path)
        assert target.fs.cat_file(fpath) == b"content"
        project_folder = target.fs.get_folder_id(
            target.make_project_path(owner, project.name)
        )
        assert box.items[project_folder]["name"] == project.name.lower()
        found = storage.find_project_object(db, project, path)
        assert found is not None and found[0].backend == "box"
        assert storage.get_project_object_sizes(
            target, owner, project.name
        ) == {path: 7}
        # Clients get tokens downscoped to the project's folder, which are
        # reused for the same folder and operation while they have a while
        # left
        for _ in range(2):
            access = storage.get_box_access(target, project, "download")
        assert access["folder_id"] == project_folder
        assert access["expires_at_unixts"] > time.time() + 3000
        assert len(downscopes) == 1
        assert downscopes[0]["resource"].endswith(f"/folders/{project_folder}")
        assert "item_upload" not in downscopes[0]["scope"]
        storage._box_access[(project_folder, "download")][
            "expires_at_unixts"
        ] = int(time.time()) + 60
        storage.get_box_access(target, project, "download")
        assert len(downscopes) == 2
        # Uploading claims the project's folder, including one it already
        # has files in from before folders were claimed
        storage.get_box_access(target, project, "upload")
        assert "item_upload" in downscopes[2]["scope"]
        marker = target.make_project_path(
            owner, project.name, storage.PROJECT_FILE
        )
        assert target.fs.cat_file(marker) == str(project.id).encode()

        def make_project(name: str) -> SimpleNamespace:
            return SimpleNamespace(
                owner_account_name=owner, name=name, id=uuid.uuid4()
            )

        # Another project with its name, e.g., after it's deleted, can't
        # have it
        with pytest.raises(storage.FolderTakenError):
            storage.claim_project_folder(target, make_project(project.name))
        with pytest.raises(storage.FolderTakenError):
            storage.get_box_access(
                target, make_project(project.name), "upload"
            )
        # Nor can one switching to Box take a folder of files from before
        # folders were claimed, but one already using it can
        unclaimed = make_project("unclaimed")
        target.fs.pipe_file(
            target.make_project_path(owner, "unclaimed", path), b"old"
        )
        with pytest.raises(storage.FolderTakenError):
            storage.claim_project_folder(target, unclaimed)
        storage.claim_project_folder(target, unclaimed, adopt=True)
        storage.claim_project_folder(target, unclaimed)
        # Uploads to a project with no folder yet make it
        new = make_project("new")
        new_path = target.make_project_path(owner, "new")
        with pytest.raises(FileNotFoundError):
            target.fs.get_folder_id(new_path)
        storage.get_box_access(target, new, "upload")
        assert target.fs.get_folder_id(new_path)
        # Including after it's moved to the trash, as a later request, which
        # gets the storage again
        del box.items[target.fs.get_folder_id(new_path)]
        target = storage.get_project_storage(db, project)
        access = storage.get_box_access(target, new, "upload")
        assert access["folder_id"] in box.items
        # Browsers get Box's own short-lived link
        file_id = target.fs.get_file_id(fpath)
        box.queued = [
            make_response(302, headers={"Location": "https://dl.box.test/x"})
        ]
        assert (
            storage.get_project_object_url(target, fpath)
            == "https://dl.box.test/x"
        )
        assert box.calls[-1][1].endswith(f"/files/{file_id}/content")
        # And nothing is ever deleted from it
        with pytest.raises(PermissionError):
            target.fs.rm(fpath)


def test_s3_storage(db: Session) -> None:
    import socket
    import uuid

    import requests

    from app import users
    from app.config import settings
    from app.models import Project, StorageResource
    from app.tests import create_random_user

    # The dev MinIO stands in for someone's S3-compatible storage
    endpoint_url = settings.OBJECT_STORAGE_ENDPOINT_URL
    assert endpoint_url
    bucket_name = f"s3-test-{uuid.uuid4().hex[:8]}"
    fs = storage.get_s3_fs(
        str(settings.OBJECT_STORAGE_KEY),
        str(settings.OBJECT_STORAGE_SECRET),
        endpoint_url=endpoint_url,
    )
    assert fs.client_kwargs == {}
    fs.mkdir(bucket_name)
    user = create_random_user(db)
    credentials = {}
    for label in ("lab", "other"):
        credentials[label] = users.save_external_credential(
            session=db,
            user=user,
            provider="s3",
            secret_payload=json.dumps(
                {
                    "access_key_id": settings.OBJECT_STORAGE_KEY,
                    "secret_access_key": settings.OBJECT_STORAGE_SECRET,
                }
            ),
            credential_type="access-key",
            label=label,
            metadata_json={"endpoint_url": endpoint_url, "region": None},
        )
    project = Project(
        name=f"s3-{uuid.uuid4().hex[:8]}",
        title="S3 project",
        git_repo_url="https://github.com/someone/s3",
        owner_account_id=user.account.id,
        owner_account=user.account,
    )
    db.add(project)
    db.commit()
    owner = user.account.name
    namespace = StorageResource(
        owner_account_id=user.account.id,
        name="lab",
        kind="s3-bucket",
        bucket=f"{bucket_name}/calkit",
        credential_user_id=user.id,
        credential_id=credentials["lab"].id,
    )
    dedicated = StorageResource(
        owner_account_id=user.account.id,
        project_id=project.id,
        kind="s3-bucket",
        bucket=f"{bucket_name}/dvc",
        credential_user_id=user.id,
        credential_id=credentials["other"].id,
    )
    db.add(namespace)
    db.add(dedicated)
    db.commit()
    # Each connection reaches only its own storage
    for label, resource in (("lab", namespace), ("other", dedicated)):
        assert storage.get_credential_resources(
            db, user.id, provider="s3", label=label
        ) == [resource]
    # Projects in a shared bucket each get a folder, and a dedicated one
    # holds the project's objects at its root, e.g., an existing DVC remote
    target = storage.get_resource_storage(db, namespace)
    assert target.backend == "s3"
    assert target.data_prefix == f"s3://{bucket_name}/calkit"
    assert target.make_project_path(owner, project.name, "files") == (
        f"s3://{bucket_name}/calkit/{owner}/{project.name}/files"
    )
    remote = storage.get_resource_storage(db, dedicated)
    assert remote.make_project_path(owner, project.name, "files") == (
        f"s3://{bucket_name}/dvc/files"
    )
    path = "files/md5/ab/cdef"
    remote.fs.pipe_file(
        remote.make_project_path(owner, project.name, path), b"x"
    )
    with pytest.raises(storage.FolderTakenError):
        storage.claim_project_folder(remote, project)
    storage.claim_project_folder(remote, project, adopt=True)
    # Only DVC's objects in it are copied, including ones from DVC 2 at its
    # root, not anything else in the bucket
    dvc_2_path = f"ab/{'c' * 30}"
    for other_path in (dvc_2_path, "secret.csv"):
        remote.fs.pipe_file(
            remote.make_project_path(owner, project.name, other_path), b"x"
        )
    assert set(
        storage.get_project_object_sizes(remote, owner, project.name)
    ) == {path, dvc_2_path}
    # Whether keys can write is found by writing, since a folder already
    # marked as the project's isn't written to again
    storage.claim_project_folder(target, project)
    assert storage.folder_is_writable(target, project)
    assert target.fs.ls(target.make_project_path(owner, project.name)) == [
        target.fs._strip_protocol(
            target.make_project_path(owner, project.name, storage.PROJECT_FILE)
        )
    ]
    with patch.object(target.fs, "pipe_file", side_effect=PermissionError):
        assert not storage.folder_is_writable(target, project)
    marker = target.make_project_path(
        owner, project.name, storage.PROJECT_FILE
    )
    assert target.fs.cat_file(marker) == str(project.id).encode()
    # Another project with its name, e.g., after it's deleted, can't have it
    other = SimpleNamespace(
        owner_account_name=owner, name=project.name, id=uuid.uuid4()
    )
    with pytest.raises(storage.FolderTakenError):
        storage.claim_project_folder(target, other)  # type: ignore[arg-type]
    # Clients get presigned URLs, signed with the connection's keys
    fpath = target.make_project_path(owner, project.name, path)
    url = target.fs.sign(fpath, expiration=60, client_method="put_object")
    assert requests.put(url, data=b"hello", timeout=10).ok
    assert target.fs.cat_file(fpath) == b"hello"
    upload = storage.get_multipart_upload_info(
        target.fs, fpath, upload_size_bytes=100
    )
    assert len(upload["part_urls"]) == 1
    target.fs.call_s3(
        "abort_multipart_upload",
        Bucket=bucket_name,
        Key=upload["key"],
        UploadId=upload["upload_id"],
    )
    # Only HF buckets follow their project's visibility
    assert storage.set_project_bucket_visibility(db, project, True) == 0
    # Removing a connection removes its storage
    resource_id = namespace.id
    db.delete(credentials["lab"])
    db.commit()
    db.expire_all()
    assert db.get(StorageResource, resource_id) is None
    # Transferring S3 storage waits until upload URLs already given expire
    with (
        patch.object(storage, "copy_resource_to_internal", return_value=0),
        patch("app.mixpanel.user_transferred_storage"),
        patch("time.sleep") as sleep,
    ):
        storage.transfer_storage_and_disconnect(
            str(user.id), "s3", label="other"
        )
    sleep.assert_called_once_with(storage.UPLOAD_URL_EXPIRES + 60)
    # Endpoints off the internet are refused outside local development
    for bad in ("minio", "https://host:abc", "https://[::1"):
        with pytest.raises(storage.S3EndpointError):
            storage.check_s3_endpoint_url(bad)
    with patch("app.config.settings.ENVIRONMENT", "production"):
        for bad in ("http://example.com", "https://example.com/path"):
            with pytest.raises(storage.S3EndpointError):
                storage.check_s3_endpoint_url(bad)
        for address in ("10.0.0.1", "127.0.0.1", "169.254.169.254"):
            with (
                patch(
                    "socket.getaddrinfo",
                    return_value=[(None, None, None, "", (address, 443))],
                ),
                pytest.raises(storage.S3EndpointError),
            ):
                storage.check_s3_endpoint_url("https://s3.example.org")
        with patch(
            "socket.getaddrinfo",
            return_value=[(None, None, None, "", ("8.8.8.8", 443))],
        ):
            storage.check_s3_endpoint_url("https://s3.example.org")
        with (
            patch("socket.getaddrinfo", side_effect=socket.gaierror),
            pytest.raises(storage.S3EndpointError),
        ):
            storage.check_s3_endpoint_url("https://nope.invalid")
        # And each connection is checked as it's made, e.g., after a
        # redirect or the host resolving differently
        guarded = storage.get_s3_fs("key", "secret", "https://s3.example.org")
        assert guarded.config_kwargs["connector_args"] == {
            "socket_factory": storage.make_public_socket
        }
    # Including private IPv4 addresses inside IPv6 ones, e.g., for NAT64
    for address in (
        "127.0.0.1",
        "10.1.2.3",
        "169.254.169.254",
        "::1",
        "::ffff:10.0.0.1",
        "64:ff9b::a00:1",
        "2002:a00:1::1",
    ):
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        with pytest.raises(OSError):
            storage.make_public_socket(
                (family, socket.SOCK_STREAM, 6, "", (address, 443))
            )
    assert storage.address_is_public("2606:4700:4700::1111")
    sock = storage.make_public_socket(
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
    )
    sock.close()
    # Compatible storage is addressed by path, and AWS by its default
    assert fs.config_kwargs["s3"] == {"addressing_style": "path"}
    aws = storage.get_s3_fs("key", "secret", region="eu-west-1")
    assert "s3" not in aws.config_kwargs
    assert aws.client_kwargs == {"region_name": "eu-west-1"}
