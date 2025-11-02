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
    ol_repo = _make_temp_overleaf_project(pid)
    ol_repo.git.config(["receive.denyCurrentBranch", "ignore"])
    subprocess.run(
        ["calkit", "init"],
        check=True,
    )
    repo = git.Repo()
    tmp_remote = f"/tmp/overleaf-sync-remotes/{pid}"
    os.makedirs(tmp_remote, exist_ok=True)
    remote_repo = git.Repo.init(path=tmp_remote, bare=True)
    remote_repo.git.config(["receive.denyCurrentBranch", "ignore"])
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
    with open("ol-project/main.tex") as f:
        txt = f.read()
        assert "This is the initial text" in txt
    # Check the TeX environment and pipeline was created properly
    ck_info = calkit.load_calkit_info()
    env = ck_info["environments"]["tex"]
    assert env["kind"] == "docker"
    assert env["image"] == "texlive/texlive:latest-full"
    stage = ck_info["pipeline"]["stages"]["build-ol-project"]
    assert stage["kind"] == "latex"
    assert stage["environment"] == "tex"
    assert stage["target_path"] == "ol-project/main.tex"
    # Test that we can sync
    subprocess.run(["calkit", "overleaf", "sync"], check=True)
    # TODO: Test that we can properly resolve a merge conflict
    with open(os.path.join(ol_repo.working_dir, "main.tex"), "a") as f:
        f.write("\nHere's another line from Overleaf")
    ol_repo.git.commit(["main.tex", "-m", "Update on Overleaf"])
    with open("ol-project/main.tex", "a") as f:
        f.write("\nHere's another line from main project")
    repo.git.commit(["ol-project/main.tex", "-m", "Local edit"])
    res = subprocess.run(["calkit", "overleaf", "sync"], capture_output=True)
    assert res.returncode != 0
    with open("ol-project/main.tex") as f:
        txt = f.read()
    assert ">>>>>>>" in txt
    # Now let's resolve the commit without actually editing the file
    subprocess.run(["calkit", "overleaf", "sync", "--resolve"], check=True)
    # Now make another change on Overleaf but allow the sync to succeed
    with open(os.path.join(ol_repo.working_dir, "main.tex"), "a") as f:
        f.write("\nHere's another line from Overleaf")
    ol_repo.git.commit(["main.tex", "-m", "Update on Overleaf"])
    subprocess.run(["calkit", "overleaf", "sync"], check=True)
