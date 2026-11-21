"""A filesystem-like object that follows ``fsspec`` and interacts with Calkit
object storage to unify operations between private and public storage.

The basic operation is as follows:
1. Make a request to the Calkit API over HTTP to get file operation info.
2. The API returns access details based on the configured storage backend.
3. Use the access details (presigned URL, OAuth, etc.) to perform the operation.

Path format:
    ck://owner/project/path/to/file

    - owner: Calkit username/organization
    - project: Project name
    - path/to/file: File path within the project (optional)

Supported storage backends (via the Calkit hub API):
    - Google Cloud Storage (GCS) - presigned URLs
    - Amazon S3 - presigned URLs
    - Google Drive - OAuth + API
    - Box - OAuth + API
    - Other storage providers as configured in the hub

Multi-backend support:
    By default, the filesystem routes to the Calkit hub API endpoint
    of the active hub (CALKIT_HUB, the project's declared hub, or
    default_hub). To use a different Calkit hub:

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
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from typing import Any, Callable, Sequence
from urllib.parse import urlparse

import requests
from fsspec import AbstractFileSystem
from fsspec.callbacks import DEFAULT_CALLBACK
from fsspec.spec import AbstractBufferedFile
from fsspec.utils import stringify_path
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError, Timeout

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

# DVC object paths are named by their content's MD5
_DVC_MD5_PATH_RE = re.compile(
    r"(?:^|/)files/md5/([0-9a-f]{2})/([0-9a-f]{30})$"
)


def _check_dvc_md5(file_path: str, local_path: str) -> None:
    """Check a downloaded DVC object against the MD5 in its path.

    Storage the hub routes to may be editable outside of Calkit, so this
    turns a wrong object into an error rather than bad data.
    """
    import hashlib

    match = _DVC_MD5_PATH_RE.search(file_path)
    if match is None:
        return
    expected = match.group(1) + match.group(2)
    md5 = hashlib.md5()
    with open(local_path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            md5.update(block)
    if md5.hexdigest() != expected:
        os.remove(local_path)
        raise OSError(
            f"Downloaded content for {file_path} doesn't match its MD5 "
            f"(got {md5.hexdigest()})"
        )


def _import_hf_xet() -> Any:
    try:
        import hf_xet
    except ImportError as e:
        raise RuntimeError(
            "This project's storage is on Hugging Face, which needs the "
            "hf-xet package, and it isn't available on this platform"
        ) from e
    return hf_xet


class _Batcher:
    """Send what concurrent callers submit in as few calls as possible.

    A caller with nothing in flight sends what's waiting right away, so no
    delay is added, and items submitted meanwhile go in the next call.
    ``send`` returns an outcome per item, which ``submit`` returns to that
    item's caller, or raises if it's an exception, as it does whatever
    ``send`` raises.
    """

    def __init__(
        self, send: Callable[[list[Any]], list[Any]], max_size: int = 1000
    ) -> None:
        self._send = send
        self._max_size = max_size
        self._cond = threading.Condition()
        self._waiting: list[SimpleNamespace] = []
        self._sending = False

    def submit(self, item: Any) -> Any:
        entry = SimpleNamespace(item=item, done=False, outcome=None)
        with self._cond:
            self._waiting.append(entry)
            while not entry.done:
                if self._sending:
                    self._cond.wait()
                    continue
                self._sending = True
                batch = self._waiting[: self._max_size]
                del self._waiting[: self._max_size]
                self._cond.release()
                try:
                    outcomes = self._send([b.item for b in batch])
                except BaseException as exc:
                    outcomes = [exc] * len(batch)
                finally:
                    self._cond.acquire()
                for b, outcome in zip(batch, outcomes):
                    b.done, b.outcome = True, outcome
                self._sending = False
                self._cond.notify_all()
        if isinstance(entry.outcome, BaseException):
            raise entry.outcome
        return entry.outcome


# What a batched transfer returns for a file it can't send with Xet, e.g.,
# one in the hub's own storage, which the caller then sends on its own
_NOT_XET = object()


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
    """An fsspec-compatible filesystem for Calkit hub storage.

    This filesystem makes requests to the Calkit API to get file operation
    information, then uses the appropriate method to interact with the
    underlying storage backend.

    The Calkit hub API acts as a compatibility layer that:

    - Determines which storage backend is configured for each project
    - Returns appropriate access credentials (presigned URLs, OAuth tokens,
      etc.)
    - Supports GCS, S3, Google Drive, Box, Azure, and other providers

    Path format: ck://owner/project/path/to/file

    Users can organize their files however they want. For example:

    - DVC will automatically organize by MD5 hashes
    - Users can create subdirectories for organization (data/, models/, etc.)
    - Files can be stored at the project root

    Endpoints are configured via:

    - endpointurl parameter (for DVC remotes): Route to different Calkit
      instances
    - endpoint_url query parameter (for URIs): Ad-hoc endpoint specification
    - the active hub: CALKIT_HUB, the working directory project's declared
      ``hub``, or the ``default_hub`` config value
    - Defaults to calkit.io when unspecified

    This design allows for:

    - Multiple storage backend support without client-side changes
    - Multiple storage backends with configurable endpoints
    - Future protocol upgrades (e.g., SFTP) without breaking API compatibility
    - Unified interface regardless of underlying storage provider

    Attributes
    ----------
    protocol : str
        The protocol scheme for this filesystem ("ck")
    base_url : str
        The Calkit hub API endpoint URL, configured via endpointurl in DVC
        config, endpoint_url in URI query, or the active hub.
        Defaults to production (https://api.calkit.io) when unspecified.
    """

    protocol = "ck"

    def __init__(self, *args, **kwargs):
        """Initialize the filesystem."""
        super().__init__(*args, **kwargs)
        self._session = requests.Session()
        self._base_url = kwargs.get("endpoint_url")
        # Xet access by (owner, project, "put" or "get"), which covers the
        # whole bucket, so it's reused until it's about to expire
        self._xet_access: dict[tuple[str, str, str], dict[str, Any]] = {}
        # (xet_hash, size) by (owner, project, path), from info, so a
        # download needn't ask the hub for them
        self._xet_objects: dict[tuple[str, str, str], tuple[str, int]] = {}
        # Projects known to be in HF storage
        self._xet_projects: set[tuple[str, str]] = set()
        # Batches concurrent transfers by (owner, project, "put" or "get")
        self._xet_batchers: dict[tuple[str, str, str], _Batcher] = {}

    @property
    def base_url(self) -> str:
        """Get the base URL for the Calkit hub API."""
        return self._base_url or calkit.hub.get_base_url()

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
        resp = calkit.hub.post(
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
        resp = calkit.hub.post(
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
        file_obj: Any = None,
        file_size: int | None = None,
        headers: dict | None = None,
        callback=DEFAULT_CALLBACK,
    ) -> requests.Response:
        """Execute a file operation using the provided operation info.

        Exactly one of ``data`` or ``file_obj`` should be provided for put
        operations. When ``file_obj`` is given it must be a seekable binary
        file-like object and ``file_size`` must be set; part/chunk bodies are
        streamed from it instead of being held in memory, which keeps memory
        bounded for large uploads.
        """
        if data is not None and file_obj is not None:
            raise ValueError("Provide data or file_obj, not both")
        if file_obj is not None:
            if not callable(getattr(file_obj, "seek", None)):
                raise TypeError(
                    "file_obj must be a seekable binary file-like object"
                )
            if file_size is None:
                raise ValueError(
                    "file_size must be provided when file_obj is given"
                )
        # Total payload size for progress reporting.
        payload_size = len(data) if data is not None else (file_size or 0)
        # Retries are intentionally narrow: transient transport errors and
        # transient 5xx responses from the storage backend (e.g. GCS/S3
        # returning 503 under load). Non-5xx statuses (308 resume acks, 404,
        # etc.) are returned to the caller untouched.
        max_retries = 2
        retry_backoff = 1.0
        transient_statuses = (500, 502, 503, 504)

        def _request_with_retry(func):
            delay = retry_backoff
            for attempt in range(max_retries + 1):
                try:
                    resp = func()
                except (Timeout, RequestsConnectionError):
                    if attempt >= max_retries:
                        raise
                else:
                    status = getattr(resp, "status_code", None)
                    if (
                        status not in transient_statuses
                        or attempt >= max_retries
                    ):
                        return resp
                if delay > 0:
                    time.sleep(delay)
                    delay *= 2

        def _prepare_stream(request_headers: dict) -> Any:
            """Return the request body, setting Content-Length if streaming."""
            if data is not None:
                return data
            if file_obj is None:
                return None
            file_obj.seek(0)
            # Explicit Content-Length avoids chunked transfer-encoding, which
            # presigned URL signatures typically reject.
            request_headers.setdefault("Content-Length", str(file_size))
            return file_obj

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
            resp = _request_with_retry(
                lambda: self._session.request(
                    method=http_method.upper(),
                    url=url,
                    headers=request_headers,
                    params=params,
                    data=_prepare_stream(request_headers),
                    timeout=120,
                )
            )
            if operation == "put" and payload_size:
                callback.relative_update(payload_size)
            return resp
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
            resp = _request_with_retry(
                lambda: self._session.request(
                    method=http_method.upper(),
                    url=url,
                    headers=request_headers,
                    params=params,
                    data=_prepare_stream(request_headers),
                    timeout=120,
                )
            )
            if operation == "put" and payload_size:
                callback.relative_update(payload_size)
            return resp
        elif kind == "presigned-multipart":
            # S3 multipart upload using server-provided part URLs
            if data is None and file_obj is None:
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
            total_bytes = len(data) if data is not None else int(file_size)
            total_parts_needed = (total_bytes + part_size - 1) // part_size
            if total_parts_needed > len(part_urls):
                raise ValueError(
                    "Insufficient part URLs for multipart upload "
                    f"(need {total_parts_needed}, got {len(part_urls)})"
                )
            uploaded_parts: list[tuple[int, str]] = []
            for part_num in range(1, total_parts_needed + 1):
                start = (part_num - 1) * part_size
                end = min(start + part_size, total_bytes)
                if data is not None:
                    part_data = data[start:end]
                else:
                    file_obj.seek(start)
                    part_data = file_obj.read(end - start)
                part_url = part_urls[part_num - 1]
                part_headers = {}
                if content_type:
                    part_headers["Content-Type"] = str(content_type)
                part_resp = _request_with_retry(
                    lambda: self._session.put(
                        part_url,
                        headers=part_headers,
                        data=part_data,
                        timeout=120,
                    )
                )
                part_resp.raise_for_status()
                etag = part_resp.headers.get("ETag")
                if not etag:
                    raise ValueError(
                        f"Missing ETag for uploaded multipart part {part_num}"
                    )
                uploaded_parts.append((part_num, etag.strip()))
                callback.relative_update(len(part_data))
            complete_root = ET.Element("CompleteMultipartUpload")
            for part_num, etag in uploaded_parts:
                part_el = ET.SubElement(complete_root, "Part")
                ET.SubElement(part_el, "PartNumber").text = str(part_num)
                ET.SubElement(part_el, "ETag").text = etag
            complete_body = ET.tostring(
                complete_root, encoding="utf-8", xml_declaration=True
            )
            complete_resp = _request_with_retry(
                lambda: self._session.post(
                    complete_url,
                    headers={"Content-Type": "application/xml"},
                    data=complete_body,
                    timeout=120,
                )
            )
            complete_resp.raise_for_status()
            return complete_resp
        elif kind == "presigned-chunked":
            # GCS resumable upload - requires multiple requests
            if data is None and file_obj is None:
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
            init_resp = _request_with_retry(
                lambda: self._session.request(
                    method=init_method.upper(),
                    url=init_url,
                    headers=init_headers,
                    params=init_params,
                    timeout=30,
                )
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
            total_size = len(data) if data is not None else int(file_size)
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
                    if data is not None:
                        chunk_data = data[offset:chunk_end]
                    else:
                        file_obj.seek(offset)
                        chunk_data = file_obj.read(chunk_end - offset)
                    # Set Content-Range header for the chunk
                    chunk_headers = {
                        **chunk_headers_base,
                        "Content-Length": str(len(chunk_data)),
                        "Content-Range": (
                            f"bytes {offset}-{chunk_end - 1}/{total_size}"
                        ),
                    }
                    chunk_resp = _request_with_retry(
                        lambda: self._session.request(
                            method=chunk_upload_method.upper(),
                            url=session_uri,
                            headers=chunk_headers,
                            params=access.get("chunk_params"),
                            data=chunk_data,
                            timeout=120,
                        )
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
                        callback.relative_update(next_offset - offset)
                        offset = next_offset
                    elif chunk_resp.status_code in (200, 201):
                        # Final success is only valid when sending the final
                        # range
                        if chunk_end != total_size:
                            raise ValueError(
                                "Chunked upload returned success before all "
                                "bytes were sent"
                            )
                        callback.relative_update(chunk_end - offset)
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
        elif kind == "hf-xet":
            raise ValueError(
                "hf-xet access is handled by the transfer methods, "
                "not as an HTTP request"
            )
        else:
            raise ValueError(f"Unsupported access kind: {kind}")

    def _get_xet_access(
        self, owner: str, project: str, operation: str
    ) -> dict[str, Any] | None:
        """Get a project's Xet access from an earlier operation, if it's
        not about to expire.
        """
        access = self._xet_access.get((owner, project, operation))
        if access is None or access["expires_at_unix"] < time.time() + 60:
            return None
        return access

    def _set_xet_access(
        self, owner: str, project: str, operation: str, access: dict[str, Any]
    ) -> None:
        self._xet_access[(owner, project, operation)] = access
        self._xet_projects.add((owner, project))

    def _get_xet_batcher(
        self, owner: str, project: str, operation: str
    ) -> _Batcher:
        """Get what batches a project's concurrent Xet transfers.

        DVC transfers one file per call, from many threads, so batching
        them makes one Xet session and one hub request per batch rather
        than per file.
        """

        def upload(items: list[tuple[str, str, Any]]) -> list[Any]:
            access = self._get_xet_access(owner, project, "put")
            if access is None:
                info = self._get_fs_op_info(owner, project, items[0][0], "put")
                access = info["access"]
                self._set_xet_access(owner, project, "put", access)
            self._xet_upload(owner, project, access, items)
            return [None] * len(items)

        def download(items: list[tuple[str, str, Any]]) -> list[Any]:
            unknown = [
                f"{owner}/{project}/{file_path}"
                for file_path, _, _ in items
                if (owner, project, file_path) not in self._xet_objects
            ]
            if unknown:
                # Records the Xet hash of each that's in HF
                self.info_many(unknown, content=False)
            outcomes: list[Any] = [_NOT_XET] * len(items)
            known = [
                (n, item)
                for n, item in enumerate(items)
                if (owner, project, item[0]) in self._xet_objects
            ]
            if not known:
                return outcomes
            access = self._get_xet_access(owner, project, "get")
            if access is None:
                info = self._get_fs_op_info(
                    owner, project, known[0][1][0], "get"
                )
                access = info.get("access") or {}
                if access.get("kind") != "hf-xet":
                    return outcomes
                self._set_xet_access(owner, project, "get", access)
            errors = self._xet_download(
                owner,
                project,
                access,
                [
                    (file_path, lpath)
                    + self._xet_objects[(owner, project, file_path)]
                    + (callback,)
                    for _, (file_path, lpath, callback) in known
                ],
            )
            for (n, _), error in zip(known, errors):
                outcomes[n] = error
            return outcomes

        key = (owner, project, operation)
        batcher = self._xet_batchers.get(key)
        if batcher is None:
            send = upload if operation == "put" else download
            batcher = self._xet_batchers.setdefault(key, _Batcher(send))
        return batcher

    def _xet_upload(
        self,
        owner: str,
        project: str,
        access: dict[str, Any],
        uploads: Sequence[tuple[str, str | bytes, Any]],
    ) -> None:
        """Upload files or bytes with Xet, then have the hub add them at
        their paths.

        Each upload is its path in the project, a local path or bytes, and a
        progress callback. The Xet token can only upload content, so the
        paths are added by the hub with the storage owner's credential.
        """
        hf_xet = _import_hf_xet()
        files = [u for u in uploads if isinstance(u[1], str)]
        datas = [u for u in uploads if isinstance(u[1], bytes)]
        callbacks = {str(u[1]): u[2] for u in files}
        # Bytes reported per local path, to finish any hf_xet didn't name
        reported: dict[str, int] = {}

        def refresh_token() -> tuple[str, int]:
            info = self._get_fs_op_info(owner, project, uploads[0][0], "put")
            self._set_xet_access(owner, project, "put", info["access"])
            return (
                info["access"]["access_token"],
                info["access"]["expires_at_unix"],
            )

        def update_progress(total_update: Any, item_updates: Any) -> None:
            for update in item_updates:
                callback = callbacks.get(update.item_name)
                if callback is not None:
                    increment = update.bytes_completion_increment
                    callback.relative_update(increment)
                    reported[update.item_name] = (
                        reported.get(update.item_name, 0) + increment
                    )

        args = (
            access["cas_url"],
            (access["access_token"], access["expires_at_unix"]),
            refresh_token,
            update_progress,
            "bucket",
        )
        xet_hashes = {}
        if files:
            lpaths = [str(u[1]) for u in files]
            infos = hf_xet.upload_files(lpaths, *args, skip_sha256=True)
            for (file_path, _, callback), lpath, info in zip(
                files, lpaths, infos
            ):
                xet_hashes[file_path] = info.hash
                remaining = os.path.getsize(lpath) - reported.get(lpath, 0)
                if remaining > 0:
                    callback.relative_update(remaining)
        if datas:
            infos = hf_xet.upload_bytes(
                [u[1] for u in datas], *args, skip_sha256=True
            )
            for (file_path, _, _), info in zip(datas, infos):
                xet_hashes[file_path] = info.hash
        calkit.hub.post(
            f"/projects/{owner}/{project}/fs/ops/batch",
            json={
                "operation": "register",
                "paths": list(xet_hashes),
                "xet_hashes": xet_hashes,
            },
            base_url=self.base_url,
        )

    def _xet_download(
        self,
        owner: str,
        project: str,
        access: dict[str, Any],
        downloads: list[tuple[str, str, str, int, Any]],
    ) -> list[Exception | None]:
        """Download files with Xet and check each against its MD5.

        Each download is its path in the project, a local path, its Xet hash
        and size, and a progress callback. Returns each one's error, if its
        content doesn't match.
        """
        hf_xet = _import_hf_xet()
        infos = []
        callbacks = []
        for _, lpath, xet_hash, size, callback in downloads:
            callback.set_size(size)
            lpath = os.path.abspath(lpath)
            os.makedirs(os.path.dirname(lpath), exist_ok=True)
            if size == 0:
                open(lpath, "wb").close()
                continue
            infos.append(
                hf_xet.PyXetDownloadInfo(
                    destination_path=lpath, hash=xet_hash, file_size=size
                )
            )
            callbacks.append(callback.relative_update)

        def refresh_token() -> tuple[str, int]:
            info = self._get_fs_op_info(owner, project, downloads[0][0], "get")
            self._set_xet_access(owner, project, "get", info["access"])
            return (
                info["access"]["access_token"],
                info["access"]["expires_at_unix"],
            )

        if infos:
            hf_xet.download_files(
                infos,
                access["cas_url"],
                (access["access_token"], access["expires_at_unix"]),
                refresh_token,
                callbacks,
            )
        errors: list[Exception | None] = []
        for file_path, lpath, _, _, _ in downloads:
            try:
                _check_dvc_md5(file_path, os.path.abspath(lpath))
                errors.append(None)
            except Exception as e:
                errors.append(e)
        return errors

    def _xet_read(
        self, owner: str, project: str, file_path: str, access: dict[str, Any]
    ) -> bytes:
        """Read a whole file with Xet, which has no range reads."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            lpath = os.path.join(tmp, "content")
            download = (
                file_path,
                lpath,
                access["xet_hash"],
                access["size"],
                DEFAULT_CALLBACK,
            )
            error = self._xet_download(owner, project, access, [download])[0]
            if error is not None:
                raise error
            with open(lpath, "rb") as f:
                return f.read()

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
        self, paths: list[str], content: bool = True, **kwargs
    ) -> dict[str, dict[str, Any]]:
        """Get metadata for multiple paths in a batch API call.

        With ``content``, each small file's bytes come back too, saving
        a request per file for callers that will read them.
        """
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
                    include=["info", "content"] if content else ["info"],
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
                        if isinstance(info_payload.get("xet_hash"), str):
                            self._xet_objects[(owner, project, file_path)] = (
                                info_payload["xet_hash"],
                                info["size"],
                            )
                            self._xet_projects.add((owner, project))
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
        access = operation_info.get("access") or {}
        if access.get("kind") == "hf-xet":
            return self._xet_read(owner, project, file_path, access)[start:end]
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

    def put_file(
        self,
        lpath,
        rpath,
        callback=DEFAULT_CALLBACK,
        mode="overwrite",
        **kwargs,
    ):
        """Upload a local file to Calkit hub storage.

        Overrides the default fsspec implementation to report progress based
        on actual bytes uploaded rather than bytes written to the local buffer.
        """
        if mode == "create" and self.exists(rpath):
            raise FileExistsError
        if os.path.isdir(lpath):
            self.makedirs(rpath, exist_ok=True)
            return None
        owner, project, file_path = _parse_path(rpath)
        size = os.path.getsize(lpath)
        callback.set_size(size)
        access = self._get_xet_access(owner, project, "put")
        if access is None:
            operation_info = self._get_fs_op_info(
                owner,
                project,
                file_path,
                "put",
                content_length=size,
            )
            access = operation_info.get("access") or {}
            if access.get("kind") == "hf-xet":
                self._set_xet_access(owner, project, "put", access)
        if access.get("kind") == "hf-xet":
            batcher = self._get_xet_batcher(owner, project, "put")
            batcher.submit((file_path, str(lpath), callback))
            return None
        # Stream the file from disk rather than loading it into memory. This
        # keeps RAM bounded when DVC pushes many (or very large) files in
        # parallel via its worker pool.
        with open(lpath, "rb") as f:
            resp = self._execute_operation(
                operation_info,
                "put",
                file_obj=f,
                file_size=size,
                callback=callback,
            )
        resp.raise_for_status()

    def get_file(
        self,
        rpath: str,
        lpath: Any,
        callback: Any = DEFAULT_CALLBACK,
        outfile: Any = None,
        **kwargs: Any,
    ) -> None:
        """Download a file, with Xet when the project's storage uses it."""
        if outfile is not None or not isinstance(lpath, (str, os.PathLike)):
            super().get_file(
                rpath, lpath, callback=callback, outfile=outfile, **kwargs
            )
            return None
        owner, project, file_path = _parse_path(rpath)
        # Batched with other downloads in the same storage, so the hub isn't
        # asked per file
        if (owner, project) in self._xet_projects:
            batcher = self._get_xet_batcher(owner, project, "get")
            item = (file_path, str(lpath), callback)
            if batcher.submit(item) is not _NOT_XET:
                return None
        try:
            operation_info = self._get_fs_op_info(
                owner, project, file_path, "get"
            )
        except Exception:
            # e.g., a directory, which the default implementation handles
            super().get_file(rpath, lpath, callback=callback, **kwargs)
            return None
        access = operation_info.get("access") or {}
        if access.get("kind") == "hf-xet":
            self._set_xet_access(owner, project, "get", access)
            download = (
                file_path,
                str(lpath),
                access["xet_hash"],
                access["size"],
                callback,
            )
            error = self._xet_download(owner, project, access, [download])[0]
            if error is not None:
                raise error
            return None
        # Reuse the operation info so the file doesn't fetch it again
        with self.open(rpath, "rb", **kwargs) as f1:
            f1.operation_info = operation_info
            callback.set_size(getattr(f1, "size", None))
            with open(lpath, "wb") as f2:
                while data := f1.read(self.blocksize):
                    callback.relative_update(f2.write(data))
        return None


class CalkitFile(AbstractBufferedFile):
    """A file-like object for reading/writing from Calkit hub storage.

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
        # Cached operation info from API
        self.operation_info: dict[str, Any] | None = None
        self.uploaded_bytes = 0  # Track total bytes uploaded
        self._xet_content: bytes | None = None
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
        access = self.operation_info.get("access") or {}
        if access.get("kind") == "hf-xet":
            # No range reads with Xet, so read it all once
            if self._xet_content is None:
                self._xet_content = self.fs._xet_read(
                    self.owner, self.project, self.file_path, access
                )
            return self._xet_content[start:end]
        # Add Range header for partial content
        # For backends where range is unsupported, the Calkit hub API can
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
        """Upload buffered data to object storage."""
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
        access = self.operation_info.get("access") or {}
        if access.get("kind") == "hf-xet":
            self.fs._xet_upload(
                self.owner,
                self.project,
                access,
                [(self.file_path, data, DEFAULT_CALLBACK)],
            )
        else:
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
