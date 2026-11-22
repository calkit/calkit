"""Tests for app.api.routes.storage endpoints."""

import uuid
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import users
from app.models import Project
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
    # Other users can't see or add storage to the account
    response = client.get(base, headers=other_headers)
    assert response.status_code == 403
    post = {"name": "hf", "kind": "hf-bucket", "bucket": "someone/calkit"}
    response = client.post(base, headers=other_headers, json=post)
    assert response.status_code == 403
    # Hugging Face must be connected first
    response = client.post(base, headers=owner_headers, json=post)
    assert response.status_code == 401
    with (
        patch("app.users.get_huggingface_token", return_value="hf-token"),
        patch("huggingface_hub.create_bucket") as create_bucket,
        patch("app.storage.get_xet_token", return_value={}) as get_xet_token,
    ):
        for bad in [
            post | {"bucket": "no-namespace"},
            post | {"kind": "s3"},
            post | {"name": "Not Valid"},
        ]:
            response = client.post(base, headers=owner_headers, json=bad)
            assert response.status_code == 422
        response = client.post(base, headers=owner_headers, json=post)
        assert response.status_code == 200
        assert response.json()["name"] == "hf"
        assert response.json()["bucket"] == "someone/calkit"
        assert response.json()["connected_by"] == account_name
        create_bucket.assert_called_once_with(
            "someone/calkit", private=True, exist_ok=True, token="hf-token"
        )
        get_xet_token.assert_called_once()
        response = client.post(base, headers=owner_headers, json=post)
        assert response.status_code == 409
        # A bucket the account can't write to isn't connected
        get_xet_token.side_effect = Exception("403")
        response = client.post(
            base, headers=owner_headers, json=post | {"name": "other"}
        )
        assert response.status_code == 400
        get_xet_token.side_effect = None
        response = client.post(
            base, headers=owner_headers, json=post | {"name": "unused"}
        )
        assert response.status_code == 200
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
