"""Tests for the ``releases`` module."""

import subprocess
import sys
import zipfile

import bibtexparser
import git
import pytest

import calkit
from calkit.releases import (
    check_project_release_archive,
    check_release_reproducibility,
    create_bibtex,
    ls_files,
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
    files = ls_files()
    assert "submodule/submodule-file.txt" in files


def test_check_release_reproducibility_runs_from_project_root(
    tmp_dir, monkeypatch
):
    subprocess.run(["calkit", "init"], check=True)
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"pipeline": {"stages": {}}}, f)
    with open("dvc.yaml", "w") as f:
        f.write("stages: {}\n")

    calls = []

    def fake_run(cmd, check=True):
        calls.append(cmd)

    monkeypatch.setattr("calkit.releases.subprocess.run", fake_run)

    check_release_reproducibility(verbose=True)

    assert calls == [[sys.executable, "-m", "calkit", "run", "--verbose"]]


def test_check_project_release_archive_passes_when_only_skipped_stages(
    tmp_dir, monkeypatch
):
    zip_path = "archive.zip"
    with zipfile.ZipFile(zip_path, "w") as zipf:
        zipf.writestr("calkit.yaml", "title: Test\n")
        zipf.writestr("dvc.yaml", "stages: {}\n")

    monkeypatch.setattr(
        "calkit.cli.main.core.run",
        lambda quiet=False, verbose=False: {
            "stage_run_info": {"build": {"status": "skipped"}}
        },
    )

    check_project_release_archive(zip_path)


def test_check_project_release_archive_fails_when_stage_runs(
    tmp_dir, monkeypatch
):
    zip_path = "archive.zip"
    with zipfile.ZipFile(zip_path, "w") as zipf:
        zipf.writestr("calkit.yaml", "title: Test\n")
        zipf.writestr("dvc.yaml", "stages: {}\n")

    monkeypatch.setattr(
        "calkit.cli.main.core.run",
        lambda quiet=False, verbose=False: {
            "stage_run_info": {"build": {"status": "completed"}}
        },
    )

    with pytest.raises(RuntimeError, match="not up-to-date"):
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
