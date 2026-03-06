"""Tests for the Calkit filesystem implementation."""

import subprocess
import uuid

import pytest
import requests

import calkit
from calkit import fs as ckfs


class _FakeResponse:
    def __init__(self, status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _FakeChunkedSession:
    def __init__(self, init_resp, put_responses):
        self.init_resp = init_resp
        self.put_responses = list(put_responses)
        self.put_calls = []
        self.delete_calls = []

    def request(self, method, url, headers=None, params=None, timeout=None):
        return self.init_resp

    def put(self, url, headers=None, data=None, timeout=None):
        self.put_calls.append(
            {
                "url": url,
                "headers": headers or {},
                "data": data,
                "timeout": timeout,
            }
        )
        if not self.put_responses:
            raise AssertionError("No more fake put responses configured")
        return self.put_responses.pop(0)

    def delete(self, url, timeout=None):
        self.delete_calls.append({"url": url, "timeout": timeout})
        return _FakeResponse(status_code=204)


def test_parse_path():
    owner, project, file_path = ckfs._parse_path("ck://owner/project/file.txt")
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"
    owner, project, file_path = ckfs._parse_path("ck://owner/project")
    assert owner == "owner"
    assert project == "project"
    assert file_path == ""
    owner, project, file_path = ckfs._parse_path(
        "ck://owner/project/data/nested/file.txt"
    )
    assert owner == "owner"
    assert project == "project"
    assert file_path == "data/nested/file.txt"
    owner, project, file_path = ckfs._parse_path("owner/project/file.txt")
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"
    with pytest.raises(ValueError, match="Invalid path format"):
        ckfs._parse_path("ck://owner")
    with pytest.raises(ValueError, match="Invalid path format"):
        ckfs._parse_path("ck://")


def _calkit_cloud_available() -> bool:
    """Check if Calkit Cloud is available."""
    try:
        calkit.cloud.get_current_user()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _calkit_cloud_available(), reason="Calkit Cloud not available"
)
def test_calkitfilesystem():
    """Test basic CalkitFileSystem functionality."""
    fs = ckfs.CalkitFileSystem()
    assert fs.protocol == "ck"
    txt = uuid.uuid4().hex
    uri = "ck://calkit/example-basic/test.txt"
    with fs.open(uri, "w") as f:
        f.write(txt)
    with fs.open(uri, "r") as f:
        read_txt = f.read()
    assert read_txt == txt
    info = fs.info(uri)
    assert info["size"] == len(txt)
    assert info["type"] == "file"
    res = fs.ls("ck://calkit/example-basic/")
    assert "calkit/example-basic/test.txt" in res


@pytest.mark.skipif(
    not _calkit_cloud_available(), reason="Calkit Cloud not available"
)
def test_calkitfilesystem_dvc(tmp_dir):
    """Test CalkitFileSystem as a DVC remote."""
    subprocess.run(["calkit", "init"])
    subprocess.run(
        ["calkit", "dvc", "remote", "add", "ck://calkit/example-basic/"]
    )
    with open("data.txt", "w") as f:
        f.write("hello dvc")
    subprocess.run(["calkit", "dvc", "add", "data.txt"])
    subprocess.run(["calkit", "dvc", "push"])
    subprocess.run(["calkit", "dvc", "pull"])


def test_presigned_chunked_uses_server_ack_range():
    fs = ckfs.CalkitFileSystem()
    fs._session = _FakeChunkedSession(
        init_resp=_FakeResponse(
            status_code=200,
            headers={"Location": "https://upload-session.example"},
        ),
        put_responses=[
            _FakeResponse(status_code=308, headers={"Range": "bytes=0-2"}),
            _FakeResponse(status_code=308, headers={"Range": "bytes=0-7"}),
            _FakeResponse(status_code=201),
        ],
    )
    operation_info = {
        "access": {
            "kind": "presigned-chunked",
            "init_url": "https://init.example",
            "chunk_size_bytes": 5,
        }
    }
    payload = b"0123456789"
    resp = fs._execute_operation(operation_info, "put", data=payload)
    assert resp.status_code == 201
    put_calls = fs._session.put_calls
    assert len(put_calls) == 3
    assert put_calls[0]["headers"]["Content-Range"] == "bytes 0-4/10"
    assert put_calls[1]["headers"]["Content-Range"] == "bytes 3-7/10"
    assert put_calls[2]["headers"]["Content-Range"] == "bytes 8-9/10"
    assert put_calls[0]["data"] == b"01234"
    assert put_calls[1]["data"] == b"34567"
    assert put_calls[2]["data"] == b"89"


def test_presigned_chunked_raises_on_308_without_range():
    fs = ckfs.CalkitFileSystem()
    fs._session = _FakeChunkedSession(
        init_resp=_FakeResponse(
            status_code=200,
            headers={"Location": "https://upload-session.example"},
        ),
        put_responses=[_FakeResponse(status_code=308)],
    )
    operation_info = {
        "access": {
            "kind": "presigned-chunked",
            "init_url": "https://init.example",
            "chunk_size_bytes": 5,
        }
    }
    with pytest.raises(ValueError, match="308 without a valid Range"):
        fs._execute_operation(operation_info, "put", data=b"123456")
    assert fs._session.delete_calls == [
        {"url": "https://upload-session.example", "timeout": 30}
    ]


def test_presigned_chunked_raises_on_premature_success():
    fs = ckfs.CalkitFileSystem()
    fs._session = _FakeChunkedSession(
        init_resp=_FakeResponse(
            status_code=200,
            headers={"Location": "https://upload-session.example"},
        ),
        put_responses=[_FakeResponse(status_code=200)],
    )
    operation_info = {
        "access": {
            "kind": "presigned-chunked",
            "init_url": "https://init.example",
            "chunk_size_bytes": 5,
        }
    }
    with pytest.raises(ValueError, match="success before all bytes were sent"):
        fs._execute_operation(operation_info, "put", data=b"123456")
    assert fs._session.delete_calls == [
        {"url": "https://upload-session.example", "timeout": 30}
    ]
