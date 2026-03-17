"""Tests for the ``releases`` module."""

import subprocess

import git

from calkit.releases import ls_files


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
