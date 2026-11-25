"""Tests for app.api.routes.storage endpoints."""

import uuid
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import storage, users
from app.models import Project, StorageResource
from app.tests import authentication_token_from_email, random_email


def test_storage_resources_and_project_storage(
    client: TestClient, db: Session
) -> None:
    owner_email = random_email()
    owner_headers = authentication_token_from_email(
        client=client, email=owner_email, db=db
    )
    owner = users.get_user_by_email(session=db, email=owner_email)
    assert owner is not None
    account_name = owner.account.name
    other_headers = authentication_token_from_email(
        client=client, email=random_email(), db=db
    )
    base = f"/accounts/{account_name}/storage"
    assert client.get(base, headers=owner_headers).json() == []
    # Other users can't see the account's storage
    response = client.get(base, headers=other_headers)
    assert response.status_code == 403
    # Storage shared by the account's projects, e.g., S3 later, which can't
    # be added through the API yet
    for name in ("hf", "unused"):
        db.add(
            StorageResource(
                owner_account_id=owner.account.id,
                name=name,
                kind="hf-bucket",
                bucket="someone/calkit",
                credential_user_id=owner.id,
            )
        )
    db.commit()
    response = client.post(
        base,
        headers=owner_headers,
        json={"name": "hf2", "kind": "hf-bucket", "bucket": "someone/calkit"},
    )
    assert response.status_code == 405
    listed = client.get(base, headers=owner_headers).json()
    assert [r["name"] for r in listed] == ["hf", "unused"]
    assert not any(r["dedicated"] for r in listed)
    hf_id = listed[0]["id"]
    # Switching a project's storage
    project = Project(
        name=f"storage-{uuid.uuid4().hex[:8]}",
        title="Storage project",
        git_repo_url="https://github.com/someone/storage",
        owner_account_id=owner.account.id,
        owner_account=owner.account,
        is_public=True,
    )
    db.add(project)
    db.commit()
    project_url = f"/projects/{account_name}/{project.name}/storage"
    response = client.get(project_url, headers=owner_headers)
    assert response.json() == {"dvc": None, "previous": []}
    response = client.put(
        project_url, headers=other_headers, json={"dvc_storage_id": hf_id}
    )
    assert response.status_code in (403, 404)
    response = client.put(
        project_url,
        headers=owner_headers,
        json={"dvc_storage_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404
    response = client.put(
        project_url, headers=owner_headers, json={"dvc_storage_id": hf_id}
    )
    assert response.status_code == 200
    assert response.json()["dvc"]["name"] == "hf"
    assert response.json()["previous"] == []
    # Switching back keeps the old storage around for reads
    response = client.put(
        project_url, headers=owner_headers, json={"dvc_storage_id": None}
    )
    assert response.json()["dvc"] is None
    assert [r["name"] for r in response.json()["previous"]] == ["hf"]
    # A bucket of its own, made with the owner's HF account, public like the
    # project, which other users can't make
    bucket_url = f"{project_url}/hf-bucket"
    bucket = {"bucket": f"someone/{project.name}"}
    response = client.post(bucket_url, headers=other_headers, json=bucket)
    assert response.status_code in (403, 404)
    with (
        patch("app.users.get_huggingface_token", return_value="hf-token"),
        patch("huggingface_hub.create_bucket") as create_bucket,
        patch("app.api.routes.storage.mixpanel") as mp,
    ):
        response = client.post(
            bucket_url, headers=owner_headers, json={"bucket": "no-namespace"}
        )
        assert response.status_code == 422
        response = client.post(bucket_url, headers=owner_headers, json=bucket)
        assert response.status_code == 200, response.text
        create_bucket.assert_called_once_with(
            bucket["bucket"], private=False, token="hf-token"
        )
        # So we know how much it's used
        created = mp.user_created_project_storage.call_args.kwargs
        assert created["kind"] == "hf-bucket"
        assert created["is_public"] is True
        changed = mp.user_changed_project_storage.call_args.kwargs
        assert (changed["from_kind"], changed["to_kind"]) == (
            "hub",
            "hf-bucket",
        )
        # Someone else's bucket, or one made by hand, isn't taken over
        from huggingface_hub.errors import HfHubHTTPError

        create_bucket.side_effect = HfHubHTTPError(
            "exists", response=MagicMock(status_code=409)
        )
        response = client.post(
            bucket_url, headers=owner_headers, json={"bucket": "someone/taken"}
        )
        assert response.status_code == 409
    dedicated = client.get(project_url, headers=owner_headers).json()
    assert dedicated["dvc"]["bucket"] == bucket["bucket"]
    assert dedicated["dvc"]["dedicated"] is True
    assert dedicated["dvc"]["name"] is None
    assert [r["name"] for r in dedicated["previous"]] == ["hf"]
    # It's only listed for its project, not the account
    listed = client.get(base, headers=owner_headers).json()
    assert [r["name"] for r in listed] == ["hf", "unused"]
    # Another project can't use it
    other_project = Project(
        name=f"storage-{uuid.uuid4().hex[:8]}",
        title="Other storage project",
        git_repo_url="https://github.com/someone/other",
        owner_account_id=owner.account.id,
        owner_account=owner.account,
        is_public=True,
    )
    db.add(other_project)
    db.commit()
    response = client.put(
        f"/projects/{account_name}/{other_project.name}/storage",
        headers=owner_headers,
        json={"dvc_storage_id": dedicated["dvc"]["id"]},
    )
    assert response.status_code == 404
    # Storage a project has used can't be disconnected, but unused can
    response = client.delete(f"{base}/hf", headers=owner_headers)
    assert response.status_code == 409
    response = client.delete(f"{base}/unused", headers=owner_headers)
    assert response.status_code == 200
    response = client.delete(f"{base}/unused", headers=owner_headers)
    assert response.status_code == 404

    # How much of the hub's storage the project and its owner use, with the
    # account's only for those who manage it
    def get_storage_usage(owner_name, project_name=None):
        assert owner_name == account_name
        return 0.25 if project_name == project.name else 3.0

    with patch(
        "app.api.routes.storage.storage.get_storage_usage",
        side_effect=get_storage_usage,
    ):
        response = client.get(f"{project_url}/usage", headers=owner_headers)
        assert response.status_code == 200
        db.refresh(owner)
        limit = owner.subscription.storage_limit if owner.subscription else 10
        assert response.json() == {
            "project_used_gb": 0.25,
            "account": {"used_gb": 3.0, "limit_gb": limit},
        }
        response = client.get(f"{project_url}/usage", headers=other_headers)
        assert response.json() == {"project_used_gb": 0.25, "account": None}
    # What disconnecting HF would affect: everything connected with it, and
    # the projects that have used each
    response = client.get("/user/huggingface/storage", headers=owner_headers)
    assert response.status_code == 200
    by_bucket = {r["bucket"]: r for r in response.json()}
    assert set(by_bucket) == {"someone/calkit", bucket["bucket"]}
    assert by_bucket[bucket["bucket"]]["dedicated"] is True
    assert by_bucket[bucket["bucket"]]["projects"] == [
        f"{account_name}/{project.name}"
    ]
    response = client.get("/user/huggingface/storage", headers=other_headers)
    assert response.json() == []
    # While it's being transferred to the hub's own storage, it can't be
    # selected again, and no more can be made with that HF account
    response = client.get("/user/storage-transfer", headers=owner_headers)
    assert response.json() == {
        "status": None,
        "error": None,
        "provider": None,
        "label": None,
    }
    with patch(
        "app.tasks.get_storage_transfer_status",
        return_value=("running", None, "huggingface", "default"),
    ):
        response = client.get("/user/storage-transfer", headers=owner_headers)
        assert response.json() == {
            "status": "running",
            "error": None,
            "provider": "huggingface",
            "label": None,
        }
        response = client.put(
            project_url, headers=owner_headers, json={"dvc_storage_id": hf_id}
        )
        assert response.status_code == 409
        response = client.post(bucket_url, headers=owner_headers, json=bucket)
        assert response.status_code == 409


def test_project_box_folder(client: TestClient, db: Session) -> None:
    import json
    from datetime import timedelta

    from app.core import utcnow

    email = random_email()
    headers = authentication_token_from_email(
        client=client, email=email, db=db
    )
    user = users.get_user_by_email(session=db, email=email)
    assert user is not None
    project = Project(
        name=f"box-{uuid.uuid4().hex[:8]}",
        title="Box project",
        git_repo_url="https://github.com/someone/box",
        owner_account_id=user.account.id,
        owner_account=user.account,
    )
    db.add(project)
    db.commit()
    url = f"/projects/{user.account.name}/{project.name}/storage/box-folder"
    # Box has to be connected
    assert client.post(url, headers=headers).status_code == 401
    users.save_external_credential(
        session=db,
        user=user,
        provider="box",
        secret_payload=json.dumps(
            {"access_token": "box", "refresh_token": "r"}
        ),
        expires=utcnow() + timedelta(hours=1),
    )
    # Another resource has the name it would get
    db.add(
        StorageResource(
            owner_account_id=user.account.id,
            name="box",
            kind="hf-bucket",
            bucket="someone/calkit",
            credential_user_id=user.id,
        )
    )
    db.commit()
    with patch(
        "calkit.box.BoxFileSystem.get_folder_id",
        side_effect=OSError("Box down"),
    ):
        assert client.post(url, headers=headers).status_code == 502
    # A project's folder in Box holding another project's files isn't
    # taken over
    with (
        patch("calkit.box.BoxFileSystem.get_folder_id", return_value="123"),
        patch(
            "app.api.routes.storage.storage.claim_project_folder",
            side_effect=storage.FolderTakenError("Calkit/a/b"),
        ),
    ):
        response = client.post(url, headers=headers)
        assert response.status_code == 409
        assert "Calkit/a/b" in response.json()["detail"]
    # The Calkit folder is made, or reused, and the project's new objects go
    # there
    with (
        patch(
            "calkit.box.BoxFileSystem.get_folder_id", return_value="123"
        ) as get_folder_id,
        patch("app.api.routes.storage.storage.claim_project_folder") as claim,
    ):
        response = client.post(url, headers=headers)
        assert response.status_code == 200
        assert get_folder_id.call_args.args == ("Calkit",)
        assert get_folder_id.call_args.kwargs == {"create": True}
        dvc = response.json()["dvc"]
        assert dvc["kind"] == "box-folder"
        assert dvc["bucket"] == "123"
        assert dvc["name"] == "box-2"
        assert dvc["dedicated"] is False
        # Then reused, by this project and the account's others
        response = client.post(url, headers=headers)
        assert response.json()["dvc"]["id"] == dvc["id"]
        get_folder_id.assert_called_once()
        # The project's folder is checked each time
        assert claim.call_count == 2
    listed = client.get(
        f"/accounts/{user.account.name}/storage", headers=headers
    ).json()
    assert dvc["id"] in [r["id"] for r in listed]
    # It's what disconnecting Box would strand, not HF
    response = client.get("/user/box/storage", headers=headers)
    assert [
        (r["kind"], r["bucket"], r["projects"]) for r in response.json()
    ] == [("box-folder", "123", [f"{user.account.name}/{project.name}"])]
    response = client.get("/user/huggingface/storage", headers=headers)
    assert [r["kind"] for r in response.json()] == ["hf-bucket"]
    assert (
        client.get("/user/zenodo/storage", headers=headers).status_code == 422
    )


def test_project_s3_bucket(client: TestClient, db: Session) -> None:
    from app.config import settings

    email = random_email()
    headers = authentication_token_from_email(
        client=client, email=email, db=db
    )
    user = users.get_user_by_email(session=db, email=email)
    assert user is not None
    projects = []
    for _ in range(3):
        project = Project(
            name=f"s3-{uuid.uuid4().hex[:8]}",
            title="S3 project",
            git_repo_url="https://github.com/someone/s3",
            owner_account_id=user.account.id,
            owner_account=user.account,
        )
        db.add(project)
        projects.append(project)
    db.commit()
    owner = user.account.name
    # The dev MinIO stands in for someone's S3-compatible storage, e.g., OSN
    endpoint_url = settings.OBJECT_STORAGE_ENDPOINT_URL
    bucket_name = f"s3-route-{uuid.uuid4().hex[:8]}"
    storage.get_s3_fs(
        str(settings.OBJECT_STORAGE_KEY),
        str(settings.OBJECT_STORAGE_SECRET),
        endpoint_url=endpoint_url,
    ).mkdir(bucket_name)
    response = client.put(
        "/user/s3-connections/osn",
        headers=headers,
        json={
            "endpoint_url": endpoint_url,
            "access_key_id": settings.OBJECT_STORAGE_KEY,
            "secret_access_key": settings.OBJECT_STORAGE_SECRET,
        },
    )
    assert response.status_code == 200
    url = f"/projects/{owner}/{projects[0].name}/storage/s3-bucket"
    for body, status_code in (
        ({"connection": "nope", "url": f"s3://{bucket_name}"}, 404),
        ({"connection": "osn", "url": "s3://a"}, 422),
        ({"connection": "osn", "url": f"s3://{bucket_name}/../x"}, 422),
        ({"connection": "osn", "url": "s3://no-such-bucket-here/x"}, 404),
        ({"connection": "osn", "url": f"s3://{bucket_name}/{'x' * 300}"}, 422),
    ):
        response = client.post(url, headers=headers, json=body)
        assert response.status_code == status_code, response.text
    # Projects share a bucket, each in its own folder
    body = {"connection": "osn", "url": f"s3://{bucket_name}/calkit/"}
    response = client.post(url, headers=headers, json=body)
    assert response.status_code == 200, response.text
    dvc = response.json()["dvc"]
    assert response.json()["added"] == dvc
    assert dvc["kind"] == "s3-bucket"
    assert dvc["bucket"] == f"{bucket_name}/calkit"
    assert dvc["name"] == bucket_name
    assert dvc["connection"] == "osn"
    assert not dvc["dedicated"] and not dvc["read_only"]
    second = f"/projects/{owner}/{projects[1].name}/storage/s3-bucket"
    response = client.post(second, headers=headers, json=body)
    assert response.json()["dvc"]["id"] == dvc["id"]
    resource = db.get(StorageResource, uuid.UUID(dvc["id"]))
    assert resource is not None
    # Other storage signs for the connection's region, which can change
    assert resource.region is None
    target = storage.get_resource_storage(db, resource)
    for project in projects[:2]:
        marker = target.make_project_path(
            owner, project.name, storage.PROJECT_FILE
        )
        assert target.fs.cat_file(marker) == str(project.id).encode()
    # Keys that can only read make a source to read from, with new objects
    # going where they did
    third = f"/projects/{owner}/{projects[2].name}/storage/s3-bucket"
    shared = {
        "connection": "osn",
        "url": f"s3://{bucket_name}/shared",
        "dedicated": True,
    }
    with patch(
        "app.api.routes.storage.storage.claim_project_folder",
        side_effect=PermissionError,
    ):
        response = client.post(third, headers=headers, json=shared)
    assert response.status_code == 200, response.text
    assert response.json()["dvc"] is None
    read_only = response.json()["added"]
    assert read_only["read_only"] and read_only["dedicated"]
    assert response.json()["previous"] == [read_only]
    response = client.put(
        f"/projects/{owner}/{projects[2].name}/storage",
        headers=headers,
        json={"dvc_storage_id": read_only["id"]},
    )
    assert response.status_code == 409
    # Once the keys can write, adding the bucket again makes it writable
    response = client.post(third, headers=headers, json=shared)
    assert response.status_code == 200, response.text
    assert response.json()["dvc"]["id"] == read_only["id"]
    assert not response.json()["dvc"]["read_only"]
    # While one connection's storage is being transferred, it can't be
    # used, but another connection's can
    with patch(
        "app.tasks.get_storage_transfer_status",
        return_value=("running", None, "s3", "osn"),
    ):
        response = client.post(url, headers=headers, json=body)
        assert response.status_code == 409
        response = client.get("/user/storage-transfer", headers=headers)
        assert response.json()["label"] == "osn"
    with patch(
        "app.tasks.get_storage_transfer_status",
        return_value=("running", None, "s3", "aws"),
    ):
        response = client.post(url, headers=headers, json=body)
        assert response.status_code == 200
