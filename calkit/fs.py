"""A filesystem-like object that follows ``fsspec`` and interacts with Calkit
cloud storage to unify operations between private and public storage.

The basic operation is as follows:
1. Make a request to the Calkit API over HTTP to get file operation info.
2. The API returns access details based on the configured storage backend.
3. Use the access details (presigned URL, OAuth, etc.) to perform the operation.

Path format:
    ck://calkit.io/owner/project/path/to/file

    - owner: Calkit username/organization
    - project: Project name
    - path/to/file: File path within the project (optional)

Supported storage backends (via Calkit Cloud API):
    - Google Cloud Storage (GCS) - presigned URLs
    - Amazon S3 - presigned URLs
    - Google Drive - OAuth + API
    - Box - OAuth + API
    - Azure Blob Storage - SAS tokens
    - Other storage providers as configured in Calkit Cloud

Examples:
    # DVC remote (DVC will organize by MD5 hashes automatically)
    ck://calkit.io/petebachant/my-project

    # Subdirectory for organization
    ck://calkit.io/petebachant/my-project/data

    # Direct filesystem usage
    >>> from calkit.fs import CalkitFileSystem
    >>> fs = CalkitFileSystem()
    >>> with fs.open("ck://calkit.io/owner/project/file.txt", "rb") as f:
    ...     content = f.read()

The design supports transparent interaction with multiple cloud storage providers
through a unified API.
"""

from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse

import requests
from fsspec import AbstractFileSystem
from fsspec.spec import AbstractBufferedFile
from fsspec.utils import stringify_path

from . import cloud

logger = logging.getLogger(__name__)


def _parse_path(path: str) -> tuple[str, str, str]:
    """Parse a Calkit path into components.

    Parameters
    ----------
    path : str
        A path in one of these formats:
        - "ck://owner/project/file.txt" (domain inferred from CALKIT_ENV)
        - "ck://calkit.io/owner/project/file.txt" (explicit domain)
        - "ck://staging.calkit.io/owner/project/file.txt"

    The function automatically inserts the default domain (based on CALKIT_ENV)
    when parsing paths with only owner and project components.

    Returns
    -------
    tuple[str, str, str]
        A tuple of (owner, project, file_path)

    Raises
    ------
    ValueError
        If the path format is invalid

    Examples
    --------
    >>> _parse_path("ck://owner/proj/file.txt")
    ('owner', 'proj', 'file.txt')

    >>> _parse_path("ck://calkit.io/owner/proj/file.txt")
    ('owner', 'proj', 'file.txt')

    >>> _parse_path("ck://owner/proj")
    ('owner', 'proj', '')
    """
    path = stringify_path(path)
    parsed = urlparse(path)
    if parsed.scheme == "ck":
        # Check if netloc looks like a domain (has dots or is localhost-based)
        netloc = parsed.netloc
        path_str = parsed.path.lstrip("/")
        if netloc and (
            "." in netloc
            or netloc == "localhost"
            or netloc.startswith("localhost:")
        ):
            # netloc is an explicit domain, use the path as-is
            raw_path = path_str
        elif netloc:
            # netloc is not a domain (e.g., it's an owner name).
            # Treat it as owner/project..., implicitly using default domain.
            raw_path = f"{netloc}/{path_str}" if path_str else netloc
        else:
            # No netloc, use path as-is
            raw_path = path_str
    else:
        # fsspec may pass protocol-stripped paths, e.g.
        # "localhost:8000/owner/project/file" or just "owner/project/file"
        raw_path = path.lstrip("/")
    path_parts = [part for part in raw_path.split("/") if part]
    # For protocol-stripped forms like "localhost:8000/owner/project/file",
    # drop the leading host component if present
    if len(path_parts) >= 3:
        first_part = path_parts[0]
        # Check if this looks like a host (localhost:port or domain with dots)
        if (
            first_part == "localhost"
            or (
                first_part.startswith("localhost:")
                and first_part[10:].isdigit()
            )
            or ("." in first_part and not first_part.startswith("."))
        ):
            path_parts = path_parts[1:]
    # Need at least owner/project
    if len(path_parts) < 2:
        raise ValueError(
            f"Invalid path format: {path}. "
            "Expected ck://owner/project or ck://domain/owner/project"
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
    - Returns appropriate access credentials (presigned URLs, OAuth tokens, etc.)
    - Supports GCS, S3, Google Drive, Box, Azure, and other providers

    Path format: ck://calkit.io/owner/project/path/to/file

    Users can organize their files however they want. For example:

    - DVC will automatically organize by MD5 hashes
    - Users can create subdirectories for organization (data/, models/, etc.)
    - Files can be stored at the project root

    This design allows for:

    - Multiple storage backend support without client-side changes
    - Future protocol upgrades (e.g., XeT) without breaking API compatibility
    - Unified interface regardless of underlying storage provider

    Attributes
    ----------
    protocol : str
        The protocol scheme for this filesystem ("ck")
    """

    protocol = "ck"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session = requests.Session()

    def _get_file_operation_info(
        self,
        owner: str,
        project: str,
        file_path: str,
        operation: str = "get",
        content_length: int | None = None,
        content_type: str | None = None,
        detail: bool = False,
    ) -> dict:
        """Get file operation information from Calkit API.

        The API determines what storage backend is configured for this project
        and returns either:
        1. Direct result (for metadata operations like list/exists)
        2. Instructions on how to perform the operation (for content operations)

        Parameters
        ----------
        owner : str
            Calkit owner/username
        project : str
            Calkit project name
        file_path : str
            The path within the project
        operation : str, default="get"
            Operation type: 'get', 'put', 'delete', 'list', 'exists'
        content_length : int | None, optional
            Content length for put operations (enables chunked uploads)
        content_type : str | None, optional
            Content type for put operations

        Returns
        -------
        dict
            A dictionary containing:
            - backend: Storage backend type (gcs, s3, google-drive, box, hf)
            - result: Optional dict with direct answer
              (for list/exists operations with files or exists keys)
            - access: Optional dict with access details:
              - kind: Access type (presigned-url, presigned-multipart,
                presigned-chunked, http-request, sftp)
              - url/init_url: URL for the operation
              - http_method: HTTP method to use
              - headers: Optional headers to include
              - params: Optional query parameters
              - For chunked: part_size_bytes/chunk_size_bytes,
                estimated_part_count/estimated_chunk_count

        Raises
        ------
        ValueError
            If API response is invalid
        requests.HTTPError
            If API request fails

        Examples
        --------
        Content operation (get file):

        >>> {
        ...     "backend": "gcs",
        ...     "access_method": "presigned_url",
        ...     "url": "https://storage.googleapis.com/...",
        ...     "http_method": "GET"
        ... }

        Metadata operation with direct result (list):

        >>> {
        ...     "backend": "gcs",
        ...     "operation": "list",
        ...     "result": {
        ...         "files": [{"name": "file.txt", "size": 1234}]
        ...     }
        ... }

        Chunked upload operation:

        >>> {
        ...     "backend": "gcs",
        ...     "access": {
        ...         "kind": "presigned-chunked",
        ...         "init_url": "https://storage.googleapis.com/...",
        ...         "http_method": "POST",
        ...         "chunk_size_bytes": 5242880,
        ...         "estimated_chunk_count": 10,
        ...         "upload_size_bytes": 52428800,
        ...         "headers": {"x-goog-resumable": "start"}
        ...     }
        ... }
        """
        endpoint = f"/projects/{owner}/{project}/fs-ops"
        request_body: dict[str, Any] = {
            "operation": operation,
            "file_path": file_path,
            "detail": detail,
        }
        if content_length is not None:
            request_body["content_length"] = content_length
        if content_type is not None:
            request_body["content_type"] = content_type
        try:
            logger.debug(
                f"Requesting {operation} instructions for "
                f"{owner}/{project}/{file_path}"
            )
            resp = cloud.post(endpoint, json=request_body)
            # Validate response has required fields
            if "backend" not in resp:
                raise ValueError(
                    f"Invalid API response: {resp}; Expected 'backend' field"
                )
            access_kind = (
                resp.get("access", {}).get("kind")
                if resp.get("access")
                else None
            )
            logger.debug(
                f"Storage backend: {resp['backend']}, "
                f"access kind: {access_kind}"
            )
            return resp
        except requests.exceptions.HTTPError as e:
            status_code = getattr(
                getattr(e, "response", None), "status_code", None
            )
            message = str(e)
            is_not_found = status_code == 404 or message.startswith("404:")
            if is_not_found:
                target = (
                    f"{owner}/{project}/{file_path}"
                    if file_path
                    else f"{owner}/{project}"
                )
                logger.debug(
                    f"File operation target not found for {operation} "
                    f"{target}: {message}"
                )
                raise FileNotFoundError(
                    f"Not found while requesting '{operation}' operation "
                    f"info for {target}"
                ) from e
            logger.error(
                f"HTTP error getting file operation info for {operation} "
                f"{owner}/{project}/{file_path}: {e}"
            )
            raise
        except Exception as e:
            logger.error(
                f"Failed to get file operation info for {operation} "
                f"{owner}/{project}/{file_path}: {e}"
            )
            raise

    def _execute_operation(
        self,
        operation_info: dict[str, Any],
        operation: str,
        data: bytes | None = None,
        headers: dict | None = None,
    ) -> requests.Response:
        """Execute a file operation based on the operation info from the API.

        Handles different access types:
        - presigned-url: Simple HTTP request to presigned URL
        - presigned-multipart: S3 multipart upload (TODO)
        - presigned-chunked: GCS resumable upload (TODO)
        - http-request: Generic HTTP request with custom headers
        - sftp: SFTP access (TODO)

        Parameters
        ----------
        operation_info : dict[str, Any]
            Dictionary from _get_file_operation_info
        operation : str
            The operation type (get, put, delete)
        data : bytes | None, optional
            Data to upload (for put operations)
        headers : dict | None, optional
            Additional headers

        Returns
        -------
        requests.Response
            Response from the operation

        Raises
        ------
        ValueError
            If access type is not supported or required fields are missing
        requests.HTTPError
            If operation fails
        """
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
                logger.debug(
                    f"Uploading multipart part {part_num}/{total_parts_needed} "
                    f"({len(part_data)} bytes)"
                )
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
            logger.debug(
                f"Completed multipart upload with upload_id={upload_id}"
            )
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
            logger.debug(f"Initiating GCS resumable upload to {init_url}")
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
            logger.debug(f"Got session URI: {session_uri}")
            # Step 2: Upload data in chunks
            total_size = len(data)
            offset = 0
            while offset < total_size:
                chunk_end = min(offset + chunk_size, total_size)
                chunk_data = data[offset:chunk_end]
                logger.debug(
                    f"Uploading chunk: bytes {offset}-{chunk_end - 1}/{total_size - 1}"
                )
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
                    # Server returns Range header with bytes received
                    range_header = chunk_resp.headers.get("Range")
                    if range_header:
                        # Parse range like "bytes=0-524287"
                        logger.debug(f"Server confirmed: {range_header}")
                    offset = chunk_end
                elif chunk_resp.status_code in (200, 201):
                    # Upload complete
                    logger.debug("Upload completed successfully")
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
        """Open a file from Calkit cloud storage.

        Parameters
        ----------
        path : str
            Path like "ck://calkit.io/owner/project/file.txt"
        mode : str, default="rb"
            File mode ('rb', 'wb', 'ab')
        block_size : int | None, optional
            Block size for buffering
        autocommit : bool, default=True
            Whether to commit uploads automatically
        cache_options : dict | None, optional
            Cache options
        **kwargs
            Additional arguments

        Returns
        -------
        CalkitFile
            A CalkitFile object

        Raises
        ------
        ValueError
            If path format is invalid
        """
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
        """List files in a directory.

        Parameters
        ----------
        path : str
            Directory path (ck://calkit.io/owner/project or with subdirectory)
        detail : bool, default=False
            Whether to include file details
        refresh : bool, default=False
            Whether to refresh the cache
        **kwargs
            Additional arguments

        Returns
        -------
        list[str] | list[dict]
            List of file names (if detail=False) or list of dicts with info

        Raises
        ------
        ValueError
            If path format is invalid
        """
        owner, project, file_path = _parse_path(path)
        try:
            logger.debug(f"Listing files in {owner}/{project}/{file_path}")
            # Get operation info from API
            operation_info = self._get_file_operation_info(
                owner, project, file_path, operation="list", detail=detail
            )
            empty = {} if detail else []
            # Check if server provided the result directly
            if "result" in operation_info:
                return operation_info["result"].get("files", empty)
            else:
                # Server returned instructions; execute the operation
                resp = self._execute_operation(operation_info, "list")
                resp.raise_for_status()
                result = resp.json()
                return result.get("files", empty)
        except FileNotFoundError:
            logger.debug(f"Listing path not found (treating as empty): {path}")
            return []
        except Exception as e:
            logger.error(f"Failed to list files in {path}: {e}")
            raise

    def exists(self, path: str, **kwargs) -> bool:
        """Check if a file or directory exists.

        Parameters
        ----------
        path : str
            Path to check (ck://calkit.io/owner/project/file)
        **kwargs
            Additional arguments

        Returns
        -------
        bool
            True if the path exists, False otherwise
        """
        try:
            owner, project, file_path = _parse_path(path)
            logger.debug(f"Checking existence of {path}")
            # Get operation info from API
            operation_info = self._get_file_operation_info(
                owner, project, file_path, operation="exists"
            )
            # Check if server provided the result directly
            if "result" in operation_info:
                return operation_info["result"].get("exists", False)
            else:
                # Server returned instructions - execute the operation
                resp = self._execute_operation(operation_info, "exists")
                resp.raise_for_status()
                result = resp.json()
                return result.get("exists", False)
        except Exception as e:
            logger.debug(f"Path {path} does not exist: {e}")
            return False

    def info(self, path: str, **kwargs) -> dict:
        """Get information about a file.

        Parameters
        ----------
        path : str
            Path to file (ck://calkit.io/owner/project/file)
        **kwargs
            Additional arguments

        Returns
        -------
        dict
            Dictionary with file information including name, size, type, etc.

        Raises
        ------
        FileNotFoundError
            If the file does not exist
        ValueError
            If path format is invalid
        """
        owner, project, file_path = _parse_path(path)
        try:
            logger.debug(f"Getting info for {path}")
            # Get operation info from API - use dedicated info operation
            operation_info = self._get_file_operation_info(
                owner, project, file_path, operation="info"
            )
            # Check if server provided the result directly
            if "result" in operation_info:
                result = operation_info["result"]
                return {
                    "name": result.get("name", file_path),
                    "size": result.get("size", 0),
                    "type": result.get("type", "file"),
                    "time_modified": result.get("time_modified"),
                }
            else:
                # Fallback for servers that don't support info operation
                logger.debug(
                    "Server returned instructions instead of result for info"
                )
                resp = self._execute_operation(operation_info, "info")
                resp.raise_for_status()
                result = resp.json()
                return {
                    "name": result.get("name", file_path),
                    "size": result.get("size", 0),
                    "type": result.get("type", "file"),
                    "time_modified": result.get("time_modified"),
                }
        except FileNotFoundError:
            raise
        except requests.exceptions.HTTPError as e:
            status_code = getattr(
                getattr(e, "response", None), "status_code", None
            )
            if status_code == 404:
                raise FileNotFoundError(f"File not found: {path}") from e
            raise
        except Exception as e:
            logger.error(f"Failed to get info for {path}: {e}")
            raise

    def rm_file(self, path: str, **kwargs):
        """Remove a single file.

        Parameters
        ----------
        path : str
            Path to file (ck://calkit.io/owner/project/file)
        **kwargs
            Additional arguments

        Raises
        ------
        ValueError
            If path format is invalid
        requests.HTTPError
            If deletion fails
        """
        owner, project, file_path = _parse_path(path)
        try:
            logger.debug(f"Deleting file {path}")
            # Get file operation info from API
            operation_info = self._get_file_operation_info(
                owner, project, file_path, "delete"
            )
            # Execute the delete operation
            resp = self._execute_operation(operation_info, "delete")
            resp.raise_for_status()
            logger.debug(f"Successfully deleted {path}")
        except Exception as e:
            logger.error(f"Failed to delete {path}: {e}")
            raise

    def mv(self, path1: str, path2: str, **kwargs):
        """Move or rename a file.

        Parameters
        ----------
        path1 : str
            Source path
        path2 : str
            Destination path
        **kwargs
            Additional arguments

        Notes
        -----
        Currently implemented as copy + delete. In the future, this could
        be optimized with a direct move operation in the API.
        """
        logger.debug(f"Moving {path1} to {path2}")
        self.copy(path1, path2, **kwargs)
        self.rm_file(path1, **kwargs)

    def cp_file(self, path1: str, path2: str, **kwargs):
        """Copy a file.

        Parameters
        ----------
        path1 : str
            Source path
        path2 : str
            Destination path
        **kwargs
            Additional arguments
        """
        logger.debug(f"Copying {path1} to {path2}")
        with self.open(path1, "rb") as src:
            data = src.read()
        # For binary write to a file, pass the bytes directly
        with self.open(path2, "wb") as dst:
            dst.write(data)  # type: ignore[arg-type]


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
        """Fetch a range of bytes from the file.

        Parameters
        ----------
        start : int
            Start byte position
        end : int
            End byte position (exclusive)

        Returns
        -------
        bytes
            Bytes in the range [start, end)

        Raises
        ------
        requests.HTTPError
            If the fetch fails
        """
        if self.operation_info is None:
            # Get file operation info from API
            self.operation_info = self.fs._get_file_operation_info(
                self.owner, self.project, self.file_path, "get"
            )
        try:
            logger.debug(f"Fetching bytes {start}-{end - 1} from {self.path}")
            # Add Range header for partial content. For backends where range is
            # unsupported, the Calkit Cloud API can choose to ignore this header
            # or return a backend-specific request configuration.
            headers = {"Range": f"bytes={start}-{end - 1}"}
            # Execute the get operation with range header
            resp = self.fs._execute_operation(
                self.operation_info, "get", headers=headers
            )
            resp.raise_for_status()
            return resp.content
        except requests.exceptions.RequestException as e:
            logger.error(
                f"Failed to fetch range {start}-{end} from {self.path}: {e}"
            )
            raise

    def _upload_chunk(self, final: bool = False) -> int:
        """Upload a chunk of data.

        This method is called by AbstractBufferedFile to upload buffered data.
        For DVC operations, we typically upload the entire file in one go.

        Parameters
        ----------
        final : bool, default=False
            Whether this is the final chunk (file is being closed)

        Returns
        -------
        int
            Number of bytes uploaded from this chunk

        Raises
        ------
        RuntimeError
            If upload hasn't been initiated
        requests.HTTPError
            If upload fails
        """
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
        try:
            logger.debug(
                f"Uploading {ndata} bytes to "
                f"{self.owner}/{self.project}/{self.file_path}"
            )
            self.operation_info = self.fs._get_file_operation_info(
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
            logger.debug(f"Successfully uploaded {ndata} bytes")
            # Clear the buffer after successful upload
            self.buffer = io.BytesIO()
            return ndata
        except requests.exceptions.RequestException as e:
            logger.error(f"Upload failed for {self.path}: {e}")
            raise

    def _initiate_upload(self):
        """Initiate a file upload.

        This method is called by AbstractBufferedFile when opening a file for
        writing.
        It obtains the operation info (including access credentials) from the
        Calkit Cloud API.

        Raises
        ------
        RuntimeError
            If unable to get operation info
        """
        try:
            logger.debug(
                f"Initiating upload for "
                f"{self.owner}/{self.project}/{self.file_path}"
            )
            self.operation_info = self.fs._get_file_operation_info(
                self.owner, self.project, self.file_path, "put"
            )
            logger.debug(
                f"Got operation info for upload "
                f"(backend: {self.operation_info.get('backend')})"
            )
        except Exception:
            logger.error("Failed to initiate upload")
            raise
