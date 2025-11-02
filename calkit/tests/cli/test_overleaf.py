"""Tests for the Overleaf CLI commands."""

import os
import subprocess
import uuid

import git

import calkit


def _make_temp_overleaf_project(project_id: str) -> git.Repo:
    """Creates an Overleaf project Git repo that can be imported.

    Returns the directory of the project so it can be used as an import URL.
    """
    d = calkit.overleaf.get_git_remote_url(
        project_id=project_id, token="doesnt matter"
    )
    os.makedirs(d, exist_ok=True)
    repo = git.Repo.init(path=d)
    with open(os.path.join(d, "main.tex"), "w") as f:
        f.write("This is the initial text")
    repo.git.add("main.tex")
    repo.git.commit(["-m", "Initial commit"])
    return repo


def test_overleaf(tmp_dir):
    # First, create a temporary repo to represent the Overleaf project
    pid = str(uuid.uuid4())
    _ = _make_temp_overleaf_project(pid)
    subprocess.run(
        ["calkit", "init"],
        check=True,
    )
    repo = git.Repo()
    tmp_remote = f"/tmp/overleaf-sync-remotes/{pid}"
    os.makedirs(tmp_remote, exist_ok=True)
    git.Repo.init(path=tmp_remote, bare=True)
    repo.git.remote(["add", "origin", tmp_remote])
    ol_url = calkit.overleaf.get_git_remote_url(pid, "no token")
    assert os.environ["CALKIT_ENV"] == "test"
    assert os.environ["CALKIT_TEST_OVERLEAF_TOKEN"] == "none"
    config = calkit.config.read()
    assert config.overleaf_token == "none"
    subprocess.run(
        [
            "calkit",
            "overleaf",
            "import",
            ol_url,
            "ol-project",
            "--title",
            "My cool Overleaf project",
        ],
        check=True,
    )
    # Test that we can sync
    subprocess.run(["calkit", "overleaf", "sync"], check=True)
    # TODO: Test that we can properly resolve a merge conflict
