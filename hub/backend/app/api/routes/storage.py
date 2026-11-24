"""Routes for external storage connected to accounts and used by projects."""

import logging
import re
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

import app.projects
import app.tasks
from app import mixpanel, storage, users
from app.api.deps import CurrentUser, CurrentUserOptional, SessionDep
from app.models import (
    Account,
    Project,
    ProjectStorageHistory,
    StorageResource,
    StorageUsage,
    User,
)
from app.subscriptions import get_account_storage_limit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

HF_BUCKET_RE = re.compile(r"^[\w.-]{2,96}/[\w.-]{2,96}$")


class StorageResourcePublic(BaseModel):
    id: uuid.UUID
    # Only for storage shared by an account's projects
    name: str | None
    kind: str
    bucket: str
    # Whether it holds one project, e.g., an HF bucket of its own
    dedicated: bool
    created: datetime
    connected_by: str
    # Which account on the service, e.g., a Box login, since someone can
    # connect several
    service_account: str | None = None


def to_public(resource: StorageResource) -> StorageResourcePublic:
    credential = resource.credential
    service_account = None
    if credential is not None:
        metadata = credential.metadata_json or {}
        service_account = (
            metadata.get("login") or credential.provider_account_id
        )
    return StorageResourcePublic(
        id=resource.id,
        name=resource.name,
        kind=resource.kind,
        bucket=resource.bucket,
        dedicated=resource.project_id is not None,
        created=resource.created,
        connected_by=resource.credential_user.account.name,
        service_account=service_account,
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
    # Storage dedicated to a project is only listed for that project
    resources = session.exec(
        select(StorageResource)
        .where(
            StorageResource.owner_account_id == account.id,
            StorageResource.project_id.is_(None),  # type: ignore[union-attr]
        )
        .order_by(StorageResource.name)
    ).all()
    return [to_public(r) for r in resources]


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
            "Storage used by a project can't be removed",
        )
    session.delete(resource)
    session.commit()


class ProjectStorageSettings(BaseModel):
    # Where new DVC objects go; null means the hub's own storage
    dvc: StorageResourcePublic | None
    # Other storage the project's objects may be in
    previous: list[StorageResourcePublic]


class CredentialStoragePublic(BaseModel):
    """Storage reached with the current user's account on a service."""

    id: uuid.UUID
    kind: str
    # For HF, the bucket, and for Box, the ID of the ``Calkit`` folder
    bucket: str
    dedicated: bool
    owner: str
    # Every project that has used it, as ``{owner}/{name}``
    projects: list[str]


@router.get("/user/{provider}/storage")
def get_user_service_storage(
    provider: Literal["huggingface", "box"],
    session: SessionDep,
    current_user: CurrentUser,
    label: str = "default",
) -> list[CredentialStoragePublic]:
    """Get the storage reached with one of the current user's connections to
    a service, e.g., HF, which disconnecting it would make unreachable.
    """
    credential = users.get_external_credential(
        session=session, user=current_user, provider=provider, label=label
    )
    if credential is None:
        return []
    return [
        CredentialStoragePublic(
            id=r.id,
            kind=r.kind,
            bucket=r.bucket,
            dedicated=r.project_id is not None,
            owner=r.owner_account.name,
            projects=[
                f"{p.owner_account_name}/{p.name}"
                for p in storage.get_resource_projects(session, r)
            ],
        )
        for r in storage.get_credential_resources(session, credential.id)
    ]


class StorageTransferStatus(BaseModel):
    # "running", "failed", or null if there's no transfer
    status: str | None
    error: str | None = None
    # Where it's from, e.g., "huggingface"
    provider: str | None = None


@router.get("/user/storage-transfer")
def get_user_storage_transfer(
    current_user: CurrentUser,
) -> StorageTransferStatus:
    """Get the status of moving the storage reached with one of the current
    user's accounts on a service to the hub's own storage.
    """
    status, error, provider = app.tasks.get_storage_transfer_status(
        current_user.id
    )
    return StorageTransferStatus(status=status, error=error, provider=provider)


class ProjectStoragePut(BaseModel):
    # The ID of storage the project owner's account shares among its
    # projects, or that's dedicated to this one, or null for the hub's own
    # storage
    dvc_storage_id: uuid.UUID | None


class ProjectHfBucketPost(BaseModel):
    # ``{namespace}/{bucket_name}``, where the namespace is the user's HF
    # username or one of their HF orgs
    bucket: str
    # Which of the user's HF connections, if they have several
    label: str = "default"


def is_transferring(user_id: uuid.UUID, provider: str) -> bool:
    """Whether storage reached with a user's account on a service, e.g.,
    ``"huggingface"``, is being moved to the hub's own storage.
    """
    status, _, transferring = app.tasks.get_storage_transfer_status(user_id)
    return status == "running" and transferring == provider


def set_project_storage(
    session: Session, project: Project, resource: StorageResource | None
) -> None:
    """Send a project's new DVC objects to storage, keeping a record of every
    storage it has used so reads can fall back through them.

    For Box, the project's folder there is claimed first, so it can't be
    one holding another project's files.
    """
    if resource is not None and resource.kind == "box-folder":
        try:
            storage.claim_box_project_folder(
                storage.get_resource_storage(session, resource), project
            )
        except storage.BoxFolderTakenError as e:
            raise HTTPException(
                409, f"{e}; rename or move it in Box, then try again"
            )
        except HTTPException:
            raise
        except Exception:
            logger.exception("Failed to claim Box folder")
            raise HTTPException(502, "Couldn't reach Box")
    project.dvc_storage = resource
    project.dvc_storage_id = resource.id if resource is not None else None
    if resource is not None and not any(
        r.storage_resource_id == resource.id for r in project.storage_history
    ):
        session.add(
            ProjectStorageHistory(
                project_id=project.id, storage_resource_id=resource.id
            )
        )
    session.add(project)
    session.commit()
    session.refresh(project)


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


class ProjectStorageUsage(BaseModel):
    # In the hub's own storage, which is what counts toward plan limits
    project_used_gb: float
    # Only for those who can manage the owner account's storage
    account: StorageUsage | None = None


@router.get("/projects/{owner_name}/{project_name}/storage/usage")
def get_project_storage_usage(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
) -> ProjectStorageUsage:
    """Get how much of the hub's storage a project and its owner use.

    It's separate from the project's storage settings since it's slow to
    measure.
    """
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="read",
    )
    owner_name = project.owner_account_name
    usage = ProjectStorageUsage(
        project_used_gb=storage.get_storage_usage(
            owner_name, project_name=project.name
        )
    )
    if current_user is None:
        return usage
    try:
        account = get_storage_account(
            session, current_user, owner_name, manage=True
        )
    except HTTPException:
        return usage
    usage.account = StorageUsage(
        limit_gb=get_account_storage_limit(account),
        used_gb=storage.get_storage_usage(owner_name),
    )
    return usage


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
    resource = None
    if req.dvc_storage_id is not None:
        resource = session.get(StorageResource, req.dvc_storage_id)
        if (
            resource is None
            or resource.owner_account_id != project.owner_account_id
            or resource.project_id not in (None, project.id)
        ):
            raise HTTPException(404, "Storage not found")
        # It's about to be removed
        if is_transferring(
            resource.credential_user_id,
            storage.STORAGE_KIND_PROVIDERS.get(resource.kind, ""),
        ):
            raise HTTPException(
                409, "Storage being transferred to Calkit Hub storage"
            )
    from_kind = (
        project.dvc_storage.kind if project.dvc_storage is not None else "hub"
    )
    set_project_storage(session, project, resource)
    mixpanel.user_changed_project_storage(
        current_user,
        project.owner_account_name,
        project.name,
        from_kind=from_kind,
        to_kind=resource.kind if resource is not None else "hub",
    )
    return get_project_storage_settings(project)


BOX_FOLDER_NAME = "Calkit"


@router.post("/projects/{owner_name}/{project_name}/storage/box-folder")
def post_project_box_folder(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUser,
    label: str = "default",
) -> ProjectStorageSettings:
    """Send a project's new DVC objects to the current user's Box, through
    the connection under ``label``, if they've connected several.

    They go in the ``Calkit`` folder at the root of the user's Box, which is
    created if it isn't there, under ``{owner}/{project}``. The folder is
    shared by every project the owner account has there, so it's kept as
    storage the account's projects can select.
    """
    from calkit.box import BoxFileSystem

    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="owner",
    )
    # Its storage is about to be removed, along with the account
    if is_transferring(current_user.id, "box"):
        raise HTTPException(
            409, "Box storage being transferred to Calkit Hub storage"
        )
    token = users.get_box_token(
        session=session, user=current_user, label=label
    )
    credential = users.get_external_credential(
        session=session, user=current_user, provider="box", label=label
    )
    assert credential is not None
    resource = session.exec(
        select(StorageResource).where(
            StorageResource.owner_account_id == project.owner_account_id,
            StorageResource.credential_id == credential.id,
        )
    ).first()
    created = resource is None
    if resource is None:
        account = get_storage_account(
            session, current_user, project.owner_account_name, manage=True
        )
        # Reused if it's there, e.g., from an earlier connection, so the
        # objects in it can be read again
        try:
            folder_id = BoxFileSystem(token, "0").get_folder_id(
                BOX_FOLDER_NAME, create=True
            )
        except Exception as e:
            logger.info(f"Failed to create Box folder: {e}")
            raise HTTPException(
                502, f"Couldn't create '{BOX_FOLDER_NAME}' folder in Box"
            )
        taken = set(
            session.exec(
                select(StorageResource.name).where(
                    StorageResource.owner_account_id == account.id
                )
            ).all()
        )
        name = "box"
        n = 2
        while name in taken:
            name = f"box-{n}"
            n += 1
        resource = StorageResource(
            owner_account_id=account.id,
            name=name,
            kind="box-folder",
            bucket=folder_id,
            credential_user_id=current_user.id,
            credential_id=credential.id,
        )
        resource.credential = credential
        resource.credential_user = current_user
        session.add(resource)
    from_kind = (
        project.dvc_storage.kind if project.dvc_storage is not None else "hub"
    )
    set_project_storage(session, project, resource)
    if created:
        mixpanel.user_created_project_storage(
            current_user,
            project.owner_account_name,
            project.name,
            kind="box-folder",
            is_public=project.is_public,
            in_org=project.owner_account.org_id is not None,
        )
    mixpanel.user_changed_project_storage(
        current_user,
        project.owner_account_name,
        project.name,
        from_kind=from_kind,
        to_kind="box-folder",
    )
    return get_project_storage_settings(project)


@router.post("/projects/{owner_name}/{project_name}/storage/hf-bucket")
def post_project_hf_bucket(
    owner_name: str,
    project_name: str,
    req: ProjectHfBucketPost,
    session: SessionDep,
    current_user: CurrentUser,
) -> ProjectStorageSettings:
    """Create an HF bucket dedicated to a project, with the current user's
    HF account, and send the project's new DVC objects there.

    The bucket is public if the project is, and its visibility follows the
    project's from then on.
    """
    from huggingface_hub import create_bucket
    from huggingface_hub.errors import HfHubHTTPError

    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level="owner",
    )
    if not HF_BUCKET_RE.match(req.bucket):
        raise HTTPException(422, "Bucket must be like 'namespace/name'")
    # Its storage is about to be removed, along with the account
    if is_transferring(current_user.id, "huggingface"):
        raise HTTPException(
            409, "Hugging Face storage being transferred to Calkit Hub storage"
        )
    token = users.get_huggingface_token(
        session=session, user=current_user, label=req.label
    )
    credential = users.get_external_credential(
        session=session,
        user=current_user,
        provider="huggingface",
        label=req.label,
    )
    assert credential is not None
    try:
        create_bucket(req.bucket, private=not project.is_public, token=token)
    except HfHubHTTPError as e:
        status_code = (
            e.response.status_code if e.response is not None else None
        )
        logger.info(f"Failed to create HF bucket {req.bucket}: {e}")
        if status_code == 409:
            raise HTTPException(409, f"Bucket '{req.bucket}' already exists")
        raise HTTPException(400, f"Couldn't create bucket '{req.bucket}'")
    resource = StorageResource(
        owner_account_id=project.owner_account_id,
        project_id=project.id,
        kind="hf-bucket",
        bucket=req.bucket,
        credential_user_id=current_user.id,
        credential_id=credential.id,
    )
    resource.credential_user = current_user
    resource.credential = credential
    session.add(resource)
    from_kind = (
        project.dvc_storage.kind if project.dvc_storage is not None else "hub"
    )
    set_project_storage(session, project, resource)
    hf_username = credential.provider_account_id
    mixpanel.user_created_project_storage(
        current_user,
        project.owner_account_name,
        project.name,
        kind="hf-bucket",
        is_public=project.is_public,
        in_org=req.bucket.split("/")[0] != hf_username,
    )
    mixpanel.user_changed_project_storage(
        current_user,
        project.owner_account_name,
        project.name,
        from_kind=from_kind,
        to_kind="hf-bucket",
    )
    return get_project_storage_settings(project)
