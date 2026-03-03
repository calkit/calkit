"""Tests for the Calkit filesystem implementation."""

import subprocess
import uuid

import pytest

import calkit
from calkit import fs as ckfs


def test_parse_path():
    fs = ckfs.CalkitFileSystem()
    owner, project, file_path = fs._parse_path("ck://owner/project/file.txt")
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"
    owner, project, file_path = fs._parse_path("ck://owner/project")
    assert owner == "owner"
    assert project == "project"
    assert file_path == ""
    owner, project, file_path = fs._parse_path(
        "ck://owner/project/data/nested/file.txt"
    )
    assert owner == "owner"
    assert project == "project"
    assert file_path == "data/nested/file.txt"
    owner, project, file_path = fs._parse_path("owner/project/file.txt")
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"
    with pytest.raises(ValueError, match="Invalid path format"):
        fs._parse_path("ck://owner")
    with pytest.raises(ValueError, match="Invalid path format"):
        fs._parse_path("ck://")
    # Now test with strip_path_prefix
    fs = ckfs.CalkitFileSystem(strip_path_prefix="files/md5/")
    owner, project, file_path = fs._parse_path(
        "ck://owner/project/files/md5/abc123/file.txt"
    )
    assert owner == "owner"
    assert project == "project"
    assert file_path == "abc123/file.txt"


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
