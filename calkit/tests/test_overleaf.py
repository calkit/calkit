"""Tests for the ``overleaf`` module."""

import os
import subprocess

import git

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
