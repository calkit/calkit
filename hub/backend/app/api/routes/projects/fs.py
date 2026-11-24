"""fsspec related routes for projects."""

import base64
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StringConstraints

import app
import app.projects
from app import mixpanel, storage
from app.api.deps import CurrentUserOptional, SessionDep
from app.config import settings
from app.storage import get_object_url

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RETURN_CONTENT_SIZE_LIMIT = 1_000_000
XET_HASH_RE = r"^[0-9a-f]{64}$"
# Shared by every batch request, so concurrent requests can't multiply the
# threads and storage connections a worker holds
_batch_op_pool = ThreadPoolExecutor(
    max_workers=32, thread_name_prefix="fs-batch-op"
)


class PresignedUrlAccess(BaseModel):
    kind: Literal["presigned-url"] = "presigned-url"
    url: str
    http_method: Literal["GET", "PUT", "DELETE"]
    expires_at: datetime | None = None
    headers: dict | None = None
    params: dict | None = None


class PresignedMultipartAccess(BaseModel):
    kind: Literal["presigned-multipart"] = "presigned-multipart"
    bucket: str
    key: str
    upload_id: str
    part_urls: list[str]
    complete_url: str
    abort_url: str
    part_size_bytes: int
    estimated_part_count: int
    upload_size_bytes: int
    content_type: str | None = None


class PresignedChunkedAccess(BaseModel):
    kind: Literal["presigned-chunked"] = "presigned-chunked"
    init_url: str
    http_method: Literal["POST", "PUT"]
    chunk_size_bytes: int
    estimated_chunk_count: int
    upload_size_bytes: int
    content_type: str | None = None
    headers: dict | None = None
    params: dict | None = None
    expires_at: datetime | None = None


class HttpRequestAccess(BaseModel):
    kind: Literal["http-request"] = "http-request"
    url: str
    http_method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    headers: dict | None = None
    params: dict | None = None
    expires_at: datetime | None = None


class SftpAccess(BaseModel):
    kind: Literal["sftp"] = "sftp"
    host: str
    port: int = 22
    username: str
    password: str | None = None
    private_key: str | None = None
    remote_path: str
    expires_at: datetime | None = None


class XetAccess(BaseModel):
    """Access to Hugging Face storage through the Xet protocol.

    The client uploads or downloads content with ``hf_xet`` using this
    short-lived token, which covers the whole bucket, so a client can reuse
    it until it expires. After uploads, the client sends a batch
    ``register`` operation with their Xet hashes so the hub can add the
    paths to the bucket, which the token alone can't do.
    """

    kind: Literal["hf-xet"] = "hf-xet"
    operation: Literal["upload", "download"]
    # The bucket the token is for, as ``{namespace}/{name}``, since a
    # project's objects can be in more than one
    bucket: str | None = None
    # Xet's content-addressable storage (CAS) service
    cas_url: str
    access_token: str
    expires_at_unixts: int
    # For downloads
    xet_hash: str | None = None
    size: int | None = None


class FsListResult(BaseModel):
    paths: list[str] | list[dict]  # Depends on detail flag in request


class ExistsResult(BaseModel):
    exists: bool


class InfoResult(BaseModel):
    name: str
    size: int
    type: str  # "file" or "directory"
    time_modified: str | None = None


class OperationResult(BaseModel):
    """Result for file operations like delete, move, copy."""

    success: bool
    message: str | None = None


class FsOpResponse(BaseModel):
    """Response describing how to perform a file system operation
    (get/put/exists/list) for a given path within the project.
    """

    backend: Literal["gcs", "s3", "google-drive", "box", "hf"]
    access: (
        Annotated[
            PresignedUrlAccess
            | PresignedMultipartAccess
            | PresignedChunkedAccess
            | HttpRequestAccess
            | SftpAccess
            | XetAccess,
            Field(discriminator="kind"),
        ]
        | None
    ) = None
    result: (
        FsListResult | ExistsResult | InfoResult | OperationResult | None
    ) = None


class FsOpRequest(BaseModel):
    operation: Literal["get", "put", "exists", "list", "find", "info"]
    path: str
    content_length: int | None = None
    content_type: str | None = None
    detail: bool = False


def _get_time_modified(info: dict[str, Any]) -> str | None:
    """Get an object's modification time, which HF calls ``mtime``."""
    value = info.get("time_modified") or info.get("mtime")
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _strip_data_prefix(path: str, data_prefix: str) -> str:
    bare = re.sub(r"^[a-z0-9]+://", "", data_prefix.rstrip("/"))
    data_prefix_candidates = [
        f"{data_prefix.rstrip('/')}/",
        f"{bare}/",
    ]
    for prefix in data_prefix_candidates:
        if path.startswith(prefix):
            return path.removeprefix(prefix)
    return path


@router.post("/projects/{owner_name}/{project_name}/fs/ops")
def post_project_fs_op(
    owner_name: str,
    project_name: str,
    req: FsOpRequest,
    session: SessionDep,
    current_user: CurrentUserOptional,
) -> FsOpResponse:
    """Endpoint for the fsspec client to know how to perform operations on a
    given path within the project.

    The client specifies the operation (get/put) and path, and the server
    responds with instructions on how to access it:
    - Presigned URL for direct HTTP access
    - API credentials for indirect API access
    - Request delegation info for non-presigned flows
    """
    # Ensure owner and project name are lowercase
    owner_name = owner_name.lower()
    project_name = project_name.lower()
    operation = req.operation
    path = req.path
    content_length = req.content_length
    content_type = req.content_type
    # Prevent path traversal attacks
    if os.path.isabs(path):
        raise HTTPException(400, "Absolute paths are not allowed")
    if ".." in path.split(os.sep):
        raise HTTPException(400, "Path traversal is not allowed")
    if content_length is not None and content_length < 0:
        raise HTTPException(
            status_code=422, detail="content_length must be >= 0"
        )
    # Verify project access
    min_access = (
        "read"
        if operation in ["get", "list", "exists", "info", "find"]
        else "write"
    )
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level=min_access,
    )
    logger.info(
        f"Getting {operation} instructions for "
        f"{owner_name}/{project_name}/{path}"
    )
    # New objects go to the first storage, and reads fall back through the
    # rest, since objects aren't moved when a project switches storage
    storage_locations = storage.get_project_storage_locations(session, project)
    backend = storage_locations[0].backend
    for st in storage_locations:
        if (
            st.backend != "hf"
            and settings.ENVIRONMENT == "local"
            and not st.fs.exists(st.data_prefix)
        ):
            st.fs.makedir(st.data_prefix)
    if operation == "exists":
        exists = False
        for st in storage_locations:
            # Use ls here since some backends (like GCS) don't have an
            # efficient way to check for existence
            try:
                res = st.fs.ls(
                    st.make_project_path(owner_name, project_name, path),
                    detail=False,
                )
            except FileNotFoundError:
                continue
            if len(res) > 0:
                exists = True
                break
        return FsOpResponse(
            backend=backend,
            result=ExistsResult(exists=exists),
        )
    if operation == "info":
        for st in storage_locations:
            try:
                info_dict = st.fs.info(
                    st.make_project_path(owner_name, project_name, path)
                )
            except FileNotFoundError:
                continue
            return FsOpResponse(
                backend=backend,
                result=InfoResult(
                    name=info_dict.get("name", ""),
                    size=info_dict.get("size", 0),
                    type=info_dict.get("type", "file"),
                    time_modified=_get_time_modified(info_dict),
                ),
            )
        raise HTTPException(404, "Path not found")
    if operation in ("list", "find"):
        # Merge results across storage locations, keeping the first per name
        merged: dict[str, dict[str, Any] | str] = {}
        for st in storage_locations:
            full_path = st.make_project_path(owner_name, project_name, path)
            try:
                if operation == "list":
                    found = st.fs.ls(full_path, detail=req.detail)
                else:
                    found = st.fs.find(full_path, detail=req.detail)
            except FileNotFoundError:
                # Missing prefixes are normal in fresh projects and behave
                # like no matches
                continue
            if isinstance(found, dict):
                found = (
                    [
                        obj | {"name": obj.get("name", k)}
                        for k, obj in found.items()
                    ]
                    if req.detail
                    else list(found.keys())
                )
            # Paths go back as if in a namespace, even from dedicated
            # storage, i.e., under ``{owner}/{project}``
            data_prefix = st.data_prefix
            project_prefix = ""
            if st.is_dedicated:
                project_prefix = f"{owner_name}/{project_name}/"
            for item in found:
                if req.detail:
                    if isinstance(item, str):
                        item = {"name": item, "Key": item}
                    name = project_prefix + _strip_data_prefix(
                        item.get("name", ""), data_prefix
                    )
                    item = item | {
                        "name": name,
                        "Key": project_prefix
                        + _strip_data_prefix(
                            item.get("Key", item.get("name", "")),
                            data_prefix,
                        ),
                    }
                    merged.setdefault(name, item)
                else:
                    name = project_prefix + _strip_data_prefix(
                        item, data_prefix
                    )
                    merged.setdefault(name, name)
        return FsOpResponse(
            backend=backend,
            result=FsListResult(paths=list(merged.values())),  # type: ignore[arg-type]
        )
    if operation == "get":
        found_obj = storage.find_project_object(
            session, project, path, storage_locations=storage_locations
        )
        if found_obj is None:
            raise HTTPException(404, "Path not found")
        st, full_path = found_obj
        if st.backend == "hf":
            assert st.bucket is not None
            info_dict = st.fs.info(full_path)
            if not info_dict.get("xet_hash"):
                raise HTTPException(400, "Path is not a file")
            try:
                token = storage.get_xet_token(st, "read")
            except Exception:
                logger.exception(f"Failed to get Xet read token for {path}")
                raise HTTPException(502, "Failed to get download access")
            # Once per pull, since clients reuse the access for the rest
            if current_user is not None:
                mixpanel.user_performed_fs_op(
                    current_user, owner_name, project_name, "get", backend="hf"
                )
            return FsOpResponse(
                backend=st.backend,
                access=XetAccess(
                    operation="download",
                    bucket=st.bucket,
                    cas_url=token["casUrl"],
                    access_token=token["accessToken"],
                    expires_at_unixts=token["exp"],
                    xet_hash=info_dict["xet_hash"],
                    size=info_dict["size"],
                ),
            )
        url = get_object_url(
            fpath=full_path,
            fname=None,
            expires=3600,
            fs=st.fs,
            method="get",
        )
        return FsOpResponse(
            backend=st.backend,
            access=PresignedUrlAccess(
                url=url,
                http_method="GET",
            ),
        )
    target = storage.get_project_storage(session, project)
    backend = target.backend
    full_path = target.make_project_path(owner_name, project_name, path)
    # We are doing a PUT if we've made it this far
    assert operation == "put"
    if target.backend == "hf":
        assert target.bucket is not None
        try:
            token = storage.get_xet_token(target, "write")
        except Exception:
            logger.exception(f"Failed to get Xet write token for {path}")
            raise HTTPException(502, "Failed to get upload access")
        access: (
            XetAccess
            | PresignedMultipartAccess
            | PresignedChunkedAccess
            | PresignedUrlAccess
        ) = XetAccess(
            operation="upload",
            bucket=target.bucket,
            cas_url=token["casUrl"],
            access_token=token["accessToken"],
            expires_at_unixts=token["exp"],
        )
    # Determine if we need chunked upload for large puts
    elif storage.upload_should_be_chunked(content_length):
        # At this point, content_length is guaranteed to be not None
        assert content_length is not None
        try:
            upload_info = storage.get_multipart_upload_info(
                fs=target.fs,
                fpath=full_path,
                upload_size_bytes=content_length,
                expires=900,
                content_type=content_type,
            )
        except Exception:
            logger.exception(
                f"Failed to get multipart upload info for {full_path}"
            )
            raise HTTPException(500, "Failed to determine upload method")
        if backend == "s3":
            access = PresignedMultipartAccess(
                bucket=upload_info["bucket"],
                key=upload_info["key"],
                upload_id=upload_info["upload_id"],
                part_urls=upload_info["part_urls"],
                complete_url=upload_info["complete_url"],
                abort_url=upload_info["abort_url"],
                part_size_bytes=upload_info["part_size_bytes"],
                estimated_part_count=len(upload_info["part_urls"]),
                upload_size_bytes=content_length,
                content_type=content_type,
            )
        elif backend == "gcs":
            access = PresignedChunkedAccess(
                init_url=upload_info["init_url"],
                http_method=upload_info["http_method"],
                chunk_size_bytes=upload_info["chunk_size_bytes"],
                estimated_chunk_count=upload_info["estimated_chunk_count"],
                upload_size_bytes=content_length,
                content_type=content_type,
                headers={"x-goog-resumable": "start"},
            )
        else:
            raise HTTPException(
                500, f"Chunked upload not supported for {backend}"
            )
    # Regular presigned PUT URL for smaller files
    else:
        put_headers = None
        try:
            url = get_object_url(
                fpath=full_path,
                fname=None,
                expires=900,
                fs=target.fs,
                method="put",
            )
        except RuntimeError:
            logger.exception(f"Failed to get presigned URL for {full_path}")
            raise HTTPException(500, "Failed to get presigned URL")
        access = PresignedUrlAccess(
            url=url,
            http_method="PUT",
            headers=put_headers,
        )
    if current_user is not None:
        mixpanel.user_performed_fs_op(
            current_user, owner_name, project_name, operation, backend=backend
        )
    return FsOpResponse(backend=backend, access=access)


class FsOpBatchRequest(BaseModel):
    operation: Literal["exists", "info", "register"]
    paths: list[str]
    include: list[Literal["exists", "info", "content"]] | None = None
    # For register, each path's Xet hash after an upload
    xet_hashes: (
        dict[str, Annotated[str, StringConstraints(pattern=XET_HASH_RE)]]
        | None
    ) = None
    # For register, the bucket the content was uploaded to, as
    # ``{namespace}/{name}``
    bucket: str | None = None


class FsOpBatchResult(BaseModel):
    """Result for batch file system operations on multiple paths."""

    exists: bool | None = None
    info: dict | None = None
    content_base64: str | None = None


class FsOpBatchResponse(BaseModel):
    backend: Literal["gcs", "s3", "google-drive", "box", "hf"]
    results: dict[str, FsOpBatchResult]


@router.post("/projects/{owner_name}/{project_name}/fs/ops/batch")
def post_project_fs_batch_op(
    owner_name: str,
    project_name: str,
    req: FsOpBatchRequest,
    session: SessionDep,
    current_user: CurrentUserOptional,
) -> FsOpBatchResponse:
    """Endpoint for batch file system operations for multiple paths."""

    def get_result(path: str) -> FsOpBatchResult:
        # Use the first storage that has the path, or the first overall
        found = storage_locations[0]
        full_path = storage_locations[0].make_project_path(
            owner_name, project_name, path
        )
        # What HF said about the path, if it's in HF storage
        hf_info = None
        for i, st in enumerate(storage_locations):
            candidate = st.make_project_path(owner_name, project_name, path)
            if i in hf_infos:
                hf_info = hf_infos[i].get(
                    st.make_container_path(owner_name, project_name, path)
                )
                if hf_info is not None or len(storage_locations) == 1:
                    found, full_path = st, candidate
                    break
                continue
            if len(storage_locations) == 1 or st.fs.exists(candidate):
                found, full_path = st, candidate
                break
        fs = found.fs
        from_hf = storage_locations.index(found) in hf_infos
        path_result: dict[str, Any] = {}
        # Handle exists
        if operation == "exists" or "exists" in include:
            if from_hf:
                exists = hf_info is not None
            else:
                try:
                    res = fs.ls(full_path, detail=False)
                    exists = len(res) > 0
                except FileNotFoundError:
                    exists = False
            path_result["exists"] = exists
        # Handle info, which content needs for its size check anyway
        info_dict = hf_info
        if not from_hf and (
            operation == "info" or "info" in include or "content" in include
        ):
            try:
                info_dict = fs.info(full_path)
            except FileNotFoundError:
                pass
        if operation == "info" or "info" in include:
            path_result["info"] = None
            if info_dict is not None:
                path_result["info"] = {
                    "name": info_dict.get("name", ""),
                    "size": info_dict.get("size", 0),
                    "type": info_dict.get("type", "file"),
                    "time_modified": _get_time_modified(info_dict),
                }
                # So clients can download from HF without asking per file
                if info_dict.get("xet_hash") and found.bucket is not None:
                    path_result["info"]["xet_hash"] = info_dict["xet_hash"]
                    path_result["info"]["bucket"] = found.bucket
        # Handle content (if requested via include)
        if "content" in include and info_dict is not None:
            path_result["content_base64"] = None
            file_size = info_dict.get("size", 0)
            if file_size > RETURN_CONTENT_SIZE_LIMIT:
                logger.info(
                    f"Skipping content for {path} "
                    f"(size: {file_size} > {RETURN_CONTENT_SIZE_LIMIT})"
                )
            else:
                try:
                    content_bytes = fs.cat_file(full_path)
                    if isinstance(content_bytes, str):
                        content_bytes = content_bytes.encode("utf-8")
                    path_result["content_base64"] = base64.b64encode(
                        content_bytes
                    ).decode("utf-8")
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    logger.exception(
                        f"Error while reading file content for {full_path}"
                    )
                    raise HTTPException(
                        status_code=500,
                        detail=f"Error reading file content for path: {path}",
                    ) from exc
        return FsOpBatchResult(**path_result)

    owner_name = owner_name.lower()
    project_name = project_name.lower()
    operation = req.operation
    paths = req.paths
    include = req.include or []
    # Prevent path traversal attacks
    for path in paths:
        if os.path.isabs(path):
            raise HTTPException(400, "Absolute paths are not allowed")
        if ".." in path.split(os.sep):
            raise HTTPException(400, "Path traversal is not allowed")
    # Verify project access
    min_access = (
        "read" if operation in ["get", "list", "exists", "info"] else "write"
    )
    project = app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level=min_access,
    )
    if operation == "register":
        # Many uploads' paths added with one call to HF
        target = storage.get_project_storage(session, project)
        # E.g., if the project switched to the hub's own storage after the
        # client got its access
        if target.backend != "hf":
            raise HTTPException(409, "Project storage changed; push again")
        assert target.bucket is not None
        # Content uploaded to a bucket the project no longer uses can't be
        # added to the new one
        if req.bucket is not None and req.bucket != target.bucket:
            raise HTTPException(409, "Project storage changed; push again")
        xet_hashes = req.xet_hashes or {}
        if set(paths) != set(xet_hashes):
            raise HTTPException(422, "Every path needs a xet_hash")
        ops = [
            {
                "type": "addFile",
                "path": target.make_container_path(
                    owner_name, project_name, path
                ),
                "xetHash": xet_hashes[path],
            }
            for path in paths
        ]
        try:
            storage.post_hf_bucket_batch(target, ops)
        except storage.HfBucketBatchError as e:
            logger.error(f"Failed to register files: {e}")
            base = target.make_container_path(owner_name, project_name)
            failed = [
                str(f.get("path", "")).removeprefix(base).lstrip("/")
                for f in e.failures
            ]
            # Not 502, since retrying won't help, and the CLI retries those
            raise HTTPException(
                422,
                f"Failed to register {len(failed)} of {len(ops)} files: "
                + ", ".join(failed[:5])
                + (" and more" if len(failed) > 5 else ""),
            )
        except Exception:
            logger.exception(f"Failed to register {len(ops)} files")
            raise HTTPException(502, "Failed to register uploaded files")
        if current_user is not None:
            mixpanel.user_pushed_to_external_storage(
                current_user,
                owner_name,
                project_name,
                kind="hf-bucket",
                n_files=len(ops),
            )
        return FsOpBatchResponse(backend=target.backend, results={})
    storage_locations = storage.get_project_storage_locations(session, project)
    backend = storage_locations[0].backend
    for st in storage_locations:
        if (
            st.backend != "hf"
            and settings.ENVIRONMENT == "local"
            and not st.fs.exists(st.data_prefix)
        ):
            st.fs.makedir(st.data_prefix)
    # HF looks up files in batches, rather than a request per path. Only
    # files are found that way, which is all DVC's objects are.
    hf_infos: dict[int, dict[str, dict[str, Any]]] = {}
    for i, st in enumerate(storage_locations):
        if st.backend != "hf":
            continue
        try:
            hf_infos[i] = storage.get_hf_paths_info(
                st,
                [
                    st.make_container_path(owner_name, project_name, path)
                    for path in paths
                ],
            )
        except Exception:
            # Then each path is looked up on its own, as for other storage
            logger.exception("Failed to get HF paths info in a batch")
    # Each other path is a round trip to object storage, and a DVC push
    # asks about hundreds of them, so they're made concurrently
    results = dict(zip(paths, _batch_op_pool.map(get_result, paths)))
    return FsOpBatchResponse(backend=backend, results=results)
