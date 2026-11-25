"""Tests for ``calkit.box``."""

import base64
import hashlib
import json
import re
from unittest.mock import patch

import pytest
import requests

import calkit.box
from calkit.box import API_URL, UPLOAD_URL, BoxFileSystem


def make_response(
    status: int, body: dict | bytes | None = None, headers: dict | None = None
) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    if isinstance(body, bytes):
        resp._content = body
    else:
        resp._content = json.dumps(body or {}).encode()
    resp._content_consumed = True
    resp.headers.update(headers or {})
    resp.url = "https://box.test"
    return resp


class FakeBox:
    """The parts of Box's API Calkit uses, in memory."""

    def __init__(self, page_size: int = 1000, part_size: int = 4) -> None:
        self.items: dict[str, dict] = {
            "0": {"type": "folder", "id": "0", "name": "", "parent": None}
        }
        self.content: dict[str, bytes] = {}
        self.n_versions: dict[str, int] = {}
        self.sessions: dict[str, dict] = {}
        self.page_size = page_size
        self.part_size = part_size
        self.next_id = 100
        # Responses to give before handling requests, e.g., a 429
        self.queued: list[requests.Response] = []
        self.calls: list[tuple[str, str]] = []
        self.valid_tokens = {"token"}

    def new_id(self) -> str:
        self.next_id += 1
        return str(self.next_id)

    def add(self, kind: str, name: str, parent_id: str, data: bytes = b""):
        item = {"type": kind, "id": self.new_id(), "name": name}
        item["parent"] = parent_id
        if kind == "file":
            self.content[item["id"]] = data
        self.items[item["id"]] = item
        return item

    def children(self, folder_id: str) -> list[dict]:
        return sorted(
            (i for i in self.items.values() if i["parent"] == folder_id),
            key=lambda i: i["name"],
        )

    def find(self, folder_id: str, name: str) -> dict | None:
        for item in self.children(folder_id):
            if item["name"] == name:
                return item
        return None

    def public(self, item: dict) -> dict:
        out = {k: v for k, v in item.items() if k != "parent"}
        if item["type"] == "file":
            data = self.content[item["id"]]
            out["size"] = len(data)
            out["sha1"] = hashlib.sha1(data).hexdigest()
        return out

    def request(self, method, url, headers=None, **kwargs):
        self.calls.append((method, url))
        if self.queued:
            return self.queued.pop(0)
        token = (
            (headers or {}).get("Authorization", "").removeprefix("Bearer ")
        )
        if token not in self.valid_tokens:
            return make_response(401)
        params = kwargs.get("params") or {}
        body = kwargs.get("json")
        if m := re.fullmatch(rf"{API_URL}/folders/(\w+)/items", url):
            if m[1] not in self.items:
                return make_response(404)
            children = self.children(m[1])
            start = int(params.get("marker") or 0)
            page = children[start : start + self.page_size]
            out: dict = {"entries": [self.public(i) for i in page]}
            if start + self.page_size < len(children):
                out["next_marker"] = str(start + self.page_size)
            return make_response(200, out)
        if url == f"{API_URL}/folders":
            if body["parent"]["id"] not in self.items:
                return make_response(404)
            existing = self.find(body["parent"]["id"], body["name"])
            if existing is not None:
                return make_response(
                    409,
                    {
                        "code": "item_name_in_use",
                        "context_info": {"conflicts": [self.public(existing)]},
                    },
                )
            item = self.add("folder", body["name"], body["parent"]["id"])
            return make_response(201, self.public(item))
        if m := re.fullmatch(rf"{UPLOAD_URL}/files(?:/(\w+))?/content", url):
            attributes = json.loads(kwargs["files"]["attributes"][1])
            data = kwargs["files"]["file"][1]
            assert headers["content-md5"] == hashlib.sha1(data).hexdigest()
            if m[1] is None:
                if attributes["parent"]["id"] not in self.items:
                    return make_response(404)
                existing = self.find(
                    attributes["parent"]["id"], attributes["name"]
                )
                if existing is not None:
                    return make_response(
                        409,
                        {"context_info": {"conflicts": self.public(existing)}},
                    )
                item = self.add(
                    "file",
                    attributes["name"],
                    attributes["parent"]["id"],
                    data,
                )
            else:
                item = self.items[m[1]]
                self.content[item["id"]] = data
                self.n_versions[item["id"]] = (
                    self.n_versions.get(item["id"], 1) + 1
                )
            return make_response(201, {"entries": [self.public(item)]})
        if m := re.fullmatch(
            rf"{UPLOAD_URL}/files(?:/(\w+))?/upload_sessions", url
        ):
            session_id = self.new_id()
            self.sessions[session_id] = {
                "file_id": m[1],
                "folder_id": body.get("folder_id"),
                "name": body.get("file_name"),
                "parts": {},
                "commits": 0,
            }
            endpoint = f"{UPLOAD_URL}/files/upload_sessions/{session_id}"
            return make_response(
                201,
                {
                    "part_size": self.part_size,
                    "session_endpoints": {
                        "upload_part": endpoint,
                        "commit": f"{endpoint}/commit",
                    },
                },
            )
        if m := re.fullmatch(
            rf"{UPLOAD_URL}/files/upload_sessions/(\w+)", url
        ):
            data = kwargs["data"]
            digest = base64.b64encode(hashlib.sha1(data).digest()).decode()
            assert headers["digest"] == f"sha={digest}"
            offset = int(
                re.match(r"bytes (\d+)-", headers["content-range"])[1]
            )
            self.sessions[m[1]]["parts"][offset] = data
            return make_response(
                200, {"part": {"offset": offset, "size": len(data)}}
            )
        if m := re.fullmatch(
            rf"{UPLOAD_URL}/files/upload_sessions/(\w+)/commit", url
        ):
            session = self.sessions[m[1]]
            session["commits"] += 1
            # Box may still be processing the parts
            if session["commits"] == 1:
                return make_response(202, headers={"retry-after": "0"})
            data = b"".join(v for _, v in sorted(session["parts"].items()))
            digest = base64.b64encode(hashlib.sha1(data).digest()).decode()
            assert headers["digest"] == f"sha={digest}"
            if session["file_id"] is None:
                item = self.add(
                    "file", session["name"], session["folder_id"], data
                )
            else:
                item = self.items[session["file_id"]]
                self.content[item["id"]] = data
            return make_response(201, {"entries": [self.public(item)]})
        if m := re.fullmatch(rf"{API_URL}/files/(\w+)/content", url):
            if m[1] not in self.content:
                return make_response(404)
            data = self.content[m[1]]
            if rng := (headers or {}).get("Range"):
                start, end = rng.removeprefix("bytes=").split("-")
                data = data[int(start) : int(end) + 1 if end else None]
            return make_response(
                200, data, headers={"content-length": str(len(data))}
            )
        raise AssertionError(f"Unexpected request: {method} {url}")


def make_fs(box: FakeBox, token="token", root="0", **kwargs) -> BoxFileSystem:
    fs = BoxFileSystem(token, root, **kwargs)
    fs._session.request = box.request  # type: ignore[method-assign]
    return fs


@pytest.fixture(autouse=True)
def no_sleep():
    with patch("calkit.box.time.sleep"):
        yield


def test_box_filesystem(tmp_path):
    box = FakeBox(page_size=2)
    fs = make_fs(box)
    # Uploading makes the folders it needs
    lpath = tmp_path / "a"
    lpath.write_bytes(b"hello")
    fs.put_file(str(lpath), "proj/files/md5/ab/cd")
    assert fs.cat_file("proj/files/md5/ab/cd") == b"hello"
    assert fs.info("proj/files/md5/ab/cd")["size"] == 5
    assert fs.info("proj/files")["type"] == "directory"
    assert fs.exists("proj/files/md5/ab")
    assert not fs.exists("proj/files/md5/ab/nope")
    assert not fs.exists("proj/nope/deeper")
    # The same content again isn't uploaded
    n_calls = len(box.calls)
    fs.put_file(str(lpath), "proj/files/md5/ab/cd")
    assert len(box.calls) == n_calls
    # Changed content becomes a new version, since nothing's deleted
    fs.pipe_file("proj/files/md5/ab/cd", b"changed")
    file_id = fs.get_file_id("proj/files/md5/ab/cd")
    assert box.n_versions[file_id] == 2
    assert box.content[file_id] == b"changed"
    # Listings are paged, and a new instance sees everything
    for n in range(5):
        fs.pipe_file(f"proj/many/{n}", str(n).encode())
    fs2 = make_fs(box)
    assert fs2.ls("proj/many", detail=False) == [
        f"proj/many/{n}" for n in range(5)
    ]
    assert fs2.find("proj") == sorted(
        ["proj/files/md5/ab/cd"] + [f"proj/many/{n}" for n in range(5)]
    )
    assert fs2.find("proj", maxdepth=1) == []
    assert fs2.find("proj", maxdepth=2, withdirs=True) == [
        "proj/files",
        "proj/files/md5",
        "proj/many",
    ] + [f"proj/many/{n}" for n in range(5)]
    found = fs2.find("proj/files", detail=True)
    assert found["proj/files/md5/ab/cd"]["size"] == len(b"changed")
    assert fs2.find("proj/files/md5/ab/cd") == ["proj/files/md5/ab/cd"]
    assert fs2.find("proj/nope") == []
    # A name another client took meanwhile is used, rather than failing
    fs3 = make_fs(box)
    fs3.ls("proj")
    box.add(
        "folder",
        "other",
        box.find(fs3.get_folder_id("proj"), "many")["parent"],
    )
    assert (
        fs3.get_folder_id("proj/other", create=True)
        == box.find(fs3.get_folder_id("proj"), "other")["id"]
    )
    fs3.ls("proj/many")
    box.add("file", "5", fs3.get_folder_id("proj/many"), b"5")
    fs3.pipe_file("proj/many/5", b"5")
    assert len([i for i in box.items.values() if i["name"] == "5"]) == 1
    # Reads and writes through file objects
    with fs2.open("proj/many/3", "rb") as f:
        assert f.read() == b"3"
    with fs2.open("proj/written", "wb") as f:
        f.write(b"wr")
        f.write(b"itten")
    assert make_fs(box).cat_file("proj/written") == b"written"
    assert fs2.cat_file_by_id(file_id, 1, 3) == b"ha"
    out = tmp_path / "out"
    fs2.get_file("proj/files/md5/ab/cd", str(out))
    assert out.read_bytes() == b"changed"
    # Nothing is ever deleted
    with pytest.raises(PermissionError):
        fs2.rm("proj/written")
    with pytest.raises(PermissionError):
        fs2.rm_file("proj/written")
    # Paths are relative to the root folder
    sub = make_fs(box, root=fs.get_folder_id("proj/many"))
    assert sub.cat_file("2") == b"2"
    assert sub.cat_file("box://2") == b"2"
    with pytest.raises(FileNotFoundError):
        sub.info("proj")


def test_box_filesystem_chunked_upload(tmp_path):
    box = FakeBox(part_size=4)
    fs = make_fs(box)
    data = b"0123456789"
    lpath = tmp_path / "big"
    lpath.write_bytes(data)
    with patch.object(calkit.box, "CHUNKED_UPLOAD_MIN_BYTES", 8):
        fs.put_file(str(lpath), "files/big")
        session = next(iter(box.sessions.values()))
        assert sorted(session["parts"]) == [0, 4, 8]
        # Committed again after Box said it was still processing
        assert session["commits"] == 2
        assert fs.cat_file("files/big") == data
        # A new version is chunked too
        fs.pipe_file("files/big", data[::-1])
    file_id = fs.get_file_id("files/big")
    assert box.content[file_id] == data[::-1]
    assert len(box.sessions) == 2


def test_box_filesystem_retries():
    box = FakeBox()
    tokens = iter(["old", "token"])
    fs = make_fs(box, token=lambda: next(tokens))
    # A rejected token is renewed once
    fs.pipe_file("a", b"a")
    assert fs.cat_file("a") == b"a"
    # Rate limits, server errors, and blocked operations are waited out
    box.queued = [
        make_response(429, headers={"retry-after": "0"}),
        make_response(503),
        make_response(409, {"code": "operation_blocked_temporary"}),
    ]
    fs.makedirs("b")
    assert box.find("0", "b") is not None
    # So is a file that was uploaded just before, which isn't ready yet
    file_id = fs.get_file_id("a")
    box.queued = [make_response(202, headers={"retry-after": "0"})]
    assert fs.cat_file_by_id(file_id) == b"a"
    # Until they've lasted too long
    box.queued = [make_response(500)] * calkit.box.MAX_TRIES
    with pytest.raises(requests.HTTPError):
        make_fs(box).ls("")
    # A cached folder that was moved to the trash is looked up again
    folder_ids: dict[str, str] = {}
    fs = make_fs(box, folder_ids=folder_ids)
    fs.pipe_file("c/d", b"d")
    old_id = folder_ids["c"]
    del box.items[old_id]
    fs2 = make_fs(box, folder_ids=folder_ids)
    with pytest.raises(FileNotFoundError):
        fs2.pipe_file("c/e", b"e")
    assert "c" not in folder_ids
    make_fs(box, folder_ids=folder_ids).pipe_file("c/d", b"d")
    assert folder_ids["c"] != old_id
    # Including by the instance that found it gone, whose listing of the
    # parent still had it
    del box.items[folder_ids["c"]]
    with pytest.raises(FileNotFoundError):
        fs.pipe_file("c/f", b"f")
    fs.pipe_file("c/f", b"f")
    assert make_fs(box).cat_file("c/f") == b"f"
