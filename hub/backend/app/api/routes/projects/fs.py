"""fsspec related routes for projects."""

import base64
import logging
import os
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
            | SftpAccess,
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


def _strip_data_prefix(path: str, data_prefix: str) -> str:
    data_prefix_candidates = [
        f"{data_prefix.rstrip('/')}/",
        f"{data_prefix.removeprefix('s3://').rstrip('/')}/",
        f"{data_prefix.removeprefix('gcs://').rstrip('/')}/",
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
    app.projects.get_project(
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
    # TODO: Determine project fs storage type
    # Should we allow for multiple depending on the path?
    # Is Git one?
    # If none is defined, they are using the default object storage connected
    # to this system
    # For now, only support GCS/S3 via presigned URLs
    # Future: Add google_drive, box, huggingface backends
    backend = storage.get_backend()
    fs = storage.get_object_fs()
    # Construct full storage path
    data_prefix = storage.get_data_prefix()
    if settings.ENVIRONMENT == "local" and not fs.exists(data_prefix):
        fs.makedir(data_prefix)
    full_path = f"{data_prefix}/{owner_name}/{project_name}/{path}"
    # If operation is "exists" or "list", we can check if the file exists and
    # return that info to avoid an extra round trip
    if operation == "exists":
        # Use ls here since some backends (like GCS) don't have an efficient
        # way to check for existence
        try:
            res = fs.ls(full_path, detail=False)
            exists = len(res) > 0
        except FileNotFoundError:
            exists = False
        return FsOpResponse(
            backend=backend,
            result=ExistsResult(exists=exists),
        )
    if operation == "info":
        try:
            info_dict = fs.info(full_path)
        except FileNotFoundError:
            raise HTTPException(404, "Path not found")
        return FsOpResponse(
            backend=backend,
            result=InfoResult(
                name=info_dict.get("name", ""),
                size=info_dict.get("size", 0),
                type=info_dict.get("type", "file"),
                time_modified=info_dict.get("time_modified"),
            ),
        )
    if operation == "list":
        try:
            paths = fs.ls(full_path, detail=req.detail)
        except FileNotFoundError:
            # Missing prefixes are normal in fresh projects; return empty list
            paths = []
        if req.detail:
            paths = [
                obj
                | {
                    "name": _strip_data_prefix(
                        obj.get("name", ""), data_prefix
                    ),
                    "Key": _strip_data_prefix(obj.get("Key", ""), data_prefix),
                }
                for obj in paths
            ]
        else:
            paths = [_strip_data_prefix(path, data_prefix) for path in paths]
        return FsOpResponse(
            backend=backend,
            result=FsListResult(paths=paths),
        )
    if operation == "find":
        try:
            paths = fs.find(full_path, detail=req.detail)
        except FileNotFoundError:
            # For "find", a missing prefix should behave like no matches
            # This avoids noisy 404s for normal existence probes
            paths = {} if req.detail else []
        if req.detail:
            if isinstance(paths, dict):
                paths = [
                    obj
                    | {
                        "name": _strip_data_prefix(
                            obj.get("name", path), data_prefix
                        ),
                        "Key": _strip_data_prefix(
                            obj.get("Key", path), data_prefix
                        ),
                    }
                    for path, obj in paths.items()
                ]
            else:
                paths = [
                    {
                        "name": _strip_data_prefix(path, data_prefix),
                        "Key": _strip_data_prefix(path, data_prefix),
                    }
                    for path in paths
                ]
        else:
            if isinstance(paths, dict):
                paths = list(paths.keys())
            paths = [_strip_data_prefix(path, data_prefix) for path in paths]
        return FsOpResponse(
            backend=backend,
            result=FsListResult(paths=paths),
        )
    if operation == "get":
        url = get_object_url(
            fpath=full_path,
            fname=None,
            expires=3600,
            fs=fs,
            method="get",
        )
        return FsOpResponse(
            backend=backend,
            access=PresignedUrlAccess(
                url=url,
                http_method="GET",
            ),
        )
    # We are doing a PUT if we've made it this far
    assert operation == "put"
    # Determine if we need chunked upload for large puts
    chunked = storage.upload_should_be_chunked(content_length)
    if chunked:
        # At this point, content_length is guaranteed to be not None
        assert content_length is not None
        try:
            upload_info = storage.get_multipart_upload_info(
                fs=fs,
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
                fs=fs,
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
            current_user, owner_name, project_name, operation
        )
    return FsOpResponse(backend=backend, access=access)


class FsOpBatchRequest(BaseModel):
    operation: Literal["exists", "info"]
    paths: list[str]
    include: list[Literal["exists", "info", "content"]] | None = None


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
    app.projects.get_project(
        owner_name=owner_name,
        project_name=project_name,
        session=session,
        current_user=current_user,
        min_access_level=min_access,
    )
    backend = storage.get_backend()
    fs = storage.get_object_fs()
    data_prefix = storage.get_data_prefix()
    if settings.ENVIRONMENT == "local" and not fs.exists(data_prefix):
        fs.makedir(data_prefix)
    results = {}
    for path in paths:
        full_path = f"{data_prefix}/{owner_name}/{project_name}/{path}"
        path_result = {}
        # Handle exists
        if operation == "exists" or "exists" in include:
            try:
                res = fs.ls(full_path, detail=False)
                exists = len(res) > 0
            except FileNotFoundError:
                exists = False
            path_result["exists"] = exists
        # Handle info
        if operation == "info" or "info" in include:
            try:
                info_dict = fs.info(full_path)
                path_result["info"] = {
                    "name": info_dict.get("name", ""),
                    "size": info_dict.get("size", 0),
                    "type": info_dict.get("type", "file"),
                    "time_modified": info_dict.get("time_modified"),
                }
            except FileNotFoundError:
                path_result["info"] = None
        # Handle content (if requested via include)
        if "content" in include:
            try:
                # Check file size before reading content
                info_dict = path_result.get("info")
                if info_dict is None:
                    info_dict = fs.info(full_path)
                file_size = info_dict.get("size", 0)
                if file_size > RETURN_CONTENT_SIZE_LIMIT:
                    logger.info(
                        f"Skipping content for {path} "
                        f"(size: {file_size} > {RETURN_CONTENT_SIZE_LIMIT})"
                    )
                    path_result["content_base64"] = None
                else:
                    content_bytes = fs.cat_file(full_path)
                    if isinstance(content_bytes, str):
                        content_bytes = content_bytes.encode("utf-8")
                    path_result["content_base64"] = base64.b64encode(
                        content_bytes
                    ).decode("utf-8")
            except FileNotFoundError:
                path_result["content_base64"] = None
            except Exception as exc:
                logger.exception(
                    f"Error while reading file content for {full_path}"
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"Error reading file content for path: {path}",
                ) from exc
        results[path] = FsOpBatchResult(**path_result)
    return FsOpBatchResponse(backend=backend, results=results)
