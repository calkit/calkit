"""Tests for the ``overleaf`` module."""

import json
import os
import subprocess

import git
import pytest

import calkit


def _commit_all(repo: git.Repo, message: str) -> None:
    repo.git.add(["-A"])
    repo.git.commit(["-m", message])


def test_get_sync_status(tmp_dir):
    subprocess.run(["calkit", "init"], check=True)
    repo = git.Repo()
    os.makedirs(os.path.join("paper", "figures"))
    with open(os.path.join("paper", "main.tex"), "w") as f:
        f.write(
            "\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n"
        )
    fig_path = os.path.join("paper", "figures", "fig.png")
    with open(fig_path, "wb") as fb:
        fb.write(b"figure version 1")
    ck_info = calkit.load_calkit_info()
    ck_info["figures"] = [
        {"path": "paper/figures/fig.png", "title": "A figure"}
    ]
    ck_info["overleaf_sync"] = {
        "paper": {"url": "https://www.overleaf.com/project/abc123"}
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    _commit_all(repo, "Add paper")
    # Stand up a repo to stand in for the Overleaf project, which starts out
    # with only the TeX file, so the figure has never been pushed
    overleaf_dir = tmp_dir / "overleaf"
    os.makedirs(overleaf_dir)
    overleaf_repo = git.Repo.init(path=overleaf_dir)
    with open(os.path.join(overleaf_dir, "main.tex"), "w") as f:
        f.write(
            "\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n"
        )
    _commit_all(overleaf_repo, "Initial commit")
    sync_info = calkit.overleaf.get_sync_info()["paper"]
    assert sync_info["project_id"] == "abc123"
    status = calkit.overleaf.get_sync_status(
        main_repo=repo,
        overleaf_repo=overleaf_repo,
        path_in_project="paper",
        sync_info_for_path=sync_info,
    )
    assert status["overleaf_project_id"] == "abc123"
    assert not status["in_sync"]
    assert status["commits_from_overleaf"] == 0
    pushes = {f["path"]: f for f in status["files_to_push"]}
    assert pushes["figures/fig.png"]["state"] == "new"
    assert pushes["figures/fig.png"]["figure"]
    assert pushes["figures/fig.png"]["project_path"] == "paper/figures/fig.png"
    # The TeX file matches on both sides, so it isn't pending a push, and
    # wouldn't be flagged as a figure regardless
    assert "main.tex" not in pushes
    # Push the figure by hand to represent a completed sync
    os.makedirs(os.path.join(overleaf_dir, "figures"))
    with open(os.path.join(overleaf_dir, "figures", "fig.png"), "wb") as fb:
        fb.write(b"figure version 1")
    _commit_all(overleaf_repo, "Add figure")
    sync_info["last_sync_commit"] = overleaf_repo.head.commit.hexsha
    status = calkit.overleaf.get_sync_status(
        main_repo=repo,
        overleaf_repo=overleaf_repo,
        path_in_project="paper",
        sync_info_for_path=sync_info,
    )
    assert status["in_sync"]
    assert status["files_to_push"] == []
    assert status["files_to_delete"] == []
    # Regenerating the figure locally leaves Overleaf out of date
    with open(fig_path, "wb") as fb:
        fb.write(b"figure version 2, which is longer")
    _commit_all(repo, "Update figure")
    status = calkit.overleaf.get_sync_status(
        main_repo=repo,
        overleaf_repo=overleaf_repo,
        path_in_project="paper",
        sync_info_for_path=sync_info,
    )
    assert not status["in_sync"]
    pushes = {f["path"]: f for f in status["files_to_push"]}
    assert pushes["figures/fig.png"]["state"] == "modified"
    assert pushes["figures/fig.png"]["figure"]
    # A same-size edit still counts as modified, since sizes only serve to
    # skip reading files that obviously match
    with open(fig_path, "wb") as fb:
        fb.write(b"figure version 3, which is longer")
    _commit_all(repo, "Update figure again")
    status = calkit.overleaf.get_sync_status(
        main_repo=repo,
        overleaf_repo=overleaf_repo,
        path_in_project="paper",
        sync_info_for_path=sync_info,
    )
    assert [f["path"] for f in status["files_to_push"]] == ["figures/fig.png"]
    # Edits made on Overleaf show up as commits waiting to come back
    with open(os.path.join(overleaf_dir, "main.tex"), "a") as f:
        f.write("\n% Edited in Overleaf\n")
    _commit_all(overleaf_repo, "Edit on Overleaf")
    status = calkit.overleaf.get_sync_status(
        main_repo=repo,
        overleaf_repo=overleaf_repo,
        path_in_project="paper",
        sync_info_for_path=sync_info,
    )
    assert status["commits_from_overleaf"] == 1
    assert status["overleaf_commit"] == overleaf_repo.head.commit.hexsha
    assert status["project_commit"] == repo.head.commit.hexsha
    # A file removed from the project should be deleted from Overleaf
    os.remove(fig_path)
    ck_info = calkit.load_calkit_info()
    ck_info["figures"] = []
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    _commit_all(repo, "Remove figure")
    status = calkit.overleaf.get_sync_status(
        main_repo=repo,
        overleaf_repo=overleaf_repo,
        path_in_project="paper",
        sync_info_for_path=sync_info,
    )
    deletes = [f["path"] for f in status["files_to_delete"]]
    assert deletes == ["figures/fig.png"]
    assert status["files_to_delete"][0]["figure"]


def test_sync_cited_content(tmp_dir):
    import shutil

    subprocess.run(["calkit", "init"], check=True)
    repo = git.Repo()
    os.makedirs("figures")
    with open(os.path.join("figures", "plot.png"), "wb") as fb:
        fb.write(b"png")
    os.makedirs("results")
    with open(os.path.join("results", "m.json"), "w") as f:
        f.write('{"x": 1.5}')
    os.makedirs("paper")
    main_tex = (
        "\\documentclass{article}\n\\usepackage{calkit}\n"
        "\\begin{document}\n\\ckfigure{figures/plot.png}\n"
        "\\ckvalue{results/m.json}{x}\n\\end{document}\n"
    )
    with open(os.path.join("paper", "main.tex"), "w") as f:
        f.write(main_tex)
    ck_info = calkit.load_calkit_info()
    ck_info["overleaf_sync"] = {
        "paper": {"url": "https://www.overleaf.com/project/abc123"}
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    overleaf_dir = tmp_dir / "overleaf"
    os.makedirs(overleaf_dir)
    overleaf_repo = git.Repo.init(path=overleaf_dir)
    with open(os.path.join(overleaf_dir, "main.tex"), "w") as f:
        f.write(main_tex)
    _commit_all(overleaf_repo, "Initial commit")
    sync_info = calkit.overleaf.get_sync_info()["paper"]

    def status() -> dict:
        return calkit.overleaf.get_sync_status(
            main_repo=repo,
            overleaf_repo=overleaf_repo,
            path_in_project="paper",
            sync_info_for_path=sync_info,
        )

    # Checking brings in what's cited, including calkit.sty, which is
    # committed with the document like any other file
    status()
    _commit_all(repo, "Add paper")
    pushes = {f["path"] for f in status()["files_to_push"]}
    assert pushes == {
        "calkit.sty",
        "_calkit/figures/plot.png",
        "_calkit/values.tex",
    }
    # Nothing under _calkit is committed to the project
    assert not repo.ignored("paper/calkit.sty")
    assert repo.ignored("paper/_calkit/values.tex")
    # Represent a completed sync
    for rel in pushes:
        os.makedirs(os.path.dirname(overleaf_dir / rel) or ".", exist_ok=True)
        shutil.copy(os.path.join("paper", rel), overleaf_dir / rel)
    _commit_all(overleaf_repo, "Sync")
    sync_info["last_sync_commit"] = overleaf_repo.head.commit.hexsha
    assert status()["in_sync"]
    # An edit made on Overleaf to a copy isn't pulled back
    paths = calkit.overleaf.OverleafSyncPaths(
        main_repo=repo,
        overleaf_repo=overleaf_repo,
        path_in_project="paper",
        sync_info_for_path=sync_info,
    )
    assert "_calkit/values.tex" not in paths.files_to_copy_from_overleaf
    # A new result is waiting to be pushed
    with open(os.path.join("results", "m.json"), "w") as f:
        f.write('{"x": 2.5}')
    pushes = {f["path"] for f in status()["files_to_push"]}
    assert pushes == {"_calkit/values.tex"}
    # A figure no longer cited is deleted from Overleaf
    with open(os.path.join("paper", "main.tex"), "w") as f:
        f.write(main_tex.replace("\\ckfigure{figures/plot.png}\n", ""))
    _commit_all(repo, "Drop figure")
    deletes = [f["path"] for f in status()["files_to_delete"]]
    assert deletes == ["_calkit/figures/plot.png"]


def test_write_sync_info_without_calkit_dir(tmp_dir):
    """A repo that has never used Calkit locally has no ``.calkit`` dir.

    That is the hub's normal case: it clones a project and imports an
    Overleaf document into it, so nothing has created the directory yet.
    """
    fpath = calkit.overleaf.write_sync_info(
        synced_path="paper",
        info={"project_id": "abc123"},
        wdir=os.getcwd(),
    )
    assert os.path.isfile(fpath)
    with open(fpath) as f:
        written = json.load(f)
    assert written["paper"]["project_id"] == "abc123"


def test_pull(tmp_dir):
    # Stand up a repo for the Overleaf project and clone it
    overleaf_dir = tmp_dir / "overleaf"
    overleaf_repo = git.Repo.init(overleaf_dir)
    (overleaf_dir / "main.tex").write_text("v1")
    _commit_all(overleaf_repo, "Initial commit")
    clone = git.Repo.clone_from(overleaf_dir, tmp_dir / "clone")
    clone_dir = tmp_dir / "clone"
    # Leave the clone diverged and dirty, like after a sync whose push failed,
    # with a conflicting edit made on Overleaf in the meantime
    (clone_dir / "main.tex").write_text("local")
    _commit_all(clone, "Sync with Calkit project")
    (clone_dir / "main.tex").write_text("uncommitted")
    (clone_dir / "leftover.tex").write_text("untracked")
    (clone_dir / ".gitignore").write_text("*.bib\n")
    (clone_dir / "refs.bib").write_text("ignored")
    (overleaf_dir / "main.tex").write_text("v2")
    _commit_all(overleaf_repo, "Edit on Overleaf")
    calkit.overleaf.pull(clone)
    assert clone.head.commit == overleaf_repo.head.commit
    assert (clone_dir / "main.tex").read_text() == "v2"
    assert not (clone_dir / "leftover.tex").exists()
    assert not (clone_dir / "refs.bib").exists()
    assert not clone.is_dirty(untracked_files=True)
    # A fetch failure should show Git's error, without the token, and only
    # give token advice for authentication failures
    clone.git.remote("set-url", "origin", f"file://{tmp_dir}/missing")
    with pytest.raises(RuntimeError) as e:
        calkit.overleaf.pull(clone)
    msg = str(e.value)
    assert "Failed to pull from Overleaf" in msg
    assert "missing" in msg
    assert "overleaf_token" not in msg
    clone.git.remote(
        "set-url", "origin", "https://git:secret@127.0.0.1:9/project"
    )
    with pytest.raises(RuntimeError) as e:
        calkit.overleaf.pull(clone)
    msg = str(e.value)
    assert "127.0.0.1" in msg
    assert "secret" not in msg
    # Overleaf rejecting the token should be told apart from other failures
    rejected = git.GitCommandError(
        ["git", "fetch"],
        128,
        stderr="fatal: Authentication failed for 'https://git.overleaf.com/x/'",
    )
    err = calkit.overleaf._git_error(rejected, "pull")
    assert isinstance(err, calkit.overleaf.AuthError)
    assert "expired" in str(err)
    assert not isinstance(
        calkit.overleaf._git_error(
            git.GitCommandError(["git", "fetch"], 128, stderr="nope"), "pull"
        ),
        calkit.overleaf.AuthError,
    )


def test_lock(tmp_dir):
    from filelock import FileLock, Timeout

    lock_path = calkit.overleaf.get_project_dir("abc123") + ".lock"
    # Another process can't take the lock while a sync holds it
    with calkit.overleaf.lock("abc123"):
        with pytest.raises(Timeout):
            FileLock(lock_path).acquire(timeout=0)
    # It's released afterwards, even if the sync fails
    with pytest.raises(RuntimeError):
        with calkit.overleaf.lock("abc123"):
            raise RuntimeError("Sync failed")
    other = FileLock(lock_path)
    other.acquire(timeout=0)
    other.release()
