"""Tests for the Calkit filesystem implementation."""

import os
import subprocess
import uuid
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest

import calkit
from calkit import fs as ckfs


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


def test_execute_operation_presigned_chunked_progress():
    """Progress callback is called for each acknowledged chunk."""
    chunk_size = 5
    data = b"A" * 13  # 13 bytes: chunks of 5, 5, 3
    total = len(data)

    session = MagicMock()

    # Simulate GCS resumable upload responses:
    # chunk 1 (bytes 0-4): 308 with Range: bytes=0-4
    resp1 = MagicMock()
    resp1.status_code = 308
    resp1.headers = {"Range": "bytes=0-4"}

    # chunk 2 (bytes 5-9): 308 with Range: bytes=0-9
    resp2 = MagicMock()
    resp2.status_code = 308
    resp2.headers = {"Range": "bytes=0-9"}

    # chunk 3 (bytes 10-12): 200 - final success
    resp3 = MagicMock()
    resp3.status_code = 200
    resp3.headers = {}

    # init response returns a session URI
    init_resp = MagicMock()
    init_resp.raise_for_status = MagicMock()
    init_resp.headers = {"Location": "https://example.com/upload-session"}

    session.request.side_effect = [init_resp, resp1, resp2, resp3]

    fs = ckfs.CalkitFileSystem.__new__(ckfs.CalkitFileSystem)
    fs._session = session

    operation_info = {
        "access": {
            "kind": "presigned-chunked",
            "init_url": "https://example.com/initiate",
            "chunk_size_bytes": chunk_size,
            "http_method": "POST",
            "chunk_http_method": "PUT",
            "headers": {"x-goog-resumable": "start"},
        }
    }

    callback = MagicMock()
    callback.relative_update = MagicMock()

    fs._execute_operation(operation_info, "put", data=data, callback=callback)

    # Verify callback was called with correct byte counts per chunk
    calls = [c.args[0] for c in callback.relative_update.call_args_list]
    # chunk 1: ack offset 5 - start offset 0 = 5
    # chunk 2: ack offset 10 - start offset 5 = 5
    # chunk 3: chunk_end 13 - start offset 10 = 3
    assert calls == [5, 5, 3], f"Expected [5, 5, 3], got {calls}"
    assert sum(calls) == total


def test_execute_operation_presigned_multipart_progress():
    """Progress callback is called for each uploaded part."""
    part_size = 5
    data = b"B" * 13  # 13 bytes -> parts of 5, 5, 3
    total = len(data)

    session = MagicMock()

    part_resp = MagicMock()
    part_resp.raise_for_status = MagicMock()
    part_resp.headers = {"ETag": '"abc123"'}

    complete_resp = MagicMock()
    complete_resp.raise_for_status = MagicMock()

    session.put.return_value = part_resp
    session.post.return_value = complete_resp

    fs = ckfs.CalkitFileSystem.__new__(ckfs.CalkitFileSystem)
    fs._session = session

    operation_info = {
        "access": {
            "kind": "presigned-multipart",
            "upload_id": "uid-123",
            "part_urls": [
                "https://s3.example.com/part1",
                "https://s3.example.com/part2",
                "https://s3.example.com/part3",
            ],
            "complete_url": "https://s3.example.com/complete",
            "part_size_bytes": part_size,
        }
    }

    callback = MagicMock()
    callback.relative_update = MagicMock()

    fs._execute_operation(
        operation_info, "put", data=data, callback=callback
    )

    calls = [c.args[0] for c in callback.relative_update.call_args_list]
    assert calls == [5, 5, 3], f"Expected [5, 5, 3], got {calls}"
    assert sum(calls) == total


def test_put_file_uses_callback(tmp_path):
    """put_file reports progress via callback based on actual upload bytes."""
    data = b"C" * 20
    local_file = tmp_path / "upload.bin"
    local_file.write_bytes(data)

    session = MagicMock()
    put_resp = MagicMock()
    put_resp.raise_for_status = MagicMock()
    session.request.return_value = put_resp

    fs = ckfs.CalkitFileSystem.__new__(ckfs.CalkitFileSystem)
    fs._session = session

    operation_info = {
        "access": {
            "kind": "presigned-url",
            "url": "https://storage.example.com/upload",
            "http_method": "PUT",
        }
    }

    with patch.object(fs, "_get_fs_op_info", return_value=operation_info):
        with patch.object(fs, "exists", return_value=False):
            callback = MagicMock()
            callback.set_size = MagicMock()
            callback.relative_update = MagicMock()

            fs.put_file(
                str(local_file),
                "ck://owner/project/upload.bin",
                callback=callback,
            )

    callback.set_size.assert_called_once_with(len(data))
    calls = [c.args[0] for c in callback.relative_update.call_args_list]
    assert sum(calls) == len(data)


def _calkit_cloud_available(
    env: Literal["local", "staging", "production"] = "local",
) -> bool:
    """Check if Calkit Cloud is available."""
    with patch.dict(os.environ, {"CALKIT_ENV": env}):
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
    not _calkit_cloud_available("staging"), reason="Calkit Cloud not available"
)
def test_calkitfilesystem_staging(monkeypatch):
    """Test CalkitFileSystem with staging environment."""
    monkeypatch.setenv("CALKIT_ENV", "staging")
    fs = ckfs.CalkitFileSystem()
    assert fs.base_url == "https://api.staging.calkit.io"
    assert fs.protocol == "ck"
    txt = uuid.uuid4().hex
    uri = "ck://calkit/example-basic/test_staging.txt"
    with fs.open(uri, "w") as f:
        f.write(txt)
    with fs.open(uri, "r") as f:
        read_txt = f.read()
    assert read_txt == txt
    info = fs.info(uri)
    assert info["size"] == len(txt)
    assert info["type"] == "file"
    res = fs.ls("ck://calkit/example-basic/")
    assert "calkit/example-basic/test_staging.txt" in res


@pytest.mark.skipif(
    not _calkit_cloud_available(), reason="Calkit Cloud not available"
)
def test_calkitfilesystem_dvc(tmp_dir):
    """Test CalkitFileSystem as a DVC remote."""
    subprocess.run(["calkit", "init"])
    subprocess.run(
        [
            "calkit",
            "dvc",
            "remote",
            "add",
            "calkit",
            "ck://calkit/example-basic/",
        ],
        check=True,
    )
    subprocess.run(
        ["calkit", "dvc", "remote", "default", "calkit"], check=True
    )
    with open("data.txt", "w") as f:
        f.write("hello dvc")
    subprocess.run(["calkit", "dvc", "add", "data.txt"], check=True)
    subprocess.run(["calkit", "dvc", "push"], check=True)
    subprocess.run(["calkit", "dvc", "pull"], check=True)


@pytest.mark.skipif(
    not _calkit_cloud_available("staging"), reason="Calkit Cloud not available"
)
def test_calkitfilesystem_dvc_staging(monkeypatch, tmp_dir):
    """Test CalkitFileSystem as a DVC remote against the staging
    environment.
    """
    monkeypatch.setenv("CALKIT_ENV", "staging")
    # Verify env var is set
    result = subprocess.run(
        ["python", "-c", "import os; print(os.environ.get('CALKIT_ENV'))"],
        capture_output=True,
        text=True,
    )
    print(f"Subprocess sees CALKIT_ENV={result.stdout.strip()}")
    assert result.stdout.strip() == "staging"
    subprocess.run(["calkit", "init"])
    subprocess.run(
        [
            "calkit",
            "dvc",
            "remote",
            "add",
            "calkit",
            "ck://calkit/example-basic/",
        ],
        check=True,
    )
    subprocess.run(
        ["calkit", "dvc", "remote", "default", "calkit"], check=True
    )
    with open("data.txt", "w") as f:
        f.write("hello dvc")
    subprocess.run(["calkit", "dvc", "add", "data.txt"], check=True)
    subprocess.run(["calkit", "dvc", "push"], check=True)
    subprocess.run(["calkit", "dvc", "pull"], check=True)
