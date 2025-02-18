"""Tests for the ``core`` module."""

import subprocess

import git

import calkit


def test_find_project_dirs():
    calkit.find_project_dirs()
    assert calkit.find_project_dirs(relative=False)


def test_to_kebab_case():
    assert calkit.to_kebab_case("THIS IS") == "this-is"
    assert calkit.to_kebab_case("this_is_my-Project") == "this-is-my-project"


def test_detect_project_name(tmp_dir):
    subprocess.check_output(["calkit", "init"])
    repo = git.Repo()
    repo.create_remote("origin", "https://github.com/someone/some-repo.git")
    assert calkit.detect_project_name() == "someone/some-repo"
    with open("calkit.yaml", "w") as f:
        f.write("owner: someone-else\nname: some-project\n")
    assert calkit.detect_project_name() == "someone-else/some-project"
