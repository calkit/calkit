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
    - HuggingFace Hub - OAuth token + API (datasets and models)
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

The design supports future integration with XeT protocol (https://xet.tech/)
for efficient large file transfers without breaking API compatibility.
"""

from __future__ import annotations

import io
import logging
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
        A path like "ck://calkit.io/owner/project/file.txt"

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
    >>> _parse_path("ck://calkit.io/user/proj/file.txt")
    ('user', 'proj', 'file.txt')

    >>> _parse_path("ck://calkit.io/user/proj/data/nested/file.txt")
    ('user', 'proj', 'data/nested/file.txt')

    >>> _parse_path("ck://calkit.io/user/proj")
    ('user', 'proj', '')
    """
    path = stringify_path(path)
    parsed = urlparse(path)

    if parsed.scheme != "ck":
        raise ValueError(f"Invalid scheme: {parsed.scheme}. Expected 'ck'")

    # netloc should be calkit.io (or other domain)
    if parsed.netloc != "calkit.io":
        raise ValueError(
            f"Invalid domain: {parsed.netloc}. Expected 'calkit.io'. "
            "Future support for custom domains may be added."
        )

    path_parts = parsed.path.lstrip("/").split("/")

    # Need at least owner/project
    if len(path_parts) < 2:
        raise ValueError(
            f"Invalid path format: {path}. "
            "Expected ck://calkit.io/owner/project/path/to/file"
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
        protocol_hint: str = "http",
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
        protocol_hint : str, default="http"
            Protocol preference - 'http', 'xet', etc.

        Returns
        -------
        dict
            A dictionary containing:
            - backend: Storage backend type (gcs, s3, google_drive, box, etc.)
            - result: Optional dict with direct answer (for list/exists operations)
            - access_method: How to perform operation (presigned_url, api, request, xet)
            - url: URL for the operation (if method=presigned_url)
            - token: OAuth token (if method=oauth)
            - api_endpoint: API endpoint (if method=api)
            - http_method: Optional HTTP verb override for API-style methods
            - headers: Additional headers to use
            - params: Optional query parameters for the final backend call
            - Additional backend-specific fields

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

        Metadata operation with instructions (Google Drive list):

        >>> {
        ...     "backend": "google_drive",
        ...     "access_method": "api",
        ...     "operation": "list",
        ...     "api_endpoint": "https://www.googleapis.com/drive/v3/files",
        ...     "token": "ya29...",
        ...     "params": {"q": "..."}
        ... }
        """
        endpoint = f"/projects/{owner}/{project}/fs/{operation}/{file_path}"

        try:
            logger.debug(
                f"Requesting {operation} instructions for {owner}/{project}/{file_path} "
                f"[protocol_hint={protocol_hint}]"
            )

            resp = cloud.get(endpoint, params={"protocol": protocol_hint})

            # Validate response has required fields
            if "backend" not in resp:
                # For backward compatibility, assume presigned URL if just 'url' field
                if "url" in resp:
                    logger.debug(
                        "Legacy response format detected, assuming GCS backend"
                    )
                    return {
                        "backend": "gcs",
                        "method": "presigned_url",
                        "url": resp["url"],
                    }
                else:
                    raise ValueError(
                        f"Invalid API response: {resp}. "
                        f"Expected 'backend' and access method fields."
                    )

            logger.debug(
                f"Storage backend: {resp['backend']}, method: {resp.get('method')}"
            )
            return resp

        except Exception as e:
            logger.error(
                f"Failed to get file operation info for {operation} "
                f"{owner}/{project}/{file_path}: {e}"
            )
            raise

    def _execute_xet_operation(
        self,
        operation_info: dict,
        operation: str,
        data: bytes | None = None,
        headers: dict | None = None,
    ) -> requests.Response:  # type: ignore[return-value]
        """Execute a file operation using XeT protocol.

        XeT (https://xet.tech/) is an efficient protocol for version control
        and large file transfers. It's particularly useful for HuggingFace Hub,
        which has native XeT support for faster file access.

        Parameters
        ----------
        operation_info : dict
            Dictionary with XeT endpoint info
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
        NotImplementedError
            If XeT is not yet available in the client SDK
        """
        xet_endpoint = operation_info.get("xet_endpoint")
        if not xet_endpoint:
            raise ValueError(
                "Missing 'xet_endpoint' for XeT method. "
                "Ensure Calkit Cloud API returns XeT endpoint info."
            )

        try:
            import xet as xet_module  # type: ignore[import]  # Optional: xet-python SDK

            # If we successfully import xet, we could use it in the future
            # For now, log and fall back to HTTP
            logger.debug(
                "xet-python is available but direct SDK usage not yet implemented. "
                "Using HTTP fallback for XeT endpoint."
            )
            _ = xet_module  # Use the import to satisfy linters
        except ImportError:
            # xet-python not installed, will use HTTP fallback
            logger.debug(
                "xet-python not installed, using HTTP fallback for XeT endpoint"
            )

        # HTTP fallback for XeT endpoint (used until direct XeT SDK support is added)
        resp = self._session.request(
            method=operation.upper() if operation == "get" else "PUT",
            url=xet_endpoint,
            headers=headers or {},
            data=data,
        )
        return resp  # type: ignore[return-value]

    @staticmethod
    def _normalize_operation_info(
        operation_info: dict[str, Any], operation: str
    ) -> dict[str, Any]:
        """Normalize operation info for consistent execution.

        The Calkit Cloud API is the source of truth and may return provider-specific
        details. This method normalizes legacy and current response shapes.

        The API returns access_method which tells us how to access the file:
        - presigned_url: Direct HTTP with signed URL
        - api: API endpoint with credentials
        - request: Generic HTTP request
        - xet: XeT protocol for HuggingFace

        Parameters
        ----------
        operation_info : dict[str, Any]
            Operation information from the API
        operation : str
            The operation type (get, put, delete)

        Returns
        -------
        dict[str, Any]
            Normalized operation information

        Raises
        ------
        ValueError
            If required fields are missing or method is unsupported
        """
        normalized = dict(operation_info)
        # Support both "access_method" (new) and "method" (legacy)
        method = normalized.get("access_method") or normalized.get(
            "method", "presigned_url"
        )
        normalized["method"] = method

        if method == "presigned_url":
            if "url" not in normalized:
                raise ValueError("Missing 'url' for presigned_url method")
            normalized.setdefault(
                "http_method", normalized.get("http_method", "GET")
            )
            return normalized

        if method == "api":
            if "api_endpoint" not in normalized:
                raise ValueError("Missing 'api_endpoint' for api method")
            normalized.setdefault(
                "http_method", normalized.get("http_method", "GET")
            )
            normalized.setdefault("url", normalized["api_endpoint"])
            return normalized

        if method == "request":
            if "url" not in normalized:
                raise ValueError("Missing 'url' for request method")
            normalized.setdefault(
                "http_method", normalized.get("http_method", "GET")
            )
            return normalized

        if method == "xet":
            return normalized

        raise ValueError(
            f"Unsupported backend method: {method}. "
            "Supported methods: presigned_url, api, request, xet"
        )

    def _execute_operation(
        self,
        operation_info: dict,
        operation: str,
        data: bytes | None = None,
        headers: dict | None = None,
    ) -> requests.Response:
        """Execute a file operation based on the operation info from the API.

        Parameters
        ----------
        operation_info : dict
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
            If backend method is not supported
        requests.HTTPError
            If operation fails
        """
        normalized = self._normalize_operation_info(operation_info, operation)
        method = normalized["method"]
        request_method = normalized.get("http_method", "GET").upper()

        # Merge headers
        request_headers = {}
        if "headers" in normalized:
            request_headers.update(normalized["headers"])
        if headers:
            request_headers.update(headers)
        request_params = normalized.get("params")
        request_timeout = normalized.get("timeout", 120)

        # Handle different backend methods
        if method in ("presigned_url", "api", "request"):
            url = normalized["url"]
            token = normalized.get("token")
            if token and "Authorization" not in request_headers:
                request_headers["Authorization"] = f"Bearer {token}"

            return self._session.request(
                method=request_method,
                url=url,
                headers=request_headers,
                params=request_params,
                data=data,
                timeout=request_timeout,
            )

        elif method == "xet":
            # XeT protocol: Efficient version control & large file transfers
            # HuggingFace Hub supports XeT for faster file access
            # https://xet.tech/
            return self._execute_xet_operation(
                operation_info,
                operation,
                data=data,
                headers=headers,
            )

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
                owner, project, file_path, operation="list"
            )

            # Check if server provided the result directly
            if "result" in operation_info:
                files = operation_info["result"].get("files", [])
            else:
                # Server returned instructions - execute the operation
                resp = self._execute_operation(operation_info, "list")
                resp.raise_for_status()
                result = resp.json()
                files = result.get("files", [])

            if detail:
                return files
            else:
                return [f["name"] for f in files]

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
        ValueError
            If path format is invalid
        """
        owner, project, file_path = _parse_path(path)

        try:
            logger.debug(f"Getting info for {path}")

            # Get operation info from API - use exists operation for metadata
            operation_info = self._get_file_operation_info(
                owner, project, file_path, operation="exists"
            )

            # Check if server provided the result directly
            if "result" in operation_info:
                result = operation_info["result"]
            else:
                # Server returned instructions - execute the operation
                resp = self._execute_operation(operation_info, "exists")
                resp.raise_for_status()
                result = resp.json()

            return {
                "name": file_path,
                "size": result.get("size", 0),
                "type": "file" if result.get("is_file") else "directory",
                "time_modified": result.get("modified_time"),
            }

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
                f"Uploading {ndata} bytes to {self.owner}/{self.project}/{self.file_path}"
            )

            # Execute the put operation
            headers = {"Content-Type": "application/octet-stream"}
            resp = self.fs._execute_operation(
                self.operation_info,
                "put",
                data=data,
                headers=headers,
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

        This method is called by AbstractBufferedFile when opening a file for writing.
        It obtains the operation info (including access credentials) from the Calkit API.

        Raises
        ------
        RuntimeError
            If unable to get operation info
        """
        try:
            logger.debug(
                f"Initiating upload for {self.owner}/{self.project}/{self.file_path}"
            )
            self.operation_info = self.fs._get_file_operation_info(
                self.owner, self.project, self.file_path, "put"
            )
            logger.debug(
                f"Got operation info for upload (backend: {self.operation_info.get('backend')})"
            )

        except Exception:
            logger.error("Failed to initiate upload")
            raise
