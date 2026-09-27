"""Routes for external storage connected to accounts and used by projects."""

import logging
import re
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

import app.projects
from app import storage, users
from app.api.deps import CurrentUser, CurrentUserOptional, SessionDep
from app.models import (
    Account,
    Project,
    ProjectStorageHistory,
    StorageResource,
    User,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

HF_BUCKET_RE = re.compile(r"^[\w.-]{2,96}/[\w.-]{2,96}$")


class StorageResourcePublic(BaseModel):
    name: str
    kind: str
    bucket: str
    created: datetime
    connected_by: str


class StorageResourcePost(BaseModel):
    name: str = Field(
        min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    kind: str = Field(pattern=r"^hf-bucket$")
    # For HF buckets, ``{namespace}/{bucket_name}``
    bucket: str


def to_public(resource: StorageResource) -> StorageResourcePublic:
    return StorageResourcePublic(
        name=resource.name,
        kind=resource.kind,
        bucket=resource.bucket,
        created=resource.created,
        connected_by=resource.credential_user.account.name,
    )


def get_storage_account(
    session: Session, current_user: User, account_name: str, manage: bool
) -> Account:
    """Get an account whose storage the current user can see or manage.

    That's the user's own account, or an org they're a member of, where
    managing storage requires being an owner or admin.
    """
    account = session.exec(
        select(Account).where(Account.name == account_name.lower())
    ).first()
    if account is None:
        raise HTTPException(404, f"Account '{account_name}' not found")
    if account.user_id == current_user.id:
        return account
    for membership in current_user.org_memberships:
        if membership.org_id == account.org_id and account.org_id is not None:
            if manage and membership.role_name not in ["owner", "admin"]:
                break
            return account
    raise HTTPException(403, "Not allowed to manage this account's storage")


@router.get("/accounts/{account_name}/storage")
def get_account_storage(
    account_name: str, session: SessionDep, current_user: CurrentUser
) -> list[StorageResourcePublic]:
    account = get_storage_account(
        session, current_user, account_name, manage=False
    )
    resources = session.exec(
        select(StorageResource)
        .where(StorageResource.owner_account_id == account.id)
        .order_by(StorageResource.name)
    ).all()
    return [to_public(r) for r in resources]


@router.post("/accounts/{account_name}/storage")
def post_account_storage(
    account_name: str,
    req: StorageResourcePost,
    session: SessionDep,
    current_user: CurrentUser,
) -> StorageResourcePublic:
    """Connect storage to an account with the current user's credential.

    For HF buckets, the bucket is created if it doesn't exist, and the
    credential is checked by requesting an upload token for it.
    """
    from huggingface_hub import create_bucket

    account = get_storage_account(
        session, current_user, account_name, manage=True
    )
    if not HF_BUCKET_RE.match(req.bucket):
        raise HTTPException(422, "Bucket must be like 'namespace/name'")
    existing = session.exec(
        select(StorageResource).where(
            StorageResource.owner_account_id == account.id,
            StorageResource.name == req.name,
        )
    ).first()
    if existing is not None:
        raise HTTPException(409, f"Storage '{req.name}' already exists")
    token = users.get_huggingface_token(session=session, user=current_user)
    try:
        create_bucket(req.bucket, private=True, exist_ok=True, token=token)
    except Exception as e:
        logger.info(f"Failed to create HF bucket {req.bucket}: {e}")
        raise HTTPException(
            400, f"Couldn't create or access bucket '{req.bucket}'"
        )
    resource = StorageResource(
        owner_account_id=account.id,
        name=req.name,
        kind=req.kind,
        bucket=req.bucket,
        credential_user_id=current_user.id,
    )
    resource.credential_user = current_user
    try:
        storage.get_xet_token(
            storage.get_resource_storage(session, resource), "write"
        )
    except Exception as e:
        logger.info(f"No write access to HF bucket {req.bucket}: {e}")
        raise HTTPException(
            400, f"Your Hugging Face account can't write to '{req.bucket}'"
        )
    session.add(resource)
    session.commit()
    session.refresh(resource)
    return to_public(resource)


@router.delete("/accounts/{account_name}/storage/{storage_name}")
def delete_account_storage(
    account_name: str,
    storage_name: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    """Disconnect storage from an account.

    Nothing is deleted from the storage itself. Storage any project has
    used can't be disconnected, since those projects may still need to read
    objects from it.
    """
    account = get_storage_account(
        session, current_user, account_name, manage=True
    )
    resource = session.exec(
        select(StorageResource).where(
            StorageResource.owner_account_id == account.id,
            StorageResource.name == storage_name,
        )
    ).first()
    if resource is None:
        raise HTTPException(404, f"Storage '{storage_name}' not found")
    used = session.exec(
        select(ProjectStorageHistory).where(
            ProjectStorageHistory.storage_resource_id == resource.id
        )
    ).first()
    if used is not None:
        raise HTTPException(
            409,
            "This storage has been used by a project, so it's still needed",
        )
    session.delete(resource)
    session.commit()


class ProjectStorageSettings(BaseModel):
    # Where new DVC objects go; null means the hub's own storage
    dvc: StorageResourcePublic | None
    # Other storage the project's objects may be in
    previous: list[StorageResourcePublic]


class ProjectStoragePut(BaseModel):
    # The name of a storage resource of the project owner's account, or null
    # for the hub's own storage
    dvc_storage_name: str | None


def get_project_storage_settings(project: Project) -> ProjectStorageSettings:
    return ProjectStorageSettings(
        dvc=(
            to_public(project.dvc_storage)
            if project.dvc_storage is not None
            else None
        ),
        previous=[
            to_public(r.storage_resource)
            for r in sorted(
                project.storage_history,
                key=lambda r: r.first_used,
                reverse=True,
            )
            if r.storage_resource_id != project.dvc_storage_id
        ],
    )


@router.get("/projects/{owner_name}/{project_name}/storage")
def get_project_storage(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
) -> ProjectStorageSettings:
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    return get_project_storage_settings(project)


@router.put("/projects/{owner_name}/{project_name}/storage")
def put_project_storage(
    owner_name: str,
    project_name: str,
    req: ProjectStoragePut,
    session: SessionDep,
    current_user: CurrentUser,
) -> ProjectStorageSettings:
    """Change where a project's new DVC objects go.

    Existing objects aren't moved. Reads fall back through every storage the
    project has used, so nothing needs to move for pulls to keep working.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="owner",
    )
    if req.dvc_storage_name is None:
        project.dvc_storage_id = None
        project.dvc_storage = None
    else:
        resource = session.exec(
            select(StorageResource).where(
                StorageResource.owner_account_id == project.owner_account_id,
                StorageResource.name == req.dvc_storage_name,
            )
        ).first()
        if resource is None:
            raise HTTPException(
                404,
                f"Storage '{req.dvc_storage_name}' not found for "
                f"{project.owner_account_name}",
            )
        project.dvc_storage = resource
        if not any(
            r.storage_resource_id == resource.id
            for r in project.storage_history
        ):
            session.add(
                ProjectStorageHistory(
                    project_id=project.id, storage_resource_id=resource.id
                )
            )
    session.add(project)
    session.commit()
    session.refresh(project)
    return get_project_storage_settings(project)
