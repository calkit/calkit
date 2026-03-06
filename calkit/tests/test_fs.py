"""Tests for the Calkit filesystem implementation."""

import os
import subprocess
import uuid
from typing import Literal
from unittest.mock import patch

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
