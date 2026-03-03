"""Tests for the Calkit filesystem implementation."""

import subprocess
import uuid

import pytest

import calkit
from calkit import fs as ckfs


def test_parse_path_simple():
    """Test parsing a simple path without explicit domain."""
    owner, project, file_path = ckfs._parse_path("ck://owner/project/file.txt")
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"


def test_parse_path_simple_no_file():
    """Test parsing path with just owner/project."""
    owner, project, file_path = ckfs._parse_path("ck://owner/project")
    assert owner == "owner"
    assert project == "project"
    assert file_path == ""


def test_parse_path_nested_file():
    """Test parsing path with nested file structure."""
    owner, project, file_path = ckfs._parse_path(
        "ck://owner/project/data/nested/file.txt"
    )
    assert owner == "owner"
    assert project == "project"
    assert file_path == "data/nested/file.txt"


def test_parse_path_explicit_domain():
    """Test parsing path with explicit domain."""
    owner, project, file_path = ckfs._parse_path(
        "ck://calkit.io/owner/project/file.txt"
    )
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"


def test_parse_path_staging_domain():
    """Test parsing path with staging domain."""
    owner, project, file_path = ckfs._parse_path(
        "ck://staging.calkit.io/owner/project/file.txt"
    )
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"


def test_parse_path_localhost_domain():
    """Test parsing path with localhost domain."""
    owner, project, file_path = ckfs._parse_path(
        "ck://localhost:8000/owner/project/file.txt"
    )
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"


def test_parse_path_protocol_stripped():
    """Test parsing protocol-stripped path."""
    owner, project, file_path = ckfs._parse_path("owner/project/file.txt")
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"


def test_parse_path_protocol_stripped_localhost():
    """Test parsing protocol-stripped path with localhost."""
    owner, project, file_path = ckfs._parse_path(
        "localhost:8000/owner/project/file.txt"
    )
    assert owner == "owner"
    assert project == "project"
    assert file_path == "file.txt"


def test_parse_path_invalid_no_project():
    """Test that invalid paths raise ValueError."""
    with pytest.raises(ValueError, match="Invalid path format"):
        ckfs._parse_path("ck://owner")


def test_parse_path_invalid_empty():
    """Test that empty path raises ValueError."""
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
