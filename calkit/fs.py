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

import base64
import io
import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse

import requests
from fsspec import AbstractFileSystem
from fsspec.spec import AbstractBufferedFile
from fsspec.utils import stringify_path
from requests.exceptions import HTTPError

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
        self._base_url = kwargs.get("endpoint_url")

    @property
    def base_url(self) -> str:
        """Get the base URL for the Calkit Cloud API."""
        return self._base_url or calkit.cloud.get_base_url()

    @staticmethod
    def _cache_key(owner: str, project: str, file_path: str) -> str:
        return f"{owner}/{project}/{file_path}"

    @staticmethod
    def _normalize_info(
        file_path: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "name": result.get("name", file_path),
            "size": result.get("size", 0),
            "type": result.get("type", "file"),
            "time_modified": result.get("time_modified"),
        }

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
        endpoint = f"/projects/{owner}/{project}/fs/ops"
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

    def _get_fs_op_info_batch(
        self,
        owner: str,
        project: str,
        paths: list[str],
        operation: str,
        include: list[str] | None = None,
        detail: bool = False,
    ) -> dict:
        """Get batch file operation info from the Calkit API."""
        endpoint = f"/projects/{owner}/{project}/fs/ops/batch"
        request_body: dict[str, Any] = {
            "operation": operation,
            "detail": detail,
            "paths": paths,
        }
        if include:
            request_body["include"] = include
        resp = calkit.cloud.post(
            endpoint, json=request_body, base_url=self.base_url
        )
        if "backend" not in resp:
            raise ValueError(
                f"Invalid API response: {resp}; Expected 'backend' field"
            )
        return resp

    def _get_info_for_parsed_path(
        self, owner: str, project: str, file_path: str
    ) -> dict[str, Any]:
        try:
            operation_info = self._get_fs_op_info(
                owner, project, file_path, operation="info"
            )
        except HTTPError as e:
            # If the API returns 404, convert to FileNotFoundError
            if "404" in str(e):
                raise FileNotFoundError(f"ck://{owner}/{project}/{file_path}")
            raise
        if "result" in operation_info:
            info = self._normalize_info(file_path, operation_info["result"])
        else:
            resp = self._execute_operation(operation_info, "info")
            if resp.status_code == 404:
                raise FileNotFoundError(f"ck://{owner}/{project}/{file_path}")
            resp.raise_for_status()
            info = self._normalize_info(file_path, resp.json())
        return info

    def _get_exists_for_parsed_path(
        self, owner: str, project: str, file_path: str
    ) -> bool:
        operation_info = self._get_fs_op_info(
            owner, project, file_path, operation="exists"
        )
        if "result" in operation_info:
            exists = bool(operation_info["result"].get("exists", False))
        else:
            resp = self._execute_operation(operation_info, "exists")
            resp.raise_for_status()
            exists = bool(resp.json().get("exists", False))
        return exists

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
            content_type = access.get("content_type")
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
                part_headers = {}
                if content_type:
                    part_headers["Content-Type"] = str(content_type)
                part_resp = self._session.put(
                    part_url,
                    headers=part_headers,
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
            if not isinstance(chunk_size, int) or chunk_size <= 0:
                raise ValueError(
                    "Missing or invalid 'chunk_size_bytes' for "
                    "presigned-chunked"
                )
            content_type = access.get("content_type")
            init_method = access.get("http_method", "POST")
            init_params = access.get("params")
            chunk_upload_method = access.get("chunk_http_method", "PUT")
            # Step 1: Initiate resumable upload
            init_headers = dict(access.get("headers") or {})
            if content_type:
                init_headers["Content-Type"] = str(content_type)
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
                    "Failed to get session URI from resumable upload init "
                    "response; "
                    "Expected 'Location' header"
                )

            def _cancel_resumable_upload() -> None:
                delete_fn = getattr(self._session, "delete", None)
                if callable(delete_fn):
                    try:
                        delete_fn(session_uri, timeout=30)
                    except Exception:
                        pass

            # Step 2: Upload data in chunks
            total_size = len(data)
            offset = 0
            chunk_headers_base = dict(
                access.get("chunk_headers") or access.get("headers") or {}
            )
            # x-goog-resumable is only required to initiate the session.
            if "chunk_headers" not in access:
                for header_key in list(chunk_headers_base.keys()):
                    if header_key.lower() == "x-goog-resumable":
                        chunk_headers_base.pop(header_key)

            def _parse_next_offset_from_range(
                range_header: str | None,
            ) -> int | None:
                if not range_header:
                    return None
                value = range_header.strip()
                if "=" in value:
                    value = value.split("=", 1)[1].strip()
                if "-" not in value:
                    return None
                start_str, end_str = value.split("-", 1)
                if not start_str.isdigit() or not end_str.isdigit():
                    return None
                start = int(start_str)
                end = int(end_str)
                if start < 0 or end < start:
                    return None
                return end + 1

            try:
                while offset < total_size:
                    chunk_end = min(offset + chunk_size, total_size)
                    chunk_data = data[offset:chunk_end]
                    # Set Content-Range header for the chunk
                    chunk_headers = {
                        **chunk_headers_base,
                        "Content-Length": str(len(chunk_data)),
                        "Content-Range": (
                            f"bytes {offset}-{chunk_end - 1}/{total_size}"
                        ),
                    }
                    chunk_resp = self._session.request(
                        method=chunk_upload_method.upper(),
                        url=session_uri,
                        headers=chunk_headers,
                        params=access.get("chunk_params"),
                        data=chunk_data,
                        timeout=120,
                    )
                    # Check response
                    if chunk_resp.status_code == 308:
                        # Resume incomplete: trust server ack instead of local
                        # send
                        ack_range = chunk_resp.headers.get("Range")
                        next_offset = _parse_next_offset_from_range(ack_range)
                        if next_offset is None:
                            raise ValueError(
                                "Chunked upload received 308 without a valid "
                                "Range acknowledgement"
                            )
                        if next_offset <= offset:
                            raise ValueError(
                                "Chunked upload made no forward progress "
                                f"(offset={offset}, ack={ack_range!r})"
                            )
                        if next_offset > chunk_end:
                            raise ValueError(
                                "Chunked upload ack exceeds bytes sent in the "
                                "current request "
                                f"(sent_end={chunk_end}, ack={ack_range!r})"
                            )
                        if next_offset >= total_size:
                            raise ValueError(
                                "Chunked upload acknowledged full payload with "
                                "status 308 instead of final success"
                            )
                        offset = next_offset
                    elif chunk_resp.status_code in (200, 201):
                        # Final success is only valid when sending the final
                        # range
                        if chunk_end != total_size:
                            raise ValueError(
                                "Chunked upload returned success before all "
                                "bytes were sent"
                            )
                        return chunk_resp
                    else:
                        # Unexpected status
                        chunk_resp.raise_for_status()
                        raise ValueError(
                            "Unexpected status code during chunked upload: "
                            f"{chunk_resp.status_code}"
                        )
            except Exception:
                _cancel_resumable_upload()
                raise
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
            # Handle 404: directory doesn't exist yet, return empty results
            if resp.status_code == 404:
                return [] if not detail else {}
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
        return self._get_exists_for_parsed_path(owner, project, file_path)

    def exists_many(self, paths: list[str], **kwargs) -> list[bool]:
        """Check existence for multiple paths in a batch API call."""
        if not paths:
            return []
        grouped: dict[tuple[str, str], list[tuple[int, str, str]]] = {}
        for idx, path in enumerate(paths):
            owner, project, file_path = _parse_path(path)
            grouped.setdefault((owner, project), []).append(
                (idx, path, file_path)
            )
        results: list[bool | None] = [None] * len(paths)
        for (owner, project), entries in grouped.items():
            file_paths = [file_path for _, _, file_path in entries]
            index_by_file_path = {
                file_path: [idx for idx, _, fp in entries if fp == file_path]
                for file_path in set([fp for _, _, fp in entries])
            }
            try:
                resp = self._get_fs_op_info_batch(
                    owner=owner,
                    project=project,
                    paths=file_paths,
                    operation="exists",
                    include=["exists"],
                )
                batch_results = resp.get("results")
                if isinstance(batch_results, dict):
                    for file_path, value in batch_results.items():
                        exists = bool(
                            value.get("exists", False)
                            if isinstance(value, dict)
                            else value
                        )
                        for idx in index_by_file_path.get(file_path, []):
                            results[idx] = exists
            except Exception:
                pass
            # Fall back to single-path exists for any missing results
            for idx, _, file_path in entries:
                if results[idx] is None:
                    try:
                        results[idx] = self._get_exists_for_parsed_path(
                            owner, project, file_path
                        )
                    except Exception:
                        results[idx] = False
        return [bool(v) for v in results]

    def info(self, path: str, **kwargs) -> dict:
        """Get file metadata (name, size, type)."""
        owner, project, file_path = _parse_path(path)
        return self._get_info_for_parsed_path(owner, project, file_path)

    def info_many(
        self, paths: list[str], **kwargs
    ) -> dict[str, dict[str, Any]]:
        """Get metadata for multiple paths in a batch API call."""
        if not paths:
            return {}
        grouped: dict[tuple[str, str], list[tuple[str, str]]] = {}
        results: dict[str, dict[str, Any]] = {}
        for path in paths:
            owner, project, file_path = _parse_path(path)
            grouped.setdefault((owner, project), []).append((path, file_path))
        for (owner, project), entries in grouped.items():
            file_paths = [file_path for _, file_path in entries]
            paths_by_file_path = {
                file_path: [p for p, fp in entries if fp == file_path]
                for file_path in set([fp for _, fp in entries])
            }
            try:
                resp = self._get_fs_op_info_batch(
                    owner=owner,
                    project=project,
                    paths=file_paths,
                    operation="info",
                    include=["info", "content"],
                )
                batch_results = resp.get("results")
                if isinstance(batch_results, dict):
                    for file_path, value in batch_results.items():
                        if not isinstance(value, dict):
                            continue
                        # Batch API returns shape:
                        # {"info": {...}, "content_base64": "...", ...}
                        info_payload = value.get("info")
                        if not isinstance(info_payload, dict):
                            continue
                        info = self._normalize_info(file_path, info_payload)
                        content_b64 = value.get("content_base64")
                        if isinstance(content_b64, str):
                            try:
                                info["content"] = base64.b64decode(
                                    content_b64, validate=True
                                )
                            except Exception:
                                pass
                        for original_path in paths_by_file_path.get(
                            file_path, []
                        ):
                            results[original_path] = info
            except Exception:
                pass
        return results

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
        # Fast path: use inline content from info/info_many when available.
        try:
            details = self.details
            content = (
                details.get("content") if isinstance(details, dict) else None
            )
            if isinstance(content, (bytes, bytearray)):
                return bytes(content)[start:end]
        except Exception:
            pass
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

    def _upload_chunk(self, final: bool = False) -> int | bool:
        """Upload buffered data to cloud storage."""
        if not final:
            # For non-final chunks, we don't upload yet (buffer accumulates)
            return False
        # Get the data to upload from the buffer
        if self.buffer is None:
            return 0
        data = self.buffer.getvalue()
        ndata = len(data)
        if ndata == 0:
            return 0
        if self.operation_info is None:
            raise RuntimeError(
                "Upload not initiated; Call _initiate_upload first"
            )
        self.operation_info = self.fs._get_fs_op_info(
            self.owner,
            self.project,
            self.file_path,
            "put",
            content_length=ndata,
        )
        # Execute the put operation
        resp = self.fs._execute_operation(
            self.operation_info,
            "put",
            data=data,
        )
        resp.raise_for_status()
        # Verify remote size to prevent silent partial uploads.
        self._verify_remote_size(ndata)
        self.uploaded_bytes += ndata
        # Clear the buffer after successful upload
        self.buffer = io.BytesIO()
        return ndata

    def _verify_remote_size(self, expected_size: int) -> None:
        """Verify uploaded object size matches expected bytes."""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                info = self.fs._get_info_for_parsed_path(
                    self.owner,
                    self.project,
                    self.file_path,
                )
            except Exception:
                info = None
            remote_size = info.get("size") if isinstance(info, dict) else None
            if isinstance(remote_size, int):
                if remote_size == expected_size:
                    return
                raise ValueError(
                    "Remote size mismatch after upload "
                    f"(expected {expected_size}, got {remote_size})"
                )
            if attempt < max_attempts - 1:
                time.sleep(0.25)
        raise ValueError(
            "Unable to verify uploaded object size after write operation"
        )

    def _initiate_upload(self):
        """Get upload credentials from the Calkit API."""
        self.operation_info = self.fs._get_fs_op_info(
            self.owner, self.project, self.file_path, "put"
        )
