"""Functionality for working with InvenioRDM instances like Zenodo."""

import os
import time
from collections.abc import Callable
from functools import partial
from typing import Any, BinaryIO, Literal

import dotenv
import requests
from requests.exceptions import HTTPError

import calkit

ServiceName = Literal["zenodo", "caltechdata"]
DEFAULT_SERVICE: ServiceName = "zenodo"


def get_token(service: ServiceName = DEFAULT_SERVICE) -> str:
    dotenv.load_dotenv()
    config = calkit.config.read()
    if service == "zenodo":
        token = config.zenodo_token
        if token is None:
            token = os.getenv("ZENODO_TOKEN")
        if token is None:
            token = calkit.hub.get("/user/zenodo-token")["access_token"]
        return token
    elif service == "caltechdata":
        token = config.caltechdata_token
        if token is None:
            raise ValueError(f"No token for {service} found")
        return token
    else:
        raise ValueError(f"Unknown archival service '{service}'")


def get_base_url(service: ServiceName = DEFAULT_SERVICE) -> str:
    override = os.getenv(f"CALKIT_INVENIO_BASE_URL_{service.upper()}")
    if override:
        return override
    current_env = calkit.config.get_env()
    if service == "zenodo":
        if (
            current_env in ["local", "test"]
            and not os.getenv("CALKIT_USE_PROD_FOR_TESTS") == "1"
        ):
            return "https://sandbox.zenodo.org/api"
        return "https://zenodo.org/api"
    elif service == "caltechdata":
        if (
            current_env in ["local", "test"]
            and not os.getenv("CALKIT_USE_PROD_FOR_TESTS") == "1"
        ):
            return "https://data.caltechlibrary.dev/api"
        else:
            return "https://data.caltech.edu/api"
    else:
        raise ValueError(f"Unknown archival service '{service}'")


# Pushing a release can mean sending hundreds of megabytes over a slow or
# distant link, so give a response plenty of time to arrive rather than
# letting requests wait forever with no timeout at all.
CONNECT_TIMEOUT = 30
READ_TIMEOUT = 600
# Gateways in front of InvenioRDM return these when they're busy, which says
# nothing about whether the request itself was valid, so it's worth sending
# again after a pause.
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4


def get_timeout() -> tuple[float, float]:
    """Get the connect and read timeouts to use for requests."""
    read = os.getenv("CALKIT_INVENIO_TIMEOUT")
    return CONNECT_TIMEOUT, float(read) if read else READ_TIMEOUT


def _request(
    kind: Literal["get", "post", "put", "patch", "delete"],
    path: str,
    params: dict | None = None,
    json: dict | list | None = None,
    # A dict, bytes, or a file-like object to stream
    data: Any = None,
    headers: dict | None = None,
    auth: bool = True,
    as_json: bool = True,
    service: ServiceName = DEFAULT_SERVICE,
    **kwargs,
):
    if params is None:
        params = {}
    if auth and "access_token" not in params:
        params = params | {"access_token": get_token(service=service)}
    kwargs.setdefault("timeout", get_timeout())
    func = getattr(requests, kind)
    # A POST that timed out may still have been carried out on the far end,
    # e.g., leaving a draft record behind, so only repeat requests that are
    # safe to send twice
    max_attempts = 1 if kind == "post" else MAX_ATTEMPTS
    # A file being streamed as the body has to be sent from the start again
    # on each attempt, not from wherever the last one stopped reading it
    start = data.tell() if hasattr(data, "seek") else None
    for attempt in range(1, max_attempts + 1):
        if start is not None:
            data.seek(start)
        try:
            resp = func(
                get_base_url(service=service) + path,
                params=params,
                json=json,
                data=data,
                headers=headers,
                **kwargs,
            )
        except (requests.ConnectionError, requests.Timeout):
            if attempt == max_attempts:
                raise
            time.sleep(2**attempt)
            continue
        if resp.status_code in RETRY_STATUS_CODES and attempt < max_attempts:
            time.sleep(2**attempt)
            continue
        break
    if resp.status_code >= 400:
        msg = f"{resp.status_code}: "
        try:
            resp_json = resp.json()
            if "message" in resp_json:
                msg += resp_json["message"]
            if "errors" in resp_json:
                msg += f"\nErrors:\n{resp_json['errors']}"
        except ValueError:
            msg += resp.text
        if kind == "post" and resp.status_code in RETRY_STATUS_CODES:
            # The far end may have done the work anyway, and a blind retry
            # would duplicate it, so say so rather than papering over it
            msg += (
                f"\nThis request was not retried automatically, since "
                f"{service} may have carried it out despite the error. "
                "Check for a leftover draft record before trying again."
            )
        raise HTTPError(msg)
    resp.raise_for_status()
    if as_json:
        return resp.json()
    else:
        return resp


get = partial(_request, "get")
post = partial(_request, "post")
patch = partial(_request, "patch")
put = partial(_request, "put")
delete = partial(_request, "delete")

# A file sent as one request has to fit under the body size limit of every
# proxy in front of the server, e.g., Cloudflare's in front of CaltechDATA, so
# anything larger goes up in parts when the server supports it
MULTIPART_PART_SIZE = 50 * 1024 * 1024
# S3, which stores multipart uploads, accepts at most this many parts
MULTIPART_MAX_PARTS = 10_000


def get_part_size(size: int) -> int:
    """Get the part size to use for a multipart upload of ``size`` bytes."""
    min_size = -(-size // MULTIPART_MAX_PARTS)
    if min_size <= MULTIPART_PART_SIZE:
        return MULTIPART_PART_SIZE
    # Round up to a whole MiB so parts stay tidy
    mib = 1024 * 1024
    return -(-min_size // mib) * mib


class _ProgressReader:
    """Wrap a file so reading it reports how far through it has got."""

    def __init__(
        self, f: BinaryIO, size: int, progress: Callable[[int], None]
    ):
        self._f = f
        self._size = size
        self._progress = progress

    def __len__(self) -> int:
        # Lets requests send a Content-Length rather than chunking the body
        return self._size

    def read(self, n: int = -1) -> bytes:
        chunk = self._f.read(n)
        self._progress(self._f.tell())
        return chunk

    def tell(self) -> int:
        return self._f.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        pos = self._f.seek(offset, whence)
        self._progress(pos)
        return pos


def _put_part(url: str, fpath: str, offset: int, length: int) -> None:
    """Upload one part of a file to a presigned URL, retrying on failure."""
    with open(fpath, "rb") as f:
        f.seek(offset)
        chunk = f.read(length)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.put(url, data=chunk, timeout=get_timeout())
        except (requests.ConnectionError, requests.Timeout):
            if attempt == MAX_ATTEMPTS:
                raise
            time.sleep(2**attempt)
            continue
        if resp.status_code < 400:
            return
        if resp.status_code in RETRY_STATUS_CODES and attempt < MAX_ATTEMPTS:
            time.sleep(2**attempt)
            continue
        raise HTTPError(f"{resp.status_code}: {resp.text}")


def upload_file(
    record_id: str,
    fpath: str,
    key: str | None = None,
    service: ServiceName = DEFAULT_SERVICE,
    echo: Callable[[str], None] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    """Upload a file to a draft record and commit it.

    Files larger than one part are uploaded in parts straight to the server's
    storage when it supports multipart transfers, which keeps every request
    under the body size limits of proxies in front of the API. Otherwise the
    file is streamed from disk in a single request.

    ``progress`` is called with the bytes sent so far and the file's size.
    """
    if key is None:
        key = os.path.basename(fpath)
    if echo is None:
        echo = lambda msg: None  # noqa: E731
    size = os.path.getsize(fpath)
    if progress is None:
        report = lambda done: None  # noqa: E731
    else:
        report = lambda done: progress(done, size)  # noqa: E731
    files_path = f"/records/{record_id}/draft/files"
    entry = None
    if size > MULTIPART_PART_SIZE:
        part_size = get_part_size(size)
        n_parts = -(-size // part_size)
        try:
            resp = post(
                files_path,
                json=[
                    {
                        "key": key,
                        "size": size,
                        "transfer": {
                            "type": "M",
                            "parts": n_parts,
                            "part_size": part_size,
                        },
                    }
                ],
                service=service,
            )
            entry = next(
                (e for e in resp.get("entries", []) if e.get("key") == key),
                None,
            )
        except HTTPError as e:
            # A server without multipart support rejects the request
            # outright, leaving nothing behind, so fall back to one request
            if not str(e).startswith("4"):
                raise
            echo(f"Multipart upload not available ({e}); sending in one go")
    transfer = (entry or {}).get("transfer", {})
    if transfer.get("type") == "M":
        parts = entry.get("links", {}).get("parts")  # type: ignore[union-attr]
        if not parts:
            raise ValueError(
                f"{service} accepted a multipart upload of {key} "
                "but returned no part URLs"
            )
        part_size = transfer["part_size"]
        echo(
            f"Uploading {key} in {len(parts)} parts of "
            f"{part_size / 1e6:.0f} MB each"
        )
        done = 0
        report(done)
        for part in sorted(parts, key=lambda p: p["part"]):
            offset = (part["part"] - 1) * part_size
            length = min(part_size, size - offset)
            _put_part(part["url"], fpath, offset, length)
            done += length
            report(done)
    else:
        if entry is None:
            post(files_path, json=[{"key": key}], service=service)
        with open(fpath, "rb") as f:
            resp = put(
                f"{files_path}/{key}/content",
                headers={"Content-Type": "application/octet-stream"},
                as_json=False,
                service=service,
                data=_ProgressReader(f, size, report),
            )
    post(f"{files_path}/{key}/commit", service=service)


def extract_doi(record: dict) -> str | None:
    """Extract the DOI identifier from an InvenioRDM record or response.

    Depending on the endpoint and whether the DOI has been minted yet, the
    identifier can live in different places, so check all known locations and
    return ``None`` if it isn't present yet.
    """
    pids = record.get("pids")
    if isinstance(pids, dict):
        doi = pids.get("doi")
        if isinstance(doi, dict) and doi.get("identifier"):
            return doi["identifier"]
    if record.get("doi"):
        return record["doi"]
    metadata = record.get("metadata")
    if isinstance(metadata, dict) and metadata.get("doi"):
        return metadata["doi"]
    return None


def get_download_urls(
    record_id: int | str,
    service: ServiceName = DEFAULT_SERVICE,
    auth: bool = True,
) -> dict[str, str]:
    resp = get(f"/records/{record_id}", service=service, auth=auth)
    download_urls = [f["links"]["self"] for f in resp["files"]]
    filenames = [f["key"] for f in resp["files"]]
    urls = {}
    for fname, url in zip(filenames, download_urls):
        urls[fname] = url
    return urls


def upload_file_with_progress(
    record_id: str,
    fpath: str,
    key: str | None = None,
    service: ServiceName = DEFAULT_SERVICE,
) -> None:
    """Upload a file to a draft record, showing a progress bar."""
    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        TextColumn,
        TimeRemainingColumn,
        TransferSpeedColumn,
    )

    if key is None:
        key = os.path.basename(fpath)
    with Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    ) as bar:
        task = bar.add_task(f"Uploading {key}", total=os.path.getsize(fpath))
        upload_file(
            record_id,
            fpath,
            key=key,
            service=service,
            echo=bar.console.print,
            progress=lambda done, total: bar.update(
                task, completed=done, total=total
            ),
        )
