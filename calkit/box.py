"""An fsspec filesystem for a folder in Box.

The hub uses it with an account's own token to reach every project in its
``Calkit`` folder, and the CLI with a token downscoped to one project's
folder. Box addresses items by ID, not path, so paths are resolved by
listing folders, and those listings are cached.

Nothing is ever deleted from Box, so removing paths isn't supported.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import random
import threading
import time
from collections.abc import Callable, MutableMapping
from typing import Any

import requests
from fsspec import AbstractFileSystem
from fsspec.callbacks import DEFAULT_CALLBACK
from fsspec.spec import AbstractBufferedFile

API_URL = "https://api.box.com/2.0"
UPLOAD_URL = "https://upload.box.com/api/2.0"
# Box refuses chunked uploads of smaller files, and simple uploads of
# larger ones than 50 MB
CHUNKED_UPLOAD_MIN_BYTES = 20 * 1024 * 1024
ITEM_FIELDS = "type,id,name,size,sha1,modified_at"
MAX_TRIES = 6
# Folders listed at once when finding what's under a path; Box allows about
# 1000 requests a minute, and rate limits are waited out
FIND_WORKERS = 8
# How long a client reuses access to upload, so it asks the hub again soon
# after a project's storage changes, rather than uploading to Box for the
# rest of the token's hour
UPLOAD_ACCESS_REUSE_SECONDS = 300


def get_sha1(f: Any, start: int = 0, size: int | None = None) -> str:
    """Get the hex SHA-1 of a seekable binary file, or part of it."""
    sha1 = hashlib.sha1()
    f.seek(start)
    remaining = size
    while remaining is None or remaining > 0:
        n = 8 * 1024 * 1024 if remaining is None else min(remaining, 8 << 20)
        block = f.read(n)
        if not block:
            break
        sha1.update(block)
        if remaining is not None:
            remaining -= len(block)
    return sha1.hexdigest()


def make_digest_header(sha1_hex: str) -> str:
    return "sha=" + base64.b64encode(bytes.fromhex(sha1_hex)).decode()


class BoxFileSystem(AbstractFileSystem):
    """Paths are relative to ``root_folder_id``, e.g., ``files/md5/ab/cd``.

    ``token`` is an access token, or a function returning a current one,
    which is called again if Box rejects it. ``folder_ids`` caches folder
    IDs by path, and can be shared between instances with the same root.
    """

    protocol = "box"
    root_marker = ""
    # Each instance has its own token and caches
    cachable = False

    def __init__(
        self,
        token: str | Callable[[], str],
        root_folder_id: str,
        folder_ids: MutableMapping[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._get_token = token if callable(token) else (lambda: token)
        self._token = self._get_token()
        self.root_folder_id = str(root_folder_id)
        self._session = requests.Session()
        self._lock = threading.Lock()
        self._folder_ids = folder_ids if folder_ids is not None else {}
        # Items in each listed folder by name, by folder ID
        self._listings: dict[str, dict[str, dict[str, Any]]] = {}
        self._folder_locks: dict[str, threading.Lock] = {}

    @classmethod
    def _strip_protocol(cls, path: Any) -> str:
        return str(path).removeprefix("box://").strip("/")

    def _request(
        self, method: str, url: str, **kwargs: Any
    ) -> requests.Response:
        """Send a request, waiting out rate limits and server errors, and
        getting a new token once if Box rejects the current one.
        """
        # Bodies are bytes, not streams, so a retry can send them again
        extra_headers = kwargs.pop("headers", None) or {}
        renewed = False
        for n in range(MAX_TRIES):
            headers = {"Authorization": f"Bearer {self._token}"}
            resp = self._session.request(
                method,
                url,
                headers=headers | extra_headers,
                timeout=60,
                **kwargs,
            )
            if resp.status_code == 401 and not renewed:
                renewed = True
                self._token = self._get_token()
                continue
            # A download of a file uploaded just before can be not ready yet
            if (
                resp.status_code == 429
                or resp.status_code >= 500
                or (resp.status_code == 202 and method == "GET")
                or self._get_error_code(resp) == "operation_blocked_temporary"
            ):
                if n == MAX_TRIES - 1:
                    break
                wait = float(resp.headers.get("retry-after") or 2**n)
                time.sleep(wait + random.random())
                continue
            break
        return resp

    @staticmethod
    def _get_error_code(resp: requests.Response) -> str | None:
        """Get Box's code for an error, e.g., ``operation_blocked_temporary``
        for a 409 while another change to the same folder is in progress.
        """
        if resp.status_code < 400:
            return None
        try:
            return str(resp.json().get("code"))
        except ValueError:
            return None

    def _list_folder(self, folder_id: str) -> dict[str, dict[str, Any]]:
        """Get a folder's items by name, listing it once."""
        with self._lock:
            lock = self._folder_locks.setdefault(folder_id, threading.Lock())
        # So concurrent lookups in one folder list it once
        with lock:
            if folder_id in self._listings:
                return self._listings[folder_id]
            items: dict[str, dict[str, Any]] = {}
            params: dict[str, Any] = {
                "fields": ITEM_FIELDS,
                "limit": 1000,
                "usemarker": "true",
            }
            while True:
                resp = self._request(
                    "GET",
                    f"{API_URL}/folders/{folder_id}/items",
                    params=params,
                )
                if resp.status_code == 404:
                    self._forget_folders()
                    raise FileNotFoundError(folder_id)
                resp.raise_for_status()
                body = resp.json()
                for item in body["entries"]:
                    items[item["name"]] = item
                marker = body.get("next_marker")
                if not marker:
                    break
                params["marker"] = marker
            self._listings[folder_id] = items
            return items

    def _forget_folders(self) -> None:
        """Forget what's known of the folder tree once a folder is found to be
        gone, e.g., moved to the trash in Box, so paths are looked up again.

        Everything is forgotten, since the parents' listings may be from
        before, and it's rare enough that listing again is cheap.
        """
        self._folder_ids.clear()
        with self._lock:
            self._listings.clear()

    def _add_to_listing(self, folder_id: str, item: dict[str, Any]) -> None:
        with self._lock:
            listing = self._listings.get(folder_id)
            if listing is not None:
                listing[item["name"]] = item

    def get_folder_id(self, path: str, create: bool = False) -> str:
        """Get the ID of the folder at a path, optionally creating it and
        any missing parents.
        """
        path = self._strip_protocol(path)
        if not path:
            return self.root_folder_id
        cached = self._folder_ids.get(path)
        if cached is not None:
            return cached
        parent, _, name = path.rpartition("/")
        parent_id = self.get_folder_id(parent, create=create)
        item = self._list_folder(parent_id).get(name)
        if item is None:
            if not create:
                raise FileNotFoundError(path)
            resp = self._request(
                "POST",
                f"{API_URL}/folders",
                params={"fields": ITEM_FIELDS},
                json={"name": name, "parent": {"id": parent_id}},
            )
            if resp.status_code == 404:
                self._forget_folders()
                raise FileNotFoundError(parent)
            # Created meanwhile, e.g., by another thread
            if resp.status_code == 409:
                item = self._get_conflict(resp)
            else:
                resp.raise_for_status()
                item = resp.json()
                with self._lock:
                    self._listings.setdefault(item["id"], {})
            self._add_to_listing(parent_id, item)
        if item["type"] != "folder":
            raise NotADirectoryError(path)
        self._folder_ids[path] = item["id"]
        return str(item["id"])

    def _get_item(self, path: str) -> dict[str, Any]:
        path = self._strip_protocol(path)
        if not path:
            return {"type": "folder", "id": self.root_folder_id, "name": ""}
        parent, _, name = path.rpartition("/")
        try:
            parent_id = self.get_folder_id(parent)
        except NotADirectoryError:
            raise FileNotFoundError(path)
        item = self._list_folder(parent_id).get(name)
        if item is None:
            # A folder at it may have been moved to the trash since its ID was
            # cached
            for cached in list(self._folder_ids):
                if cached == path or cached.startswith(f"{path}/"):
                    self._folder_ids.pop(cached, None)
            raise FileNotFoundError(path)
        return item

    @staticmethod
    def _get_conflict(resp: requests.Response) -> dict[str, Any]:
        """Get the existing item from a 409 response."""
        conflicts = resp.json().get("context_info", {}).get("conflicts")
        if isinstance(conflicts, list):
            conflicts = conflicts[0] if conflicts else None
        if not conflicts:
            resp.raise_for_status()
        return dict(conflicts)

    @staticmethod
    def _make_info(path: str, item: dict[str, Any]) -> dict[str, Any]:
        is_file = item["type"] == "file"
        return {
            "name": path,
            "size": int(item.get("size") or 0) if is_file else 0,
            "type": "file" if is_file else "directory",
            "time_modified": item.get("modified_at"),
            "box_id": item["id"],
            "sha1": item.get("sha1"),
        }

    def info(self, path: str, **kwargs: Any) -> dict[str, Any]:
        path = self._strip_protocol(path)
        return self._make_info(path, self._get_item(path))

    def ls(self, path: str, detail: bool = True, **kwargs: Any) -> list[Any]:
        path = self._strip_protocol(path)
        item = self._get_item(path)
        if item["type"] != "folder":
            return [self._make_info(path, item)] if detail else [path]
        infos = [
            self._make_info(f"{path}/{name}" if path else name, child)
            for name, child in sorted(self._list_folder(item["id"]).items())
        ]
        return infos if detail else [i["name"] for i in infos]

    def find(
        self,
        path: str,
        maxdepth: int | None = None,
        withdirs: bool = False,
        detail: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Find what's under a path, listing each level's folders at once,
        since each is a request to Box, and DVC's layout has up to 256.
        """
        from concurrent.futures import ThreadPoolExecutor

        path = self._strip_protocol(path)
        try:
            item = self._get_item(path)
        except FileNotFoundError:
            return {} if detail else []
        found = {}
        if item["type"] == "file":
            found[path] = self._make_info(path, item)
        level = [(path, item["id"], 0)] if item["type"] == "folder" else []
        with ThreadPoolExecutor(FIND_WORKERS) as pool:
            while level:
                listings = pool.map(lambda e: self._list_folder(e[1]), level)
                next_level = []
                for (folder_path, _, depth), children in zip(level, listings):
                    for name, child in children.items():
                        child_path = (
                            f"{folder_path}/{name}" if folder_path else name
                        )
                        info = self._make_info(child_path, child)
                        if child["type"] != "folder":
                            found[child_path] = info
                            continue
                        self._folder_ids[child_path] = child["id"]
                        if withdirs:
                            found[child_path] = info
                        if maxdepth is None or depth + 1 < maxdepth:
                            next_level.append(
                                (child_path, child["id"], depth + 1)
                            )
                level = next_level
        names = sorted(found)
        return {name: found[name] for name in names} if detail else names

    def get_file_id(self, path: str) -> str:
        item = self._get_item(path)
        if item["type"] != "file":
            raise IsADirectoryError(path)
        return str(item["id"])

    def get_file_by_id(
        self, file_id: str, lpath: str, callback: Any = DEFAULT_CALLBACK
    ) -> None:
        """Download a file by its ID, e.g., one the hub looked up."""
        resp = self._request(
            "GET", f"{API_URL}/files/{file_id}/content", stream=True
        )
        if resp.status_code == 404:
            raise FileNotFoundError(file_id)
        resp.raise_for_status()
        size = resp.headers.get("content-length")
        if size is not None:
            callback.set_size(int(size))
        with open(lpath, "wb") as f:
            for block in resp.iter_content(8 * 1024 * 1024):
                callback.relative_update(f.write(block))

    def cat_file_by_id(
        self, file_id: str, start: int | None = None, end: int | None = None
    ) -> bytes:
        """Read a file, or part of it, by its ID."""
        headers = {}
        if start is not None or end is not None:
            last = "" if end is None else str(end - 1)
            headers["Range"] = f"bytes={start or 0}-{last}"
        resp = self._request(
            "GET", f"{API_URL}/files/{file_id}/content", headers=headers
        )
        if resp.status_code == 404:
            raise FileNotFoundError(file_id)
        resp.raise_for_status()
        return bytes(resp.content)

    def get_file(
        self,
        rpath: str,
        lpath: Any,
        callback: Any = DEFAULT_CALLBACK,
        **kwargs: Any,
    ) -> None:
        if os.path.isdir(lpath):
            return
        self.get_file_by_id(self.get_file_id(rpath), lpath, callback)

    def _upload(
        self, f: Any, size: int, rpath: str, callback: Any
    ) -> dict[str, Any]:
        """Upload a seekable binary file to a path, replacing what's there
        with a new version if its content differs.
        """
        rpath = self._strip_protocol(rpath)
        parent, _, name = rpath.rpartition("/")
        parent_id = self.get_folder_id(parent, create=True)
        start = f.tell()
        sha1 = get_sha1(f, start, size)
        existing = self._list_folder(parent_id).get(name)
        if existing is None:
            item = self._send(f, start, size, sha1, name, parent_id, callback)
            if item is None:
                # Uploaded meanwhile, e.g., by another client
                existing = self._list_folder(parent_id)[name]
        if existing is not None:
            if existing["type"] != "file":
                raise IsADirectoryError(rpath)
            if existing.get("sha1") == sha1:
                callback.relative_update(size)
                return existing
            # Box keeps the old content as a previous version
            item = self._send(
                f, start, size, sha1, name, parent_id, callback, existing["id"]
            )
        assert item is not None
        self._add_to_listing(parent_id, item)
        return item

    def _check_parent_found(
        self, resp: requests.Response, parent_id: str
    ) -> None:
        """Raise for a failed upload, forgetting its folder if it's gone,
        e.g., moved to the trash, so it's looked up again next time.
        """
        if resp.status_code == 404:
            self._forget_folders()
            raise FileNotFoundError(parent_id)
        resp.raise_for_status()

    def _send(
        self,
        f: Any,
        start: int,
        size: int,
        sha1: str,
        name: str,
        parent_id: str,
        callback: Any,
        file_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Send content as a new file, or a new version of ``file_id``.

        Returns the file, or ``None`` if the name was taken meanwhile, with
        the existing file added to the parent's listing.
        """
        if size >= CHUNKED_UPLOAD_MIN_BYTES:
            return self._send_chunked(
                f, start, size, sha1, name, parent_id, callback, file_id
            )
        f.seek(start)
        attributes: dict[str, Any] = {"name": name}
        if file_id is None:
            attributes["parent"] = {"id": parent_id}
            url = f"{UPLOAD_URL}/files/content"
        else:
            url = f"{UPLOAD_URL}/files/{file_id}/content"
        resp = self._request(
            "POST",
            url,
            params={"fields": ITEM_FIELDS},
            headers={"content-md5": sha1},
            files={
                "attributes": (None, json.dumps(attributes)),
                "file": (name, f.read(size)),
            },
        )
        if resp.status_code == 409 and file_id is None:
            self._add_to_listing(parent_id, self._get_conflict(resp))
            return None
        self._check_parent_found(resp, parent_id)
        callback.relative_update(size)
        return dict(resp.json()["entries"][0])

    def _send_chunked(
        self,
        f: Any,
        start: int,
        size: int,
        sha1: str,
        name: str,
        parent_id: str,
        callback: Any,
        file_id: str | None,
    ) -> dict[str, Any] | None:
        if file_id is None:
            resp = self._request(
                "POST",
                f"{UPLOAD_URL}/files/upload_sessions",
                json={
                    "folder_id": parent_id,
                    "file_size": size,
                    "file_name": name,
                },
            )
        else:
            resp = self._request(
                "POST",
                f"{UPLOAD_URL}/files/{file_id}/upload_sessions",
                json={"file_size": size},
            )
        if resp.status_code == 409 and file_id is None:
            self._add_to_listing(parent_id, self._get_conflict(resp))
            return None
        self._check_parent_found(resp, parent_id)
        session = resp.json()
        part_size = int(session["part_size"])
        endpoints = session["session_endpoints"]
        parts = []
        for offset in range(0, size, part_size):
            n = min(part_size, size - offset)
            f.seek(start + offset)
            chunk = f.read(n)
            resp = self._request(
                "PUT",
                endpoints["upload_part"],
                headers={
                    "digest": make_digest_header(
                        hashlib.sha1(chunk).hexdigest()
                    ),
                    "content-range": (
                        f"bytes {offset}-{offset + n - 1}/{size}"
                    ),
                    "content-type": "application/octet-stream",
                },
                data=chunk,
            )
            resp.raise_for_status()
            parts.append(resp.json()["part"])
            callback.relative_update(n)
        # Box may still be processing the parts, and says when to try again
        for _ in range(30):
            resp = self._request(
                "POST",
                endpoints["commit"],
                params={"fields": ITEM_FIELDS},
                headers={"digest": make_digest_header(sha1)},
                json={"parts": parts},
            )
            if resp.status_code != 202:
                break
            time.sleep(float(resp.headers.get("retry-after") or 1))
        else:
            raise OSError(f"Box didn't finish processing {name}")
        resp.raise_for_status()
        return dict(resp.json()["entries"][0])

    def put_file(
        self,
        lpath: Any,
        rpath: str,
        callback: Any = DEFAULT_CALLBACK,
        mode: str = "overwrite",
        **kwargs: Any,
    ) -> None:
        if os.path.isdir(lpath):
            self.get_folder_id(rpath, create=True)
            return
        size = os.path.getsize(lpath)
        callback.set_size(size)
        with open(lpath, "rb") as f:
            self._upload(f, size, rpath, callback)

    def pipe_file(self, path: str, value: bytes, **kwargs: Any) -> None:
        self._upload(io.BytesIO(value), len(value), path, DEFAULT_CALLBACK)

    def makedir(
        self, path: str, create_parents: bool = True, **kwargs: Any
    ) -> None:
        self.get_folder_id(path, create=True)

    def makedirs(self, path: str, exist_ok: bool = False) -> None:
        self.get_folder_id(path, create=True)

    def _rm(self, path: str) -> None:
        raise PermissionError("Calkit never deletes from Box")

    def rm(
        self, path: Any, recursive: bool = False, maxdepth: Any = None
    ) -> None:
        raise PermissionError("Calkit never deletes from Box")

    def _open(
        self,
        path: str,
        mode: str = "rb",
        block_size: Any = "default",
        autocommit: bool = True,
        cache_options: Any = None,
        **kwargs: Any,
    ) -> BoxFile:
        return BoxFile(
            self,
            path,
            mode,
            block_size,
            autocommit,
            cache_options=cache_options,
            **kwargs,
        )


class BoxFile(AbstractBufferedFile):
    """Reads with range requests, and writes in one upload on close."""

    fs: BoxFileSystem

    def _fetch_range(self, start: int, end: int) -> bytes:
        return self.fs.cat_file_by_id(self.details["box_id"], start, end)

    def _initiate_upload(self) -> None:
        self._content = io.BytesIO()

    def _upload_chunk(self, final: bool = False) -> bool:
        self.buffer.seek(0)
        self._content.write(self.buffer.read())
        if final:
            size = self._content.tell()
            self._content.seek(0)
            self.fs._upload(self._content, size, self.path, DEFAULT_CALLBACK)
        return True
