"""Tests for the Calkit filesystem implementation."""

import os
import subprocess
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import HTTPError, Timeout

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
    fs._execute_operation(operation_info, "put", data=data, callback=callback)
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
    fs._xet_access = {}
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


def test_execute_operation_retries_transient_timeout_across_upload_paths():
    """Retries transient timeout for both simple and chunked upload flows."""
    import io

    with patch("calkit.fs.time.sleep", return_value=None):
        # Use case 1: simple presigned-url upload retries and rewinds stream.
        payload_simple = b"R" * 8
        start_positions = []
        session_simple = MagicMock()

        def _simple_side_effect(**kwargs):
            body = kwargs["data"]
            start_positions.append(body.tell())
            if len(start_positions) == 1:
                raise Timeout("read timeout")
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            return resp

        session_simple.request.side_effect = _simple_side_effect
        fs_simple = ckfs.CalkitFileSystem.__new__(ckfs.CalkitFileSystem)
        fs_simple._session = session_simple
        op_simple = {
            "access": {
                "kind": "presigned-url",
                "url": "https://storage.example.com/upload",
                "http_method": "PUT",
            }
        }
        fs_simple._execute_operation(
            op_simple,
            "put",
            file_obj=io.BytesIO(payload_simple),
            file_size=len(payload_simple),
        )
        assert start_positions == [0, 0]
        # Use case 2: chunked upload retries a timed-out chunk and continues.
        chunk_size = 5
        payload_chunked = b"T" * 13
        session_chunked = MagicMock()
        init_resp = MagicMock()
        init_resp.raise_for_status = MagicMock()
        init_resp.headers = {"Location": "https://example.com/session"}
        resp1 = MagicMock()
        resp1.status_code = 308
        resp1.headers = {"Range": "bytes=0-4"}
        resp2 = MagicMock()
        resp2.status_code = 308
        resp2.headers = {"Range": "bytes=0-9"}
        resp3 = MagicMock()
        resp3.status_code = 200
        resp3.headers = {}
        session_chunked.request.side_effect = [
            init_resp,
            Timeout("read timeout"),
            resp1,
            resp2,
            resp3,
        ]
        fs_chunked = ckfs.CalkitFileSystem.__new__(ckfs.CalkitFileSystem)
        fs_chunked._session = session_chunked
        op_chunked = {
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
        fs_chunked._execute_operation(
            op_chunked,
            "put",
            file_obj=io.BytesIO(payload_chunked),
            file_size=len(payload_chunked),
            callback=callback,
        )
        calls = [c.args[0] for c in callback.relative_update.call_args_list]
        assert calls == [5, 5, 3]


def test_execute_operation_retries_transient_5xx():
    """Retries a transient 5xx response from the storage backend."""
    import io

    with patch("calkit.fs.time.sleep", return_value=None):
        # A 503 from the backend is retried; the follow-up 200 is returned.
        statuses = [503, 200]
        seen = []

        def _side_effect(**kwargs):
            resp = MagicMock()
            resp.status_code = statuses[len(seen)]
            seen.append(resp.status_code)
            return resp

        session = MagicMock()
        session.request.side_effect = _side_effect
        fs = ckfs.CalkitFileSystem.__new__(ckfs.CalkitFileSystem)
        fs._session = session
        op = {
            "access": {
                "kind": "presigned-url",
                "url": "https://storage.example.com/upload",
                "http_method": "PUT",
            }
        }
        resp = fs._execute_operation(
            op,
            "put",
            file_obj=io.BytesIO(b"hello"),
            file_size=5,
        )
        assert seen == [503, 200]
        assert resp.status_code == 200


def _calkit_hub_available(hub: str = "localhost:5173") -> bool:
    """Check if the Calkit hub is available.

    Named by URL, and left with CALKIT_ENV=test in place, so credentials
    still come from the suite's own isolated config rather than the
    developer's real ones.
    """
    with patch.dict(os.environ, {"CALKIT_HUB": hub}):
        try:
            calkit.hub.get_current_user()
            return True
        except Exception:
            return False


@pytest.mark.skipif(
    not _calkit_hub_available(), reason="Calkit hub not available"
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
    not _calkit_hub_available("staging.calkit.io"),
    reason="Calkit hub not available",
)
def test_calkitfilesystem_staging(monkeypatch):
    """Test CalkitFileSystem with staging environment."""
    monkeypatch.setenv("CALKIT_HUB", "staging.calkit.io")
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
    not _calkit_hub_available(), reason="Calkit hub not available"
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
    not _calkit_hub_available("staging.calkit.io"),
    reason="Calkit hub not available",
)
def test_calkitfilesystem_dvc_staging(monkeypatch, tmp_dir):
    """Test CalkitFileSystem as a DVC remote against the staging
    environment.
    """
    monkeypatch.setenv("CALKIT_HUB", "staging.calkit.io")
    # Verify the env var reaches a subprocess, since DVC runs the
    # filesystem in one
    result = subprocess.run(
        ["python", "-c", "import os; print(os.environ.get('CALKIT_HUB'))"],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "staging.calkit.io"
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


def test_get_file_from_object_storage(tmp_path: Path) -> None:
    import hashlib
    import io

    fs = ckfs.CalkitFileSystem(
        endpoint_url="https://api.example.com", skip_instance_cache=True
    )
    op_info = {"access": {"kind": "presigned-url", "url": "u"}}
    with (
        patch.object(fs, "_get_fs_op_info", return_value=op_info),
        patch.object(fs, "isdir", return_value=False),
        patch.object(fs, "open", return_value=io.BytesIO(b"content")),
    ):
        nested = tmp_path / "new" / "dir" / "f.txt"
        fs.get_file("ck://o/p/f.txt", str(nested))
        assert nested.read_bytes() == b"content"
    with (
        patch.object(fs, "_get_fs_op_info", return_value=op_info),
        patch.object(fs, "isdir", return_value=True),
        patch.object(fs, "open") as open_remote,
    ):
        directory = tmp_path / "new" / "d"
        fs.get_file("ck://o/p/d", str(directory))
        assert directory.is_dir()
        open_remote.assert_not_called()
    # DVC directory manifests are checked like other objects
    manifest = tmp_path / "manifest"
    manifest.write_bytes(b'[{"md5": "abc", "relpath": "a.txt"}]')
    md5 = hashlib.md5(manifest.read_bytes()).hexdigest()
    obj_path = f"files/md5/{md5[:2]}/{md5[2:]}.dir"
    ckfs._check_dvc_md5(obj_path, str(manifest))
    manifest.write_bytes(b'[{"md5": "def", "relpath": "a.txt"}]')
    with pytest.raises(OSError, match="doesn't match its MD5"):
        ckfs._check_dvc_md5(obj_path, str(manifest))
    assert not manifest.exists()


def test_xet_transfers(tmp_path: Path) -> None:
    import hashlib
    import threading
    import time
    from types import SimpleNamespace
    from typing import Any

    content = b"some DVC object content"
    md5 = hashlib.md5(content).hexdigest()
    obj_path = f"files/md5/{md5[:2]}/{md5[2:]}"
    stored: dict[str, bytes] = {}
    upload_calls: list[list[str]] = []

    def upload_files(paths: list[str], *a: Any, **k: Any) -> list[Any]:
        upload_calls.append(paths)
        if len(upload_calls) == 1 and upload_gate is not None:
            upload_gate()
        for path in paths:
            with open(path, "rb") as f:
                stored["xethash"] = f.read()
        return [SimpleNamespace(hash="xethash") for _ in paths]

    def upload_bytes(datas: list[bytes], *a: Any, **k: Any) -> list[Any]:
        stored["xethash"] = datas[0]
        return [SimpleNamespace(hash="xethash")]

    def download_files(infos: list[Any], *a: Any) -> None:
        download_tokens.append(a[1][0])
        for info in infos:
            with open(info.destination_path, "wb") as f:
                f.write(stored[info.hash])

    upload_gate = None
    download_tokens: list[str] = []
    fake_xet = SimpleNamespace(
        upload_files=upload_files,
        upload_bytes=upload_bytes,
        download_files=download_files,
        PyXetDownloadInfo=lambda **kw: SimpleNamespace(**kw),
    )
    access = {
        "kind": "hf-xet",
        "bucket": "someone/one",
        "cas_url": "https://cas.example.com",
        "access_token": "xet_token",
        "expires_at_unixts": 2_000_000_000,
    }
    fs = ckfs.CalkitFileSystem(
        endpoint_url="https://api.example.com", skip_instance_cache=True
    )
    local = tmp_path / "upload.bin"
    local.write_bytes(content)
    # Platforms without hf-xet get a clear error before anything is sent
    with (
        patch.dict("sys.modules", {"hf_xet": None}),
        patch.object(
            fs,
            "_get_fs_op_info",
            return_value={"access": access | {"operation": "upload"}},
        ),
        patch.object(ckfs.calkit.hub, "post") as post,
        pytest.raises(RuntimeError, match="hf-xet"),
    ):
        fs.put_file(str(local), f"ck://owner/project/{obj_path}")
    post.assert_not_called()
    # Uploading a file registers its Xet hash at the same path
    with (
        patch.dict("sys.modules", {"hf_xet": fake_xet}),
        patch.object(
            fs,
            "_get_fs_op_info",
            return_value={"access": access | {"operation": "upload"}},
        ) as get_op,
        patch.object(ckfs.calkit.hub, "post") as post,
    ):
        fs.put_file(str(local), f"ck://owner/project/{obj_path}")
        post.assert_called_once()
        assert post.call_args.args[0] == "/projects/owner/project/fs/ops/batch"
        assert post.call_args.kwargs["json"] == {
            "operation": "register",
            "paths": [obj_path],
            "xet_hashes": {obj_path: "xethash"},
            "bucket": "someone/one",
        }
        assert stored["xethash"] == content
        # The access covers the whole bucket, so the next upload reuses it
        fs.put_file(str(local), "ck://owner/project/again.bin")
        get_op.assert_called_once()
        # Files DVC puts while an upload is in flight go up together next,
        # in one Xet session and one registration
        n = 8
        batcher = fs._xet_batchers[("owner", "project", "put")]
        upload_calls.clear()
        post.reset_mock()

        def wait_for_others() -> None:
            deadline = time.time() + 10
            while len(batcher._waiting) < n - 1:
                assert time.time() < deadline
                time.sleep(0.01)

        upload_gate = wait_for_others
        threads = [
            threading.Thread(
                target=fs.put_file,
                args=(str(local), f"ck://owner/project/f{i}.bin"),
            )
            for i in range(n)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        upload_gate = None
        assert [len(c) for c in upload_calls] == [1, n - 1]
        assert post.call_count == 2
        assert len(post.call_args.kwargs["json"]["paths"]) == n - 1
        # A failed registration fails the uploads waiting on it
        post.side_effect = RuntimeError("hub down")
        with pytest.raises(RuntimeError, match="hub down"):
            fs.put_file(str(local), "ck://owner/project/fails.bin")
        # Access that's about to expire isn't reused
        post.side_effect = None
        fs._xet_access[("owner", "project", "put", None)] = access | {
            "expires_at_unixts": 0
        }
        fs.put_file(str(local), "ck://owner/project/later.bin")
        assert get_op.call_count == 2
        # If the project's storage changed since the access was given, the
        # upload starts over with new access
        conflict = MagicMock(status_code=409)
        post.reset_mock()
        post.side_effect = [HTTPError("409: changed", response=conflict), None]
        fs.put_file(str(local), "ck://owner/project/switched.bin")
        assert get_op.call_count == 3
        assert post.call_count == 2
        # If it keeps changing, it's an error rather than a loop
        post.side_effect = HTTPError("409: changed", response=conflict)
        with pytest.raises(OSError, match="keeps changing"):
            fs.put_file(str(local), "ck://owner/project/flapping.bin")
        post.side_effect = None
        # And storage that's no longer HF gets a regular upload
        presigned = {"access": {"kind": "presigned-url", "url": "u"}}
        get_op.return_value = presigned
        post.side_effect = HTTPError("409: changed", response=conflict)
        response = MagicMock()
        with patch.object(
            fs, "_execute_operation", return_value=response
        ) as execute:
            fs.put_file(str(local), "ck://owner/project/to-hub.bin")
        assert execute.call_args.args[0] == presigned
        response.raise_for_status.assert_called_once()
        post.side_effect = None
        get_op.return_value = {"access": access | {"operation": "upload"}}
    # Writing through a file object uploads its bytes the same way
    stored.clear()
    with (
        patch.dict("sys.modules", {"hf_xet": fake_xet}),
        patch.object(
            fs,
            "_get_fs_op_info",
            return_value={"access": access | {"operation": "upload"}},
        ),
        patch.object(ckfs.calkit.hub, "post") as post,
    ):
        with fs.open("ck://owner/project/other.txt", "wb") as f:
            f.write(content)
    assert stored["xethash"] == content
    assert post.call_args.kwargs["json"]["paths"] == ["other.txt"]
    # Downloading checks the content against the MD5 in the path, and a
    # file the batch lookup doesn't find in HF is fetched on its own
    download = access | {
        "operation": "download",
        "xet_hash": "xethash",
        "size": len(content),
    }
    with (
        patch.dict("sys.modules", {"hf_xet": fake_xet}),
        patch.object(
            fs,
            "_get_fs_op_info_batch",
            return_value={"backend": "s3", "results": {}},
        ),
        patch.object(fs, "_get_fs_op_info", return_value={"access": download}),
    ):
        out = tmp_path / "out.bin"
        fs.get_file(f"ck://owner/project/{obj_path}", str(out))
        assert out.read_bytes() == content
        assert fs.cat_file(f"ck://owner/project/{obj_path}", 5, 8) == b"DVC"
        # Content that doesn't match its MD5 is an error, and not left behind
        stored["xethash"] = b"tampered"
        bad = tmp_path / "bad.bin"
        with pytest.raises(OSError, match="doesn't match its MD5"):
            fs.get_file(f"ck://owner/project/{obj_path}", str(bad))
        assert not bad.exists()
        # Empty files don't need a download
        empty = download | {"xet_hash": "x", "size": 0}
        with patch.object(
            fs, "_get_fs_op_info", return_value={"access": empty}
        ):
            out = tmp_path / "empty.bin"
            fs.get_file("ck://owner/project/empty.txt", str(out))
            assert out.read_bytes() == b""
    # With the hash from a batch lookup, a download doesn't ask the hub
    # about the file
    stored["xethash"] = content
    batch = {
        "backend": "hf",
        "results": {
            obj_path: {
                "info": {"name": obj_path, "size": len(content)}
                | {"xet_hash": "xethash", "bucket": "someone/one"}
            }
        },
    }
    with (
        patch.dict("sys.modules", {"hf_xet": fake_xet}),
        patch.object(fs, "_get_fs_op_info_batch", return_value=batch) as bop,
        patch.object(fs, "_get_fs_op_info") as get_op,
    ):
        out = tmp_path / "out2.bin"
        fs.get_file(f"ck://owner/project/{obj_path}", str(out))
        assert out.read_bytes() == content
        get_op.assert_not_called()
        bop.assert_called_once()
        # And one already looked up isn't looked up again
        fs.get_file(f"ck://owner/project/{obj_path}", str(out))
        bop.assert_called_once()
    # A project that moved between buckets downloads each object with the
    # token for the bucket it's in
    other = b"in the previous bucket"
    other_md5 = hashlib.md5(other).hexdigest()
    other_path = f"files/md5/{other_md5[:2]}/{other_md5[2:]}"
    stored["otherhash"] = other
    batch["results"][other_path] = {
        "info": {"name": other_path, "size": len(other)}
        | {"xet_hash": "otherhash", "bucket": "someone/two"}
    }
    old_access = access | {"bucket": "someone/two", "access_token": "old"}
    download_tokens.clear()
    with (
        patch.dict("sys.modules", {"hf_xet": fake_xet}),
        patch.object(fs, "_get_fs_op_info_batch", return_value=batch),
        patch.object(
            fs, "_get_fs_op_info", return_value={"access": old_access}
        ) as get_op,
    ):
        fs._xet_objects.clear()
        batcher = fs._xet_batchers[("owner", "project", "get")]
        outcomes = batcher._send(
            [
                (obj_path, str(tmp_path / "a.bin"), ckfs.DEFAULT_CALLBACK),
                (other_path, str(tmp_path / "b.bin"), ckfs.DEFAULT_CALLBACK),
            ]
        )
    assert outcomes == [None, None]
    assert (tmp_path / "a.bin").read_bytes() == content
    assert (tmp_path / "b.bin").read_bytes() == other
    assert sorted(download_tokens) == ["old", "xet_token"]
    get_op.assert_called_once()
    assert get_op.call_args.args[2] == other_path
