"""A filesystem-like object that follows ``fsspec`` and interacts with Calkit
cloud storage to unify operations between private and public storage.

The basic operation is as follows:
1. Make a request to the Calkit API over HTTP to get file operation info.
2. The API returns access details based on the configured storage backend.
3. Use the access details (presigned URL, OAuth, etc.) to perform the operation.

Path format:
    ck://owner/project/path/to/file

    - owner: Calkit username/organization
    - project: Project name
    - path/to/file: File path within the project (optional)

Supported storage backends (via Calkit Cloud API):
    - Google Cloud Storage (GCS) - presigned URLs
    - Amazon S3 - presigned URLs
    - Google Drive - OAuth + API
    - Box - OAuth + API
    - Other storage providers as configured in Calkit Cloud

Multi-cloud support:
    By default, the filesystem routes to the Calkit Cloud API endpoint
    configured by CALKIT_ENV (production, staging, etc.). To use a different
    Calkit Cloud instance:

    - DVC config: dvc remote modify myremote endpointurl https://api.other.com
    - URI query: ck://owner/project/file?endpoint_url=https://api.other.com

Examples:
    # DVC remote (DVC will organize by MD5 hashes automatically)
    ck://owner/project

    # Subdirectory for organization
    ck://owner/project/data

    # Direct filesystem usage
    >>> from calkit.fs import CalkitFileSystem
    >>> fs = CalkitFileSystem()
    >>> with fs.open("ck://owner/project/file.txt", "rb") as f:
    ...     content = f.read()

    # Using with pandas (automatic fsspec integration)
    >>> import pandas as pd
    >>> import calkit  # Import to register the filesystem
    >>> df = pd.read_parquet("ck://owner/project/data.parquet")
    >>> df.to_parquet("ck://owner/project/output.parquet")

    # Using with polars (requires explicit fsspec.open)
    >>> import polars as pl
    >>> import fsspec
    >>> import calkit  # Import to register the filesystem
    >>> # Reading
    >>> with fsspec.open("ck://owner/project/data.parquet", "rb") as f:
    ...     df = pl.read_parquet(f)
    >>> # Writing
    >>> with fsspec.open("ck://owner/project/output.parquet", "wb") as f:
    ...     df.write_parquet(f)

Note:
    Pandas automatically uses fsspec for custom protocols, but Polars uses
    Rust's object_store crate which doesn't support fsspec. For Polars, use
    fsspec.open() explicitly to get a file-like object.

The design supports transparent interaction with multiple storage backends
or providers through a unified API.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse

import requests
from fsspec import AbstractFileSystem
from fsspec.spec import AbstractBufferedFile
from fsspec.utils import stringify_path

import calkit


def register_filesystem():
    """Register the Calkit filesystem with fsspec's registry.

    This function is called automatically when the module is imported,
    but can also be called manually if needed.
    """
    from fsspec.registry import register_implementation

    register_implementation("ck", "calkit.fs.CalkitFileSystem")


# Register the filesystem when the module is imported
register_filesystem()


def _parse_path(path: str) -> tuple[str, str, str]:
    """Parse a Calkit path into (owner, project, file_path)."""
    path = stringify_path(path)
    parsed = urlparse(path)
    if parsed.scheme == "ck":
        # Standard format: ck://owner/project/file
        # netloc is the owner, path contains /project/file
        if parsed.netloc:
            raw_path = f"{parsed.netloc}{parsed.path}"
        else:
            raw_path = parsed.path.lstrip("/")
    else:
        # fsspec may pass protocol-stripped paths
        raw_path = path.lstrip("/")
    path_parts = [part for part in raw_path.split("/") if part]
    # Need at least owner/project
    if len(path_parts) < 2:
        raise ValueError(
            f"Invalid path format: {path}; Expected ck://owner/project/path"
        )
    owner = path_parts[0]
    project = path_parts[1]
    file_path = "/".join(path_parts[2:]) if len(path_parts) > 2 else ""
    return owner, project, file_path


class CalkitFileSystem(AbstractFileSystem):
    """An fsspec-compatible filesystem for Calkit cloud storage.

    This filesystem makes requests to the Calkit API to get file operation
    information, then uses the appropriate method to interact with the
    underlying storage backend.

    The Calkit Cloud API acts as a compatibility layer that:

    - Determines which storage backend is configured for each project
    - Returns appropriate access credentials (presigned URLs, OAuth tokens,
      etc.)
    - Supports GCS, S3, Google Drive, Box, Azure, and other providers

    Path format: ck://owner/project/path/to/file

    Users can organize their files however they want. For example:

    - DVC will automatically organize by MD5 hashes
    - Users can create subdirectories for organization (data/, models/, etc.)
    - Files can be stored at the project root

    Cloud endpoints are configured via:

    - endpointurl parameter (for DVC remotes): Route to different Calkit
      instances
    - endpoint_url query parameter (for URIs): Ad-hoc endpoint specification
    - CALKIT_ENV environment variable: Select production, staging, local, or
      test
    - Defaults to production when unspecified

    This design allows for:

    - Multiple storage backend support without client-side changes
    - Multi-cloud support with configurable endpoints
    - Future protocol upgrades (e.g., SFTP) without breaking API compatibility
    - Unified interface regardless of underlying storage provider

    Attributes
    ----------
    protocol : str
        The protocol scheme for this filesystem ("ck")
    base_url : str
        The Calkit Cloud API endpoint URL, configured via endpointurl in DVC
        config, endpoint_url in URI query, or CALKIT_ENV environment variable.
        Defaults to production (https://api.calkit.io) when unspecified.
    """

    protocol = "ck"

    def __init__(self, *args, **kwargs):
        """Initialize the filesystem."""
        super().__init__(*args, **kwargs)
        self._session = requests.Session()
        self.base_url = (
            kwargs.get("endpoint_url") or calkit.cloud.get_base_url()
        )

    def _get_fs_op_info(
        self,
        owner: str,
        project: str,
        path: str,
        operation: str = "get",
        content_length: int | None = None,
        content_type: str | None = None,
        detail: bool = False,
    ) -> dict:
        """Get file operation info from the Calkit API."""
        endpoint = f"/projects/{owner}/{project}/fs-ops"
        request_body: dict[str, Any] = {
            "operation": operation,
            "path": path,
            "detail": detail,
        }
        if content_length is not None:
            request_body["content_length"] = content_length
        if content_type is not None:
            request_body["content_type"] = content_type
        resp = calkit.cloud.post(
            endpoint, json=request_body, base_url=self.base_url
        )
        # Validate response has required fields
        if "backend" not in resp:
            raise ValueError(
                f"Invalid API response: {resp}; Expected 'backend' field"
            )
        return resp

    def _execute_operation(
        self,
        operation_info: dict[str, Any],
        operation: str,
        data: bytes | None = None,
        headers: dict | None = None,
    ) -> requests.Response:
        """Execute a file operation using the provided operation info."""
        # Extract access info from the operation info
        access = operation_info.get("access")
        if not access:
            raise ValueError("Missing 'access' field in operation info")
        kind = access.get("kind")
        if not kind:
            raise ValueError("Missing 'kind' field in access info")
        # Handle different access types
        if kind == "presigned-url":
            # Simple presigned URL - just make the HTTP request
            url = access.get("url")
            if not url:
                raise ValueError("Missing 'url' field for presigned-url")
            http_method = access.get("http_method") or (
                "PUT" if operation == "put" else "GET"
            )
            request_headers = dict(access.get("headers") or {})
            if headers:
                request_headers.update(headers)
            params = access.get("params")
            return self._session.request(
                method=http_method.upper(),
                url=url,
                headers=request_headers,
                params=params,
                data=data,
                timeout=120,
            )
        elif kind == "http-request":
            # Generic HTTP request with custom headers
            url = access.get("url")
            if not url:
                raise ValueError("Missing 'url' field for http-request")
            http_method = access.get("http_method") or (
                "PUT" if operation == "put" else "GET"
            )
            request_headers = dict(access.get("headers") or {})
            if headers:
                request_headers.update(headers)
            params = access.get("params")
            return self._session.request(
                method=http_method.upper(),
                url=url,
                headers=request_headers,
                params=params,
                data=data,
                timeout=120,
            )
        elif kind == "presigned-multipart":
            # S3 multipart upload using server-provided part URLs
            if data is None:
                raise ValueError("Data required for multipart upload")
            upload_id = access.get("upload_id")
            part_urls = access.get("part_urls")
            complete_url = access.get("complete_url")
            part_size = access.get("part_size_bytes")
            if not upload_id:
                raise ValueError(
                    "Missing 'upload_id' field for presigned-multipart"
                )
            if not isinstance(part_urls, list) or len(part_urls) == 0:
                raise ValueError(
                    "Missing or invalid 'part_urls' for presigned-multipart"
                )
            if not complete_url:
                raise ValueError(
                    "Missing 'complete_url' for presigned-multipart"
                )
            if not isinstance(part_size, int) or part_size <= 0:
                raise ValueError(
                    "Missing or invalid 'part_size_bytes' for "
                    "presigned-multipart"
                )
            content_type = access.get(
                "content_type", "application/octet-stream"
            )
            total_parts_needed = (len(data) + part_size - 1) // part_size
            if total_parts_needed > len(part_urls):
                raise ValueError(
                    "Insufficient part URLs for multipart upload "
                    f"(need {total_parts_needed}, got {len(part_urls)})"
                )
            uploaded_parts: list[tuple[int, str]] = []
            for part_num in range(1, total_parts_needed + 1):
                start = (part_num - 1) * part_size
                end = min(start + part_size, len(data))
                part_data = data[start:end]
                part_url = part_urls[part_num - 1]
                part_resp = self._session.put(
                    part_url,
                    headers={"Content-Type": content_type},
                    data=part_data,
                    timeout=120,
                )
                part_resp.raise_for_status()
                etag = part_resp.headers.get("ETag")
                if not etag:
                    raise ValueError(
                        f"Missing ETag for uploaded multipart part {part_num}"
                    )
                uploaded_parts.append((part_num, etag.strip()))
            complete_root = ET.Element("CompleteMultipartUpload")
            for part_num, etag in uploaded_parts:
                part_el = ET.SubElement(complete_root, "Part")
                ET.SubElement(part_el, "PartNumber").text = str(part_num)
                ET.SubElement(part_el, "ETag").text = etag
            complete_body = ET.tostring(
                complete_root, encoding="utf-8", xml_declaration=True
            )
            complete_resp = self._session.post(
                complete_url,
                headers={"Content-Type": "application/xml"},
                data=complete_body,
                timeout=120,
            )
            complete_resp.raise_for_status()
            return complete_resp
        elif kind == "presigned-chunked":
            # GCS resumable upload - requires multiple requests
            if data is None:
                raise ValueError("Data required for chunked upload")
            init_url = access.get("init_url")
            if not init_url:
                raise ValueError(
                    "Missing 'init_url' field for presigned-chunked"
                )
            chunk_size = access.get("chunk_size_bytes", 5 * 1024 * 1024)
            content_type = access.get(
                "content_type", "application/octet-stream"
            )
            init_method = access.get("http_method", "POST")
            init_params = access.get("params")
            # Step 1: Initiate resumable upload
            init_headers = dict(access.get("headers") or {})
            init_headers["Content-Type"] = content_type
            init_headers["Content-Length"] = "0"  # Init request has no body
            init_resp = self._session.request(
                method=init_method.upper(),
                url=init_url,
                headers=init_headers,
                params=init_params,
                timeout=30,
            )
            init_resp.raise_for_status()
            # Get the session URI from the Location header
            session_uri = init_resp.headers.get("Location")
            if not session_uri:
                raise ValueError(
                    "Failed to get session URI from resumable upload init response. "
                    "Expected 'Location' header."
                )
            # Step 2: Upload data in chunks
            total_size = len(data)
            offset = 0
            while offset < total_size:
                chunk_end = min(offset + chunk_size, total_size)
                chunk_data = data[offset:chunk_end]
                # Set Content-Range header for the chunk
                chunk_headers = {
                    "Content-Length": str(len(chunk_data)),
                    "Content-Range": f"bytes {offset}-{chunk_end - 1}/{total_size}",
                }
                chunk_resp = self._session.put(
                    session_uri,
                    headers=chunk_headers,
                    data=chunk_data,
                    timeout=120,
                )
                # Check response
                if chunk_resp.status_code == 308:
                    # Resume Incomplete - continue uploading
                    offset = chunk_end
                elif chunk_resp.status_code in (200, 201):
                    # Upload complete
                    return chunk_resp
                else:
                    # Unexpected status
                    chunk_resp.raise_for_status()
                    raise ValueError(
                        f"Unexpected status code during chunked upload: {chunk_resp.status_code}"
                    )
            # If we reach here, the upload completed without getting a 200/201
            # This shouldn't happen, but handle it gracefully
            raise ValueError(
                "Chunked upload completed but no success response received"
            )
        elif kind == "sftp":
            # SFTP access
            raise NotImplementedError("SFTP access not yet implemented")
        else:
            raise ValueError(f"Unsupported access kind: {kind}")

    def _open(
        self,
        path: str,
        mode: str = "rb",
        block_size: int | None = None,
        autocommit: bool = True,
        cache_options: dict | None = None,
        **kwargs,
    ) -> CalkitFile:
        """Open a file for reading or writing."""
        owner, project, file_path = _parse_path(path)
        return CalkitFile(
            self,
            path,
            mode,
            block_size,
            autocommit,
            owner=owner,
            project=project,
            file_path=file_path,
            cache_options=cache_options,
            **kwargs,
        )

    def ls(
        self, path: str, detail: bool = False, refresh: bool = False, **kwargs
    ) -> list[str] | list[dict]:
        """List files in a directory."""
        owner, project, file_path = _parse_path(path)
        # Get operation info from API
        operation_info = self._get_fs_op_info(
            owner, project, file_path, operation="list", detail=detail
        )
        # Check if server provided the result directly
        if "result" in operation_info:
            paths = operation_info["result"].get("paths", [])
        else:
            # Server returned instructions; execute the operation
            resp = self._execute_operation(operation_info, "list")
            resp.raise_for_status()
            result = resp.json()
            paths = result.get("paths", [])
        # Ensure paths have the protocol-stripped format expected by fsspec
        # Format depends on detail flag:
        # - detail=False: list of strings (paths without protocol)
        # - detail=True: list of dicts with 'name', 'size', 'type' keys
        if detail:
            # If paths is already a list of dicts, return as-is
            # Otherwise, convert strings to minimal dict format
            if paths and isinstance(paths[0], dict):
                return paths
            else:
                # Convert list of strings to list of dicts
                return [
                    {"name": p, "size": None, "type": "file"} for p in paths
                ]
        else:
            # Return list of strings
            if paths and isinstance(paths[0], dict):
                return [p["name"] for p in paths]
            else:
                return paths

    def find(
        self, path, maxdepth=None, withdirs=False, detail=False, **kwargs
    ):
        """Recursively find all files under a path."""
        owner, project, file_path = _parse_path(path)
        operation_info = self._get_fs_op_info(
            owner, project, file_path, operation="find", detail=detail
        )
        # Check if server provided the result directly
        if "result" in operation_info:
            paths = operation_info["result"].get(
                "paths", [] if not detail else {}
            )
        else:
            # Server returned instructions; execute the operation
            resp = self._execute_operation(operation_info, "find")
            resp.raise_for_status()
            result = resp.json()
            paths = result.get("paths", [] if not detail else {})

        # Normalize the paths format:
        # - detail=False: list of strings
        # - detail=True: dict mapping path -> info dict
        if detail:
            # Convert to dict format if it's a list
            if isinstance(paths, list):
                if paths and isinstance(paths[0], dict):
                    # List of dicts - convert to dict mapping name -> info
                    paths = {p["name"]: p for p in paths}
                else:
                    # List of strings - convert to dict with minimal info
                    paths = {
                        p: {"name": p, "size": None, "type": "file"}
                        for p in paths
                    }
        else:
            # Convert to list format if it's a dict
            if isinstance(paths, dict):
                paths = list(paths.keys())
            # Ensure it's a list of strings
            elif paths and isinstance(paths[0], dict):
                paths = [p["name"] for p in paths]

        # Apply maxdepth filtering if needed
        if maxdepth is not None:
            base_depth = file_path.count("/") if file_path else 0
            if detail and isinstance(paths, dict):
                paths = {
                    p: info
                    for p, info in paths.items()
                    if p.count("/") - base_depth <= maxdepth
                }
            elif detail:
                paths = {}
            else:
                paths = [
                    p for p in paths if p.count("/") - base_depth <= maxdepth
                ]
        # Filter out directories if not requested
        if not withdirs:
            if detail and isinstance(paths, dict):
                paths = {
                    p: info
                    for p, info in paths.items()
                    if info.get("type") == "file"
                }
            else:
                # When detail=False, we don't have type info in the list
                # The backend should handle this by only returning files
                pass
        return paths

    def exists(self, path: str, **kwargs) -> bool:
        """Check if a path exists."""
        owner, project, file_path = _parse_path(path)
        operation_info = self._get_fs_op_info(
            owner, project, file_path, operation="exists"
        )
        if "result" in operation_info:
            return operation_info["result"].get("exists", False)
        resp = self._execute_operation(operation_info, "exists")
        resp.raise_for_status()
        result = resp.json()
        return result.get("exists", False)

    def info(self, path: str, **kwargs) -> dict:
        """Get file metadata (name, size, type)."""
        owner, project, file_path = _parse_path(path)
        operation_info = self._get_fs_op_info(
            owner, project, file_path, operation="info"
        )
        if "result" in operation_info:
            result = operation_info["result"]
            return {
                "name": result.get("name", file_path),
                "size": result.get("size", 0),
                "type": result.get("type", "file"),
                "time_modified": result.get("time_modified"),
            }
        resp = self._execute_operation(operation_info, "info")
        resp.raise_for_status()
        result = resp.json()
        return {
            "name": result.get("name", file_path),
            "size": result.get("size", 0),
            "type": result.get("type", "file"),
            "time_modified": result.get("time_modified"),
        }

    def cat_file(
        self,
        path: str,
        start: int | None = None,
        end: int | None = None,
        **kwargs,
    ) -> bytes:
        """Read file contents."""
        owner, project, file_path = _parse_path(path)
        # Get file operation info from API (one API call per file)
        operation_info = self._get_fs_op_info(
            owner, project, file_path, operation="get"
        )
        # Add Range header if reading a specific byte range
        headers = {}
        if start is not None and end is not None:
            headers["Range"] = f"bytes={start}-{end - 1}"
        elif start is not None:
            headers["Range"] = f"bytes={start}-"
        elif end is not None:
            headers["Range"] = f"bytes=0-{end - 1}"
        # Execute the get operation
        resp = self._execute_operation(operation_info, "get", headers=headers)
        resp.raise_for_status()
        return resp.content

    def rm_file(self, path: str, **kwargs):
        """Delete a file."""
        owner, project, file_path = _parse_path(path)
        # Get file operation info from API
        operation_info = self._get_fs_op_info(
            owner, project, file_path, "delete"
        )
        # Execute the delete operation
        resp = self._execute_operation(operation_info, "delete")
        resp.raise_for_status()

    def mv(self, path1: str, path2: str, **kwargs):
        """Move or rename a file (copy + delete)."""
        self.copy(path1, path2, **kwargs)
        self.rm_file(path1, **kwargs)

    def cp_file(self, path1: str, path2: str, **kwargs):
        """Copy a file."""
        with self.open(path1, "rb") as src:
            data = src.read()
        # For binary write to a file, pass the bytes directly
        with self.open(path2, "wb") as dst:
            dst.write(data)  # type: ignore[arg-type]

    def makedir(self, path, create_parents=True, **kwargs):
        """Create a directory (no-op for object storage).

        TODO: Handle other backends when they are supported.
        """
        pass

    def makedirs(self, path, exist_ok=False):
        """Create directories (no-op for object storage).

        TODO: Handle other backends when they are supported.
        """
        pass


class CalkitFile(AbstractBufferedFile):
    """A file-like object for reading/writing from Calkit cloud storage.

    This class handles buffering and delegates actual I/O to the underlying
    storage backend (GCS, S3, Google Drive, Box, etc.) via the Calkit API.

    Attributes
    ----------
    owner : str
        Calkit owner/username
    project : str
        Calkit project name
    file_path : str
        Path within the project
    operation_info : dict | None
        Cached operation info from API (contains backend details)
    uploaded_bytes : int
        Total bytes uploaded (for tracking)
    """

    def __init__(
        self,
        fs: CalkitFileSystem,
        path: str,
        mode: str = "rb",
        block_size: int | None = None,
        autocommit: bool = True,
        owner: str | None = None,
        project: str | None = None,
        file_path: str | None = None,
        cache_options: dict | None = None,
        **kwargs,
    ):
        self.owner = owner
        self.project = project
        self.file_path = file_path
        self.operation_info = None  # Cached operation info from API
        self.uploaded_bytes = 0  # Track total bytes uploaded
        # fsspec expects block_size to be an integer, not None
        if block_size is None:
            block_size = 5 * 1024 * 1024  # Default 5MB
        super().__init__(
            fs,
            path,
            mode=mode,
            block_size=block_size,  # type: ignore[arg-type]
            autocommit=autocommit,
            cache_options=cache_options,
            **kwargs,
        )

    def _fetch_range(self, start: int, end: int) -> bytes:
        """Fetch a byte range from the file."""
        if self.operation_info is None:
            # Get file operation info from API
            self.operation_info = self.fs._get_fs_op_info(
                self.owner, self.project, self.file_path, "get"
            )
        # Add Range header for partial content
        # For backends where range is unsupported, the Calkit Cloud API can
        # choose to ignore this header or return a backend-specific request
        # configuration
        headers = {"Range": f"bytes={start}-{end - 1}"}
        # Execute the get operation with range header
        resp = self.fs._execute_operation(
            self.operation_info, "get", headers=headers
        )
        resp.raise_for_status()
        return resp.content

    def _upload_chunk(self, final: bool = False) -> int:
        """Upload buffered data to cloud storage."""
        if not final:
            # For non-final chunks, we don't upload yet (buffer accumulates)
            return 0
        # Get the data to upload from the buffer
        if self.buffer is None:
            return 0
        data = self.buffer.getvalue()
        ndata = len(data)
        if ndata == 0:
            return 0
        if self.operation_info is None:
            raise RuntimeError(
                "Upload not initiated. Call _initiate_upload first."
            )
        self.operation_info = self.fs._get_fs_op_info(
            self.owner,
            self.project,
            self.file_path,
            "put",
            content_length=ndata,
            content_type="application/octet-stream",
        )
        # Execute the put operation
        resp = self.fs._execute_operation(
            self.operation_info,
            "put",
            data=data,
        )
        resp.raise_for_status()
        self.uploaded_bytes += ndata
        # Clear the buffer after successful upload
        self.buffer = io.BytesIO()
        return ndata

    def _initiate_upload(self):
        """Get upload credentials from the Calkit API."""
        self.operation_info = self.fs._get_fs_op_info(
            self.owner, self.project, self.file_path, "put"
        )
