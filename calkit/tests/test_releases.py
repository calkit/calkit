"""Tests for the ``releases`` module."""

import os
import subprocess
import sys
import zipfile

import bibtexparser
import git
import pytest

from calkit.dvc.zip import write_zip_path_map
from calkit.releases import (
    check_project_release_archive,
    create_bibtex,
    ls_files,
    zip_paths,
)


def test_ls_files(tmp_dir):
    subprocess.run(["calkit", "init"], check=True)
    # Create some files and add them to git and dvc
    (tmp_dir / "file1.txt").write_text("This is file 1.")
    (tmp_dir / "file2.txt").write_text("This is file 2.")
    subprocess.run(["git", "add", "file1.txt"], check=True)
    subprocess.run(["git", "commit", "-m", "Add file1.txt"], check=True)
    subprocess.run(["calkit", "dvc", "add", "file2.txt"], check=True)
    # Get the list of files to be released
    files = ls_files()
    assert "file1.txt" in files
    assert "file2.txt" in files
    # Now add some files in a git submodule and ensure they are included
    submodule_source = tmp_dir / "submodule-source"
    submodule_repo = git.Repo.init(submodule_source)
    (submodule_source / "submodule-file.txt").write_text(
        "This file lives in the submodule."
    )
    submodule_repo.git.add("submodule-file.txt")
    submodule_repo.index.commit("Add submodule file")
    subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(submodule_source),
            "submodule",
        ],
        check=True,
    )
    subprocess.run(["git", "commit", "-m", "Add submodule"], check=True)
    # Ensure all .dvc/cache content is included by ls_files.
    os.makedirs(".dvc/cache/aa", exist_ok=True)
    os.makedirs(".dvc/cache/files/md5/bb", exist_ok=True)
    os.makedirs(".dvc/cache/runs/cc/hash", exist_ok=True)
    (tmp_dir / ".dvc" / "cache" / "aa" / "legacy").write_text("x")
    (
        tmp_dir / ".dvc" / "cache" / "files" / "md5" / "bb" / "modern"
    ).write_text("y")
    (tmp_dir / ".dvc" / "cache" / "runs" / "cc" / "hash" / "run").write_text(
        "z"
    )
    files = ls_files()
    assert "submodule/submodule-file.txt" in files
    assert ".dvc/cache/aa/legacy" in files
    assert ".dvc/cache/files/md5/bb/modern" in files
    assert ".dvc/cache/runs/cc/hash/run" in files
    # Ensure files from unzipped dvc-zip workspace folders are included;
    # these folders are ignored by both Git and DVC
    os.makedirs("my-zip-workspace/sub", exist_ok=True)
    (tmp_dir / "my-zip-workspace" / "data.txt").write_text("data")
    (tmp_dir / "my-zip-workspace" / "sub" / "nested.txt").write_text("nested")
    write_zip_path_map(
        {"my-zip-workspace": ".calkit/zip/files/my-zip-workspace.zip"}
    )
    files = ls_files()
    assert "my-zip-workspace/data.txt" in files
    assert "my-zip-workspace/sub/nested.txt" in files


def test_check_project_release_archive_passes_when_pipeline_is_current(
    tmp_dir, monkeypatch
):
    zip_path = "archive.zip"
    with zipfile.ZipFile(zip_path, "w") as zipf:
        zipf.writestr("calkit.yaml", "title: Test\n")
        zipf.writestr("dvc.yaml", "stages: {}\n")

    calls = []

    def fake_run(cmd, cwd=None, check=True):
        calls.append((cmd, cwd, check))

    monkeypatch.setattr("calkit.releases.subprocess.run", fake_run)
    check_project_release_archive(zip_path)
    assert len(calls) == 1
    assert calls[0][0] == [sys.executable, "-m", "calkit", "run"]
    assert calls[0][2] is True
    assert calls[0][1] is not None


def test_check_project_release_archive_fails_when_stages_out_of_date(
    tmp_dir, monkeypatch
):
    zip_path = "archive.zip"
    with zipfile.ZipFile(zip_path, "w") as zipf:
        zipf.writestr("calkit.yaml", "title: Test\n")
        zipf.writestr("dvc.yaml", "stages: {}\n")

    def fake_run(cmd, cwd=None, check=True):
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

    monkeypatch.setattr("calkit.releases.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="calkit run` failed"):
        check_project_release_archive(zip_path)


def test_create_bibtex():
    entry = create_bibtex(
        authors=[{"first_name": "Alice", "last_name": "Smith"}],
        release_date="2026-03-25",
        title="Test title",
        doi="10.1234/example",
        record_id="123",
    )
    entries = bibtexparser.loads(entry).entries
    assert len(entries) == 1
    entry = create_bibtex(
        authors=[{"first_name": "A", "last_name": "van der Waals"}],
        release_date="2026-03-25",
        title="Test title",
        doi="10.1234/example",
        record_id="abc-123",
    )
    entries = bibtexparser.loads(entry).entries
    assert len(entries) == 1
    entry = create_bibtex(
        authors=[{"first_name": "A", "last_name": "Smith"}],
        release_date="2026-03-25",
        title="Test title",
        doi=None,
        record_id=None,
    )
    entries = bibtexparser.loads(entry).entries
    assert len(entries) == 1


def test_zip_paths(tmp_dir):
    os.makedirs("data/sub", exist_ok=True)
    with open("data/sub/file.txt", "w") as f:
        f.write("hello")
    with open("root.txt", "w") as f:
        f.write("root")
    zip_path = "archive.zip"
    zip_paths(zip_path, ["data", "root.txt"])
    with zipfile.ZipFile(zip_path) as zipf:
        names = set(zipf.namelist())
        assert "data/sub/file.txt" in names
        assert "root.txt" in names
        assert zipf.getinfo("root.txt").compress_type == zipfile.ZIP_DEFLATED
