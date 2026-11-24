"""Functionality for managing object storage."""

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import boto3
import cachetools
import gcsfs
import s3fs
from botocore.config import Config
from google.cloud import storage as gcs
from google.oauth2 import service_account as gcs_service_account

from app.config import settings

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlmodel import Session

    from app.models import Project, StorageResource

# Multipart/chunked upload configuration
MULTIPART_THRESHOLD_BYTES = 64 * 1024 * 1024  # 64 MB
MULTIPART_PART_SIZE_BYTES = 16 * 1024 * 1024  # 16 MB
CHUNKED_CHUNK_SIZE_BYTES = 16 * 1024 * 1024  # 16 MB
S3_MAX_PARTS = 10000  # S3 multipart upload limit
# Project DVC data is one kind of object this hub stores, kept under
# its own folder within the storage root so other kinds can be added
# alongside it without touching every deployment's config
DVC_DATA_DIR = "data"
STORAGE_USAGE_CACHE_TTL_SECONDS = 300
STORAGE_USAGE_CACHE_MAXSIZE = 2048

# In-process cache for owner-level storage usage reads. The type arguments
# are repeated on the constructor because it takes no argument they could
# be inferred from, which leaves them unsolved and unassignable.
_storage_usage_cache: cachetools.TTLCache[str, float] = cachetools.TTLCache[
    str, float
](
    maxsize=STORAGE_USAGE_CACHE_MAXSIZE,
    ttl=STORAGE_USAGE_CACHE_TTL_SECONDS,
)


def get_backend() -> Literal["s3", "gcs"]:
    """Get the configured storage backend for the current environment.

    For GCS, this is not the scheme of the prefix (gs://) but the backend type
    (gcs) used in code to interact with GCS.
    """
    return settings.object_storage_type


def upload_should_be_chunked(content_length: int | None) -> bool:
    """Determine if an upload should use multipart/chunked strategy."""
    return (
        content_length is not None
        and content_length >= MULTIPART_THRESHOLD_BYTES
    )


def get_upload_chunk_size(backend: Literal["s3", "gcs"] | None = None) -> int:
    """Get the chunk/part size for the specified backend in bytes."""
    if backend is None:
        backend = get_backend()
    return (
        MULTIPART_PART_SIZE_BYTES
        if backend == "s3"
        else CHUNKED_CHUNK_SIZE_BYTES
    )


def get_gcs_credentials() -> dict | None:
    """Get GCS credentials from environment."""
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    if creds_json:
        return json.loads(creds_json)
    return None


def get_gcs_client() -> gcs.Client:
    """Get a Google Cloud Storage client with credentials from environment."""
    creds_dict = get_gcs_credentials()
    if creds_dict:
        credentials = (
            gcs_service_account.Credentials.from_service_account_info(
                creds_dict
            )
        )
        return gcs.Client(credentials=credentials)
    return gcs.Client()


def get_storage_root() -> str:
    """Get the root under which this hub stores all of its objects."""
    return settings.OBJECT_STORAGE_PREFIX.rstrip("/")


def get_bucket_name() -> str:
    """Get the bucket name from the configured storage root."""
    root = get_storage_root()
    for scheme in ["gs://", "s3://"]:
        root = root.removeprefix(scheme)
    return root.split("/")[0]


def remove_gcs_content_type(fpath: str) -> None:
    client = get_gcs_client()
    # Derived from the configured prefix rather than the environment name,
    # so a self-hosted instance can use a bucket of its own naming
    bucket = client.bucket(get_bucket_name())
    blob = bucket.blob(fpath.removeprefix(f"gs://{bucket.name}/"))
    blob.content_type = None
    blob.patch()


def get_object_fs() -> s3fs.S3FileSystem | gcsfs.GCSFileSystem:
    # Without caching listings: the instance outlives a request, so a cached
    # listing would hide objects other workers have written since, and an
    # object that exists would be reported missing
    if settings.object_storage_type == "s3":
        # An unset endpoint URL means AWS S3 itself; unset credentials let
        # s3fs fall back to the standard AWS credential chain
        return s3fs.S3FileSystem(
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT_URL,
            key=settings.OBJECT_STORAGE_KEY,
            secret=settings.OBJECT_STORAGE_SECRET,
            use_listings_cache=False,
        )
    return gcsfs.GCSFileSystem(
        token=get_gcs_credentials(), use_listings_cache=False
    )


def get_data_prefix() -> str:
    """Get the prefix under which project DVC data is stored."""
    return f"{get_storage_root()}/{DVC_DATA_DIR}"


def get_data_prefix_for_owner(owner_name: str, lowercase: bool = True) -> str:
    prefix = f"{get_data_prefix()}/{owner_name}"
    return prefix.lower() if lowercase else prefix


def make_data_fpath(
    owner_name: str,
    project_name: str,
    idx: str,
    md5: str,
    legacy: bool = False,
) -> str:
    """Make a data file path for a given owner, project, index, and md5 hash.

    This matches the DVC path structure used for storing data files, i.e.,
    under the files/md5 subdirectory.

    The legacy flag allows generating paths in the old format
    (without 'files/md5/') for backward compatibility with existing data.
    New uploads should use the new format.
    """
    prefix = get_data_prefix_for_owner(owner_name, lowercase=not legacy)
    if legacy:
        return f"{prefix}/{project_name}/{idx}/{md5}"
    else:
        return f"{prefix}/{project_name.lower()}/files/md5/{idx}/{md5}"


def _replace_local_object_host(url: str) -> str:
    """Replace the local object storage host in a presigned URL with the
    externally reachable host for local development.
    """
    endpoint = settings.OBJECT_STORAGE_ENDPOINT_URL
    if settings.ENVIRONMENT == "local" and endpoint:
        return url.replace(endpoint, f"http://objects.{settings.DOMAIN}")
    return url


def _generate_multipart_urls(
    fpath: str,
    estimated_part_count: int,
    expires: int,
    fs: s3fs.S3FileSystem,
    content_type: str | None = None,
) -> dict:
    """Generate presigned URLs for S3 multipart upload.

    Returns a dict with:
    - bucket: bucket name
    - key: object key
    - upload_id: multipart upload ID
    - part_urls: list of presigned URLs for each part
    - complete_url: presigned URL to complete the upload
    - abort_url: presigned URL to abort the upload
    """
    # Parse bucket and key from fpath (e.g., "s3://bucket/path/to/object")
    if fpath.startswith("s3://"):
        bucket, _, key = fpath[5:].partition("/")
    else:
        raise ValueError(f"Invalid S3 path: {fpath}")
    s3_config = Config(
        signature_version="s3v4", s3={"addressing_style": "path"}
    )
    # Use an internal client for control-plane calls (create multipart upload)
    control_client: Any = boto3.client(
        "s3",
        endpoint_url=fs.endpoint_url,
        aws_access_key_id=fs.key,
        aws_secret_access_key=fs.secret,
        aws_session_token=fs.token,
        config=s3_config,
    )
    # Sign URLs for the externally reachable host to avoid host/signature
    # mismatch
    presign_endpoint = fs.endpoint_url
    if settings.ENVIRONMENT == "local":
        presign_endpoint = f"http://objects.{settings.DOMAIN}"
    presign_client: Any = boto3.client(
        "s3",
        endpoint_url=presign_endpoint,
        aws_access_key_id=fs.key,
        aws_secret_access_key=fs.secret,
        aws_session_token=fs.token,
        config=s3_config,
    )
    # Initiate multipart upload
    mpu = control_client.create_multipart_upload(
        Bucket=bucket,
        Key=key,
        **({"ContentType": content_type} if content_type else {}),
    )
    upload_id = mpu["UploadId"]
    # Generate presigned URLs for each part
    part_urls = []
    for part_number in range(1, estimated_part_count + 1):
        part_url = presign_client.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": bucket,
                "Key": key,
                "PartNumber": part_number,
                "UploadId": upload_id,
            },
            ExpiresIn=expires,
        )
        part_urls.append(part_url)
    # Generate presigned URL for completing the multipart upload
    complete_url = presign_client.generate_presigned_url(
        "complete_multipart_upload",
        Params={
            "Bucket": bucket,
            "Key": key,
            "UploadId": upload_id,
        },
        ExpiresIn=expires,
    )
    # Generate presigned URL for aborting the multipart upload
    abort_url = presign_client.generate_presigned_url(
        "abort_multipart_upload",
        Params={
            "Bucket": bucket,
            "Key": key,
            "UploadId": upload_id,
        },
        ExpiresIn=expires,
    )
    return {
        "bucket": bucket,
        "key": key,
        "upload_id": upload_id,
        "part_urls": part_urls,
        "complete_url": complete_url,
        "abort_url": abort_url,
    }


def get_object_url(
    fpath: str,
    fname: str | None = None,
    expires: int = 3600 * 24,
    fs: s3fs.S3FileSystem | gcsfs.GCSFileSystem | None = None,
    method: Literal["get", "put"] = "get",
    **kwargs,
) -> str:
    """Get a presigned URL for an object in object storage.

    For multipart/chunked uploads, use get_multipart_upload_info() instead.
    """
    if fs is None:
        fs = get_object_fs()
    # Standard presigned URL
    if isinstance(fs, s3fs.S3FileSystem):
        kws = {}
        if fname is not None:
            kws["ResponseContentDisposition"] = f"filename={fname}"
            if fname.endswith(".pdf"):
                kws["ResponseContentType"] = "application/pdf"
            elif fname.endswith(".html"):
                kws["ResponseContentType"] = "text/html"
            elif fname.endswith(".svg"):
                kws["ResponseContentType"] = "image/svg+xml"
        kws["client_method"] = f"{method}_object"
    elif isinstance(fs, gcsfs.GCSFileSystem):
        kws = {}
        if fname is not None:
            kws["response_disposition"] = f"filename={fname}"
            if fname.endswith(".pdf"):
                kws["response_type"] = "application/pdf"
            elif fname.endswith(".html"):
                kws["response_type"] = "text/html"
            elif fname.endswith(".svg"):
                kws["response_type"] = "image/svg+xml"
        kws["method"] = method.upper()
    else:
        raise ValueError("Unsupported filesystem type")
    signed_url = fs.sign(fpath, expiration=expires, **(kws | kwargs))
    if signed_url is None:
        raise RuntimeError("Failed to generate presigned URL")
    return _replace_local_object_host(signed_url)


HF_ENDPOINT = "https://huggingface.co"


@dataclass
class ProjectStorage:
    """Where a project's DVC objects live in one storage backend.

    A project's objects are under ``{data_prefix}/{owner}/{project}`` in
    ``fs``, or right under ``data_prefix`` if the storage is dedicated to
    the project.
    """

    backend: Literal["s3", "gcs", "hf"]
    fs: Any
    data_prefix: str
    resource: "StorageResource | None" = None
    # Owner's credential for the backend, when the hub holds one
    token: str | None = None
    bucket: str | None = field(init=False, default=None)
    is_dedicated: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        # Copied since worker threads can't load an expired resource through
        # the request's session
        if self.resource is not None:
            self.bucket = self.resource.bucket
            self.is_dedicated = self.resource.project_id is not None

    def make_project_path(
        self, owner_name: str, project_name: str, path: str = ""
    ) -> str:
        base = (
            self.data_prefix
            if self.is_dedicated
            else f"{self.data_prefix}/{owner_name.lower()}/{project_name.lower()}"
        )
        return f"{base}/{path}" if path else base

    def make_container_path(
        self, owner_name: str, project_name: str, path: str = ""
    ) -> str:
        """Make a path relative to the bucket or folder, e.g., for HF's
        batch API.
        """
        full = self.make_project_path(owner_name, project_name, path)
        return full.removeprefix(self.data_prefix).lstrip("/")


def get_internal_storage() -> ProjectStorage:
    """Get the hub's own object storage."""
    return ProjectStorage(
        backend=get_backend(),
        fs=get_object_fs(),
        data_prefix=get_data_prefix(),
    )


def get_resource_storage(
    session: "Session", resource: "StorageResource"
) -> ProjectStorage:
    """Get the storage for an external storage resource."""
    from huggingface_hub import HfFileSystem

    import app.users

    if resource.kind != "hf-bucket":
        raise ValueError(f"Unsupported storage kind: {resource.kind}")
    token = app.users.get_huggingface_token(
        session=session, user=resource.credential_user
    )
    # Skip fsspec's instance cache so listings aren't stale across requests
    fs = HfFileSystem(token=token, skip_instance_cache=True)
    return ProjectStorage(
        backend="hf",
        fs=fs,
        data_prefix=f"buckets/{resource.bucket}",
        resource=resource,
        token=token,
    )


class UnreachableStorageError(RuntimeError):
    """Storage a project uses can't be reached, e.g., because the account
    that connected it disconnected.
    """

    def __init__(self, resource: "StorageResource"):
        self.resource = resource
        super().__init__(f"Can't reach {resource.bucket}")


def get_project_storages(
    session: "Session", project: "Project", skip_unreachable: bool = True
) -> list[ProjectStorage]:
    """Get every storage a project's DVC objects may be in, for reading.

    Objects aren't moved when a project switches storage, so reads should
    fall back through these in order: the current storage, the project's
    previous storage resources, newest first, then the hub's own storage.
    Storage that can't be reached right now, e.g., because the account that
    connected it disconnected Hugging Face, is skipped so everything else
    stays readable, unless ``skip_unreachable`` is false, in which case it
    raises ``UnreachableStorageError``. New objects go to
    ``get_project_storage``.
    """
    from fastapi import HTTPException

    resources = []
    if project.dvc_storage is not None:
        resources.append(project.dvc_storage)
    for record in sorted(
        project.storage_history, key=lambda r: r.first_used, reverse=True
    ):
        if record.storage_resource_id != project.dvc_storage_id:
            resources.append(record.storage_resource)
    storages = []
    for resource in resources:
        try:
            storages.append(get_resource_storage(session, resource))
        except HTTPException as e:
            if not skip_unreachable:
                raise UnreachableStorageError(resource) from e
            logger.warning(
                f"Skipping unavailable storage {resource.name} "
                f"({resource.bucket}): {e.detail}"
            )
    internal = get_internal_storage()
    if project.dvc_storage is None:
        return [internal] + storages
    return storages + [internal]


def get_project_storage(
    session: "Session", project: "Project"
) -> ProjectStorage:
    """Get the storage new DVC objects for a project should go to.

    Unlike reads, this fails if that storage can't be reached, rather than
    putting objects somewhere else.
    """
    if project.dvc_storage is None:
        return get_internal_storage()
    return get_resource_storage(session, project.dvc_storage)


def find_project_object(
    session: "Session",
    project: "Project",
    path: str,
    storages: list[ProjectStorage] | None = None,
) -> tuple[ProjectStorage, str] | None:
    """Find which of a project's storages holds an object.

    Returns the storage and the object's full path in it, or ``None`` if no
    storage has it.
    """
    if storages is None:
        storages = get_project_storages(session, project)
    owner_name = project.owner_account_name
    for storage in storages:
        fpath = storage.make_project_path(owner_name, project.name, path)
        if storage.fs.exists(fpath):
            return storage, fpath
    return None


def set_project_bucket_visibility(
    session: "Session", project: "Project", is_public: bool
) -> int:
    """Make the buckets dedicated to a project public or private, returning
    how many there are.

    Raises ``UnreachableStorageError`` before changing any if one can't be
    reached.
    """
    from fastapi import HTTPException
    from huggingface_hub import HfApi
    from sqlmodel import select

    from app.models import StorageResource

    resources = session.exec(
        select(StorageResource).where(StorageResource.project_id == project.id)
    ).all()
    targets = []
    for resource in resources:
        try:
            targets.append(get_resource_storage(session, resource))
        except HTTPException as e:
            raise UnreachableStorageError(resource) from e
    for target in targets:
        assert target.bucket is not None
        HfApi(token=target.token).update_bucket_settings(
            target.bucket, private=not is_public
        )
    return len(targets)


# Objects at the root of a dedicated bucket
DVC_OBJECT_PATH_RE = re.compile(r"files/md5/[0-9a-f]{2}/[0-9a-f]{30}(\.dir)?")
MAX_STORAGE_CLOCK_SKEW = timedelta(minutes=5)


class UnsafeStorageDeleteError(RuntimeError):
    """Storage isn't safe to delete, since it changed outside Calkit."""

    def __init__(self, bucket: str):
        self.bucket = bucket
        super().__init__(f"Not deleting {bucket}: changed outside Calkit")


def check_safe_to_delete(target: ProjectStorage) -> None:
    """Check that a dedicated bucket is still the one the hub created, with
    only DVC objects in it, since HF identifies buckets by name.

    Raises ``UnsafeStorageDeleteError`` if not. A missing bucket is safe.
    """
    from huggingface_hub import HfApi
    from huggingface_hub.errors import BucketNotFoundError

    if not target.is_dedicated:
        return
    assert target.bucket is not None and target.resource is not None
    api = HfApi(token=target.token)
    try:
        info = api.bucket_info(target.bucket)
    except BucketNotFoundError:
        return
    # The hub saves its record right after creating the bucket
    recorded = target.resource.created
    if recorded.tzinfo is None:
        recorded = recorded.replace(tzinfo=timezone.utc)
    if info.created_at > recorded + MAX_STORAGE_CLOCK_SKEW:
        raise UnsafeStorageDeleteError(target.bucket)
    for item in api.list_bucket_tree(target.bucket, recursive=True):
        if item.type == "file" and not DVC_OBJECT_PATH_RE.fullmatch(item.path):
            raise UnsafeStorageDeleteError(target.bucket)


def delete_objects_from(
    target: ProjectStorage, owner_name: str, project_name: str
) -> None:
    """Delete a project's DVC objects from one storage.

    Storage dedicated to the project is deleted entirely, e.g., its HF
    bucket, and otherwise the project's folder is removed. Callers run
    ``check_safe_to_delete`` on everything they'll delete first.
    """
    from huggingface_hub import HfApi

    if target.is_dedicated:
        assert target.bucket is not None
        HfApi(token=target.token).delete_bucket(target.bucket, missing_ok=True)
        return
    base = target.make_project_path(owner_name, project_name)
    if target.backend == "hf":
        assert target.bucket is not None
        paths = [
            p.removeprefix(f"{target.data_prefix}/")
            for p in target.fs.find(base)
        ]
        if paths:
            HfApi(token=target.token).batch_bucket_files(
                target.bucket, delete=paths
            )
    elif target.fs.exists(base):
        target.fs.rm(base, recursive=True)


def delete_project_objects(session: "Session", project: "Project") -> None:
    """Delete a project's DVC objects from every storage it has used,
    including the hub's own.

    Raises ``UnreachableStorageError`` before deleting anything if any of
    that storage can't be reached, rather than leaving objects behind with
    no record of them, and ``UnsafeStorageDeleteError`` if any changed
    outside Calkit.
    """
    owner_name = project.owner_account_name
    targets = get_project_storages(session, project, skip_unreachable=False)
    for target in targets:
        check_safe_to_delete(target)
    for target in targets:
        delete_objects_from(target, owner_name, project.name)
    invalidate_storage_usage_cache(owner_name)


def get_credential_resources(
    session: "Session", user_id: Any
) -> list["StorageResource"]:
    """Get the storage reached with a user's credential, e.g., their HF
    account, whichever account owns it.
    """
    from sqlmodel import select

    from app.models import StorageResource

    return list(
        session.exec(
            select(StorageResource).where(
                StorageResource.credential_user_id == user_id
            )
        ).all()
    )


def get_resource_projects(
    session: "Session", resource: "StorageResource"
) -> list["Project"]:
    """Get every project that has used a storage resource."""
    from sqlmodel import select

    from app.models import Project, ProjectStorageHistory

    return list(
        session.exec(
            select(Project)
            .join(ProjectStorageHistory)
            .where(ProjectStorageHistory.storage_resource_id == resource.id)
        ).all()
    )


def get_project_object_sizes(
    target: ProjectStorage, owner_name: str, project_name: str
) -> dict[str, int]:
    """Get the size of each of a project's objects in a storage, by path in
    the project.
    """
    base = target.fs._strip_protocol(
        target.make_project_path(owner_name, project_name)
    )
    try:
        found = target.fs.find(base, detail=True)
    except FileNotFoundError:
        return {}
    return {
        fpath.removeprefix(f"{base}/"): int(info["size"])
        for fpath, info in found.items()
    }


def get_resource_gb_to_copy(
    session: "Session", resource: "StorageResource"
) -> dict[str, float]:
    """Get how many GB of each owner account's projects in a storage
    resource aren't in the hub's own storage yet.
    """
    source = get_resource_storage(session, resource)
    internal = get_internal_storage()
    needed: dict[str, float] = {}
    for project in get_resource_projects(session, resource):
        owner_name = project.owner_account_name
        copied = get_project_object_sizes(internal, owner_name, project.name)
        size = sum(
            size
            for path, size in get_project_object_sizes(
                source, owner_name, project.name
            ).items()
            if copied.get(path) != size
        )
        needed[owner_name] = needed.get(owner_name, 0) + size / 1e9
    return needed


def copy_resource_to_internal(
    session: "Session", resource: "StorageResource"
) -> int:
    """Copy every project's DVC objects in a storage resource into the hub's
    own storage. Objects already there are skipped, so it can be rerun.
    Returns how many objects were copied.
    """
    import tempfile

    internal = get_internal_storage()
    n_copied = 0
    for project in get_resource_projects(session, resource):
        owner_name = project.owner_account_name
        project_name = project.name
        source = get_resource_storage(session, resource)
        copied = get_project_object_sizes(internal, owner_name, project_name)
        for path, size in get_project_object_sizes(
            source, owner_name, project_name
        ).items():
            if copied.get(path) == size:
                continue
            # This can outlast a token, so get a current one for each object
            source = get_resource_storage(session, resource)
            dest = internal.make_project_path(owner_name, project_name, path)
            # Uploaded once complete, so a failed read can't leave part of it
            with tempfile.NamedTemporaryFile() as tmp:
                with source.fs.open(
                    source.make_project_path(owner_name, project_name, path),
                    "rb",
                ) as f_in:
                    shutil.copyfileobj(f_in, tmp)
                tmp.flush()
                if os.path.getsize(tmp.name) != size:
                    raise OSError(f"Incomplete read of {path}")
                internal.fs.put_file(tmp.name, dest)
            if settings.ENVIRONMENT != "local":
                remove_gcs_content_type(dest)
            n_copied += 1
        invalidate_storage_usage_cache(owner_name)
    return n_copied


def transfer_storage_and_disconnect(user_id: str) -> None:
    """Move the storage reached with a user's HF account into the hub's own
    storage, then disconnect the account. Run on the worker.

    Each resource's projects switch to the hub's own storage before its
    objects are copied, so nothing new lands there after the copy.
    """
    import uuid

    from sqlmodel import Session

    import app.mixpanel
    import app.users
    from app.db import engine
    from app.models import User

    with Session(engine) as session:
        user = session.get(User, uuid.UUID(user_id))
        if user is None:
            return
        n_storage = 0
        n_objects = 0
        try:
            # Checked again after each pass, in case any was added meanwhile
            for _ in range(10):
                resources = get_credential_resources(session, user.id)
                if not resources:
                    break
                for resource in resources:
                    for project in get_resource_projects(session, resource):
                        if project.dvc_storage_id == resource.id:
                            project.dvc_storage = None
                            project.dvc_storage_id = None
                            session.add(project)
                    session.commit()
                    n_copied = copy_resource_to_internal(session, resource)
                    logger.info(
                        f"Copied {n_copied} objects from {resource.bucket} "
                        "to the hub's storage"
                    )
                    session.delete(resource)
                    session.commit()
                    n_storage += 1
                    n_objects += n_copied
            else:
                raise RuntimeError(
                    "Storage kept being added during the transfer"
                )
        except Exception:
            app.mixpanel.user_transferred_storage(
                user, n_storage, n_objects, succeeded=False
            )
            raise
        credential = app.users.get_external_credential(
            session=session, user=user, provider="huggingface"
        )
        if credential is not None:
            session.delete(credential)
            session.commit()
        app.mixpanel.user_transferred_storage(
            user, n_storage, n_objects, succeeded=True
        )


def get_xet_token(
    storage: ProjectStorage, token_type: Literal["read", "write"]
) -> dict[str, Any]:
    """Get a short-lived Xet token for an HF bucket.

    It's scoped to the one bucket, so it can be handed to any client with
    access to the project. It can upload and download content, but only the
    owner's credential can add paths to the bucket.
    """
    import requests

    assert storage.bucket is not None
    resp = requests.get(
        f"{HF_ENDPOINT}/api/buckets/{storage.bucket}/xet-{token_type}-token",
        headers={"Authorization": f"Bearer {storage.token}"},
        timeout=15,
    )
    resp.raise_for_status()
    token: dict[str, Any] = resp.json()
    return token


class HfBucketBatchError(RuntimeError):
    """Some operations of an HF bucket batch failed."""

    def __init__(self, failures: list[dict[str, str]]):
        self.failures = failures
        listed = ", ".join(
            f"{f.get('path')}: {f.get('error')}" for f in failures[:5]
        )
        more = f" and {len(failures) - 5} more" if len(failures) > 5 else ""
        super().__init__(f"{len(failures)} failed ({listed}{more})")


def post_hf_bucket_batch(
    storage: ProjectStorage, ops: list[dict[str, Any]]
) -> None:
    """Add or delete files in an HF bucket with the owner's credential."""
    import requests

    assert storage.bucket is not None
    data = b"".join(json.dumps(op).encode() + b"\n" for op in ops)
    resp = requests.post(
        f"{HF_ENDPOINT}/api/buckets/{storage.bucket}/batch",
        headers={
            "Authorization": f"Bearer {storage.token}",
            "Content-Type": "application/x-ndjson",
        },
        data=data,
        timeout=60,
    )
    # HF lists failed operations in the body of a 200 for a partial failure,
    # or a 422 if all failed
    if resp.status_code in (200, 422):
        failures = resp.json().get("failed", [])
        if failures:
            raise HfBucketBatchError(failures)
    resp.raise_for_status()


def put_project_objects(
    target: ProjectStorage,
    owner_name: str,
    project_name: str,
    objects: list[tuple[str, str | bytes]],
) -> None:
    """Write objects to a project's storage, each from a local path or bytes.

    Each object is its path in the project and its source. For HF, they're
    all added in one batch.
    """
    if not objects:
        return
    if target.backend == "hf":
        from huggingface_hub import HfApi

        assert target.bucket is not None
        add: list[tuple[str | Path | bytes, str]] = [
            (
                src,
                target.make_project_path(
                    owner_name, project_name, path
                ).removeprefix(f"{target.data_prefix}/"),
            )
            for path, src in objects
        ]
        HfApi(token=target.token).batch_bucket_files(target.bucket, add=add)
        return
    for path, src in objects:
        fpath = target.make_project_path(owner_name, project_name, path)
        with target.fs.open(fpath, "wb") as f_out:
            if isinstance(src, bytes):
                f_out.write(src)
            else:
                with open(src, "rb") as f_in:
                    shutil.copyfileobj(f_in, f_out)
        if settings.ENVIRONMENT != "local":
            remove_gcs_content_type(fpath)


def get_hf_paths_info(
    storage: ProjectStorage, paths: list[str]
) -> dict[str, dict[str, Any]]:
    """Get info for many files in an HF bucket, up to 1000 per request.

    Paths are relative to the bucket. Returns info like ``fs.info`` gives,
    by path, for those that exist.
    """
    from huggingface_hub import HfApi

    assert storage.bucket is not None
    infos = {}
    for f in HfApi(token=storage.token).get_bucket_paths_info(
        storage.bucket, paths
    ):
        infos[f.path] = {
            "name": f"{storage.data_prefix}/{f.path}",
            "size": f.size,
            "type": "file",
            "mtime": f.mtime,
            "xet_hash": f.xet_hash,
        }
    return infos


def get_hf_object_url(storage: ProjectStorage, fpath: str) -> str:
    """Get a short-lived URL a browser can download an HF bucket object from.

    HF redirects authenticated requests to a signed CDN URL, which is what
    gets returned, so the owner's credential never leaves the hub.
    """
    import requests

    assert storage.bucket is not None
    path_in_bucket = fpath.removeprefix(f"{storage.data_prefix}/")
    resp = requests.get(
        f"{HF_ENDPOINT}/buckets/{storage.bucket}/resolve/{path_in_bucket}",
        headers={"Authorization": f"Bearer {storage.token}"},
        allow_redirects=False,
        timeout=15,
    )
    if resp.status_code not in (301, 302, 303, 307, 308):
        raise RuntimeError(
            f"Failed to get URL for {fpath}: {resp.status_code}"
        )
    return str(resp.headers["Location"])


def get_project_object_url(
    storage: ProjectStorage, fpath: str, fname: str | None = None
) -> str:
    """Get a URL a browser can download a project object from."""
    if storage.backend == "hf":
        return get_hf_object_url(storage, fpath)
    return get_object_url(fpath, fname=fname, fs=storage.fs)


def get_multipart_upload_info(
    fs: s3fs.S3FileSystem | gcsfs.GCSFileSystem,
    fpath: str,
    upload_size_bytes: int,
    expires: int = 900,
    content_type: str | None = None,
) -> dict:
    """Get multipart/chunked upload info with all presigned URLs.

    For S3: Returns dict with upload_id, bucket, key, part_urls, complete_url,
    abort_url
    For GCS: Returns dict with init_url for resumable upload

    Note: For S3, this creates a multipart upload server-side. If the client
    never completes or aborts, it will leave orphaned uploads. To prevent
    storage costs, configure S3 lifecycle rules to automatically clean up
    incomplete multipart uploads after a few days.
    The abort_url is provided to allow
    clients to explicitly clean up if they decide not to complete the upload.
    """
    if isinstance(fs, s3fs.S3FileSystem):
        part_size = get_upload_chunk_size("s3")
        estimated_part_count = (upload_size_bytes + part_size - 1) // part_size
        # Enforce S3's 10,000-part limit by dynamically increasing part size
        if estimated_part_count > S3_MAX_PARTS:
            part_size = (upload_size_bytes + S3_MAX_PARTS - 1) // S3_MAX_PARTS
            estimated_part_count = (
                upload_size_bytes + part_size - 1
            ) // part_size
        result = _generate_multipart_urls(
            fpath=fpath,
            estimated_part_count=estimated_part_count,
            expires=expires,
            fs=fs,
            content_type=content_type,
        )
        result["part_size_bytes"] = part_size
        return result
    elif isinstance(fs, gcsfs.GCSFileSystem):
        part_size = get_upload_chunk_size("gcs")
        estimated_part_count = (upload_size_bytes + part_size - 1) // part_size
        init_headers = {"x-goog-resumable": "start"}
        # Try POST first (preferred), fall back to PUT
        http_method = "POST"
        try:
            init_url = fs.sign(
                fpath,
                expiration=expires,
                method="POST",
                headers=init_headers,
            )
        except Exception:
            init_url = None
        if init_url is None:
            http_method = "PUT"
            init_url = fs.sign(
                fpath,
                expiration=expires,
                method="PUT",
                headers=init_headers,
            )
        if init_url is None:
            raise RuntimeError("Failed to generate chunked init URL")
        return {
            "init_url": init_url,
            "http_method": http_method,
            "estimated_chunk_count": estimated_part_count,
            "chunk_size_bytes": part_size,
        }
    else:
        raise ValueError("Unsupported filesystem type")


def get_storage_usage(
    owner_name: str,
    fs: s3fs.S3FileSystem | gcsfs.GCSFileSystem | None = None,
    project_name: str | None = None,
) -> float:
    """Get the hub's storage usage in GB for an owner, or one of their
    projects.
    """
    cache_key = f"{settings.ENVIRONMENT}:{owner_name}"
    prefix = get_data_prefix_for_owner(owner_name)
    if project_name is not None:
        cache_key += f"/{project_name.lower()}"
        prefix += f"/{project_name.lower()}"
    use_cache = fs is None
    if use_cache:
        cached = _storage_usage_cache.get(cache_key)
        if cached is not None:
            return cached
        fs = get_object_fs()
    assert fs is not None
    try:
        usage = fs.du(prefix)
    except FileNotFoundError:
        usage = 0
    if isinstance(usage, dict):
        usage = sum(float(v) for v in usage.values())
    usage_gb = float(usage) / 1e9
    if use_cache:
        _storage_usage_cache[cache_key] = usage_gb
    return usage_gb


def invalidate_storage_usage_cache(owner_name: str | None = None) -> None:
    """Invalidate cached storage usage for one owner or all owners."""
    if owner_name is None:
        _storage_usage_cache.clear()
        return
    # The owner's and each of their projects'
    key = f"{settings.ENVIRONMENT}:{owner_name}"
    for cached_key in list(_storage_usage_cache):
        if cached_key == key or cached_key.startswith(f"{key}/"):
            _storage_usage_cache.pop(cached_key, None)


def migrate_legacy_dvc_paths(dry_run=True):
    """Migrate legacy DVC paths in object storage to new structure with
    'files/md5/'.
    """
    fs = get_object_fs()
    data_prefix = get_data_prefix()
    # Iterate over all owners and projects, renaming any two character folders
    # to prepend 'files/md5/' to match the new DVC path structure
    for owner_path in fs.ls(data_prefix, False):
        owner_name = os.path.basename(owner_path)
        owner_prefix = get_data_prefix_for_owner(owner_name, lowercase=False)
        for project_path in fs.ls(owner_prefix, False):
            project_name = os.path.basename(project_path)
            project_prefix = f"{owner_prefix}/{project_name}"
            for item_path in fs.ls(project_prefix, False):
                item_name = os.path.basename(item_path)
                if len(item_name) == 2 and all(c.isalnum() for c in item_name):
                    old_path = (
                        f"{data_prefix}/{owner_name}/{project_name}"
                        f"/{item_name}"
                    )
                    new_path = (
                        f"{data_prefix}/{owner_name}/{project_name}"
                        f"/files/md5/{item_name}"
                    )
                    print(f"Renaming {old_path} to {new_path}")
                    if not dry_run:
                        fs.mv(old_path, new_path, recursive=True)
            # Check that the path is lowercase
            if project_prefix != project_prefix.lower():
                old_path = f"{data_prefix}/{owner_name}/{project_name}"
                new_path = (
                    f"{data_prefix.lower()}/{owner_name.lower()}"
                    f"/{project_name.lower()}"
                )
                print(f"Renaming {old_path} to {new_path} to make lowercase")
                if not dry_run:
                    fs.mv(old_path, new_path, recursive=True)
