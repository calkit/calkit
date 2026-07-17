"""Tests for the Overleaf CLI commands."""

import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import git
from typer.testing import CliRunner

import calkit
from calkit.cli.overleaf import _extract_title_from_tex, overleaf_app
from calkit.git import ls_files

runner = CliRunner()


def test_overleaf_status_alias_st_resolves():
    result = runner.invoke(overleaf_app, ["st"])
    assert result.exit_code == 1
    assert "No Overleaf sync info found" in result.output


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
    def get_overleaf_tree(repo: git.Repo) -> set[str]:
        """List files tracked at the Overleaf repo's HEAD (post-push)."""
        out = repo.git.ls_tree("-r", "--name-only", "HEAD")
        return set(out.split("\n")) - {""}

    # First, create a temporary repo to represent the Overleaf project
    pid = str(uuid.uuid4())
    ol_repo = _make_temp_overleaf_project(pid)
    ol_repo.git.config(["receive.denyCurrentBranch", "ignore"])
    subprocess.run(["calkit", "init"], check=True)
    repo = git.Repo()
    tmp_remote = (
        Path(tempfile.gettempdir()) / "overleaf-sync-remotes" / pid
    ).as_posix()
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
    # Test that we can properly resolve a merge conflict
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
    # Test that --no-commit pulls changes from Overleaf but does not create a
    # commit in the main repo, leaving the pulled changes staged instead
    with open(os.path.join(ol_repo.working_dir, "main.tex"), "a") as f:
        f.write("\nA line that should be pulled but not committed")
    ol_repo.git.commit(["main.tex", "-m", "Update on Overleaf"])
    head_before = repo.head.commit.hexsha
    subprocess.run(["calkit", "overleaf", "sync", "--no-commit"], check=True)
    # No new commit should have been created
    assert repo.head.commit.hexsha == head_before
    # The change should be present locally and staged
    with open("ol-project/main.tex") as f:
        assert "A line that should be pulled but not committed" in f.read()
    assert repo.git.diff(["--staged", "ol-project/main.tex"])
    assert not repo.git.diff(["ol-project/main.tex"])
    # Commit the staged changes so the working tree is clean for the next step
    repo.git.commit(["-m", "Commit pulled Overleaf changes"])
    # Test that if we add a file on Overleaf, it syncs back to the main repo
    with open(os.path.join(ol_repo.working_dir, "ol-new.txt"), "w") as f:
        f.write("Created on Overleaf")
    ol_repo.git.add("ol-new.txt")
    ol_repo.git.commit(["-m", "Update on Overleaf"])
    subprocess.run(["calkit", "overleaf", "sync"], check=True)
    assert "ol-project/ol-new.txt" in ls_files(repo)
    # Test that if we add a file locally, it makes it to Overleaf
    os.makedirs(os.path.join(repo.working_dir, "ol-project", "figs"))
    with open(
        os.path.join(repo.working_dir, "ol-project", "figs", "fig1.txt"), "w"
    ) as f:
        f.write("Fig1 created in main repo")
    repo.git.add("ol-project/figs")
    repo.git.commit(["-m", "Add figure"])
    assert "ol-project/figs/fig1.txt" in ls_files(repo)
    subprocess.run(["calkit", "overleaf", "sync", "--verbose"], check=True)
    # Note: We have to look at the git show in the Overleaf repo to verify the
    # file made it there, since it is a dummy remote and doesn't actually
    # update the file system
    ol_repo_git_show = ol_repo.git.show()
    print("Git show in OL repo:\n", ol_repo_git_show)
    assert "diff --git a/figs/fig1.txt b/figs/fig1.txt" in ol_repo_git_show
    assert "Fig1 created in main repo" in ol_repo_git_show
    assert "new file mode 100644" in ol_repo_git_show
    # Test that a file ignored in the main repo (and not otherwise stored) is
    # treated as ignored and does not make it to Overleaf
    with open(os.path.join(repo.working_dir, ".gitignore"), "a") as f:
        f.write("\nol-project/figs/ignored-in-main.txt\n*.pdf\n*.aux\n*.log")
    repo.git.add(".gitignore")
    repo.git.commit(["-m", "Update gitignore"])
    with open(
        os.path.join(
            repo.working_dir, "ol-project", "figs", "ignored-in-main.txt"
        ),
        "w",
    ) as f:
        f.write("This is ignored in main")
    assert repo.ignored("ol-project/figs/ignored-in-main.txt")
    subprocess.run(["calkit", "overleaf", "sync"], check=True)
    ol_repo_git_show = ol_repo.git.show()
    print("Git show in OL repo:\n", ol_repo_git_show)
    assert "figs/ignored-in-main.txt" not in get_overleaf_tree(ol_repo)
    # Test that LaTeX aux build files and main PDFs don't make it to Overleaf
    for fname in ["main.pdf", "main.log", "main.aux"]:
        with open(
            os.path.join(repo.working_dir, "ol-project", fname), "w"
        ) as f:
            f.write("Ignored locally and shouldn't make it to Overleaf")
    subprocess.run(["calkit", "overleaf", "sync"], check=True)
    ol_repo_git_show = ol_repo.git.show()
    print("Git show in OL repo:\n", ol_repo_git_show)
    assert "main.pdf" not in ol_repo_git_show
    assert "main.log" not in ol_repo_git_show
    assert "main.aux" not in ol_repo_git_show
    # Test that an untracked LaTeX build artifact (e.g., a .auxlock file) in
    # the synced folder is auto-ignored rather than committed during a sync,
    # and is not pushed to Overleaf
    auxlock_rel = "ol-project/out/main.auxlock"
    os.makedirs(os.path.join(repo.working_dir, "ol-project", "out"))
    with open(os.path.join(repo.working_dir, auxlock_rel), "w") as f:
        f.write("\\def \\tikzexternallocked {0}")
    subprocess.run(["calkit", "overleaf", "sync"], check=True)
    assert auxlock_rel not in ls_files(repo)
    with open(os.path.join(repo.working_dir, ".gitignore")) as f:
        assert auxlock_rel in f.read()
    assert not repo.git.status("--porcelain", "ol-project/out")
    assert "main.auxlock" not in ol_repo.git.show()
    # Test that if we add a file locally, sync to Overleaf, then delete from
    # local, it is deleted on Overleaf as well
    with open(
        os.path.join(repo.working_dir, "ol-project", "figs", "fig2.txt"), "w"
    ) as f:
        f.write("Fig2 created in main repo")
    repo.git.add("ol-project/figs")
    repo.git.commit(["-m", "Add figure 2"])
    assert "ol-project/figs/fig2.txt" in ls_files(repo)
    subprocess.run(["calkit", "overleaf", "sync", "--verbose"], check=True)
    ol_repo_git_show = ol_repo.git.show()
    print("Git show in OL repo:\n", ol_repo_git_show)
    assert "diff --git a/figs/fig2.txt b/figs/fig2.txt" in ol_repo_git_show
    assert "Fig2 created in main repo" in ol_repo_git_show
    assert "new file mode 100644" in ol_repo_git_show
    repo.git.rm("ol-project/figs/fig2.txt")
    repo.git.commit(["-m", "Delete figure 2"])
    subprocess.run(["calkit", "overleaf", "sync", "--verbose"], check=True)
    assert "ol-project/figs/fig2.txt" not in ls_files(repo)
    ol_repo_git_show = ol_repo.git.show()
    print("Git show in OL repo after deletion:\n", ol_repo_git_show)
    assert "deleted file mode 100644" in ol_repo_git_show
    assert "--- a/figs/fig2.txt" in ol_repo_git_show
    # Make sure that if we add that file back on Overleaf, it comes back to the
    # main repo
    os.makedirs(os.path.join(ol_repo.working_dir, "figs"), exist_ok=True)
    with open(
        os.path.join(ol_repo.working_dir, "figs", "fig2.txt"),
        "w",
    ) as f:
        f.write("Fig2 created again on Overleaf")
    ol_repo.git.add("figs/fig2.txt")
    ol_repo.git.commit(["-m", "Add figure 2 again on Overleaf"])
    subprocess.run(["calkit", "overleaf", "sync", "--verbose"], check=True)
    print("Overleaf Git show after adding fig2 back:", ol_repo.git.show())
    assert "ol-project/figs/fig2.txt" in ls_files(repo)
    # Test that if a file is deleted from Git but added to DVC, it is not
    # deleted from Overleaf (the file still logically exists in the DVC repo)
    with open(
        os.path.join(repo.working_dir, "ol-project", "figs", "fig3.txt"), "w"
    ) as f:
        f.write("Fig3 created in main repo")
    repo.git.add("ol-project/figs/fig3.txt")
    repo.git.commit(["-m", "Add figure 3"])
    assert "ol-project/figs/fig3.txt" in ls_files(repo)
    subprocess.run(["calkit", "overleaf", "sync", "--verbose"], check=True)
    ol_repo_git_show = ol_repo.git.show()
    assert "diff --git a/figs/fig3.txt b/figs/fig3.txt" in ol_repo_git_show
    # Now move from Git to DVC: first remove from Git index (keeping file on
    # disk), then add to DVC so it gets moved to DVC cache
    repo.git.rm(["--cached", "ol-project/figs/fig3.txt"])
    subprocess.run(
        ["dvc", "add", "ol-project/figs/fig3.txt"],
        check=True,
        cwd=repo.working_dir,
    )
    # Commit the DVC pointer file (fig3.txt is now tracked by DVC, not Git)
    repo.git.add("ol-project/figs/fig3.txt.dvc", "ol-project/figs/.gitignore")
    repo.git.commit(["-m", "Move figure 3 from git to DVC"])
    assert "ol-project/figs/fig3.txt" not in ls_files(repo)
    # Also remove the local file to simulate the file not being pulled from
    # DVC (i.e., only the DVC pointer exists locally, not the actual file)
    fig3_path = os.path.join(
        repo.working_dir, "ol-project", "figs", "fig3.txt"
    )
    if os.path.exists(fig3_path):
        os.remove(fig3_path)
    assert not os.path.exists(fig3_path)
    subprocess.run(["calkit", "overleaf", "sync", "--verbose"], check=True)
    ol_repo_git_show = ol_repo.git.show()
    print("Git show in OL repo after moving fig3 to DVC:\n", ol_repo_git_show)
    # The file should not have been deleted from Overleaf
    assert "deleted file mode" not in ol_repo_git_show
    assert "--- a/figs/fig3.txt" not in ol_repo_git_show


def test_overleaf_sync_paths_storage(tmp_dir):
    # Regression test for issue #922: only "stored" files (tracked by Git or
    # cached by DVC) are synced with Overleaf. DVC pipeline outputs with no
    # storage (storage: null) are treated as ignored -- never pushed, pulled,
    # or deleted from Overleaf -- whether or not they exist on disk.
    main_dir = os.path.join(str(tmp_dir), "main")
    ol_dir = os.path.join(str(tmp_dir), "ol")
    os.makedirs(os.path.join(main_dir, "pub", "aux"))
    os.makedirs(ol_dir)
    main_repo = git.Repo.init(main_dir)
    ol_repo = git.Repo.init(ol_dir)
    # Stored (git-tracked) authored files
    with open(os.path.join(main_dir, "pub", "main.tex"), "w") as f:
        f.write("Hello")
    with open(os.path.join(main_dir, "pub", "references.bib"), "w") as f:
        f.write("@article{a}")
    # A storage: null pipeline output that exists on disk (a LaTeX aux PDF):
    # must not be pushed to Overleaf
    with open(
        os.path.join(main_dir, "pub", "aux", "main-figure0.pdf"), "w"
    ) as f:
        f.write("build artifact")
    # Declare the pipeline outputs as uncached (storage: null) in dvc.yaml.
    # shared-pkg.tex is such an output that does not exist on disk locally but
    # does exist on Overleaf -- it must not be deleted from Overleaf.
    dvc_yaml = {
        "stages": {
            "build": {
                "cmd": "echo build",
                "outs": [
                    {"pub/aux": {"cache": False}},
                    {"pub/shared-pkg.tex": {"cache": False}},
                ],
            }
        }
    }
    with open(os.path.join(main_dir, "dvc.yaml"), "w") as f:
        calkit.ryaml.dump(dvc_yaml, f)
    main_repo.git.add("pub/main.tex", "pub/references.bib", "dvc.yaml")
    main_repo.git.commit(["-m", "Init project"])
    # Overleaf has the stored files plus an Overleaf-only storage: null output
    # (shared-pkg.tex) and a genuinely-removed file (deleted.tex)
    for name, content in [
        ("main.tex", "Hello"),
        ("references.bib", "@article{a, note={edited on Overleaf}}"),
        ("shared-pkg.tex", "\\usepackage{amsmath}"),
        ("deleted.tex", "removed from the project"),
    ]:
        with open(os.path.join(ol_dir, name), "w") as f:
            f.write(content)
    ol_repo.git.add(".")
    ol_repo.git.commit(["-m", "Overleaf state"])
    paths = calkit.overleaf.OverleafSyncPaths(
        main_repo=main_repo,
        overleaf_repo=ol_repo,
        path_in_project="pub",
        sync_info_for_path={},
        last_sync_commit=ol_repo.head.commit.hexsha,
    )
    # Only git-tracked authored files are "stored"
    assert paths.stored_files == {"main.tex", "references.bib"}
    # Both pipeline outputs are recognized regardless of on-disk presence
    assert "shared-pkg.tex" in paths.pipeline_output_paths
    assert "aux" in paths.pipeline_output_paths
    # The storage: null aux PDF on disk is not pushed to Overleaf
    assert set(paths.files_to_copy_to_overleaf) == {
        "main.tex",
        "references.bib",
    }
    # The Overleaf-only storage: null output is not pulled into the project
    assert "shared-pkg.tex" not in paths.files_to_copy_from_overleaf
    assert set(paths.files_to_copy_from_overleaf) == {
        "main.tex",
        "references.bib",
        "deleted.tex",
    }
    # storage: null outputs (whether on disk or only on Overleaf) and stored
    # files are preserved; only the genuinely-removed file is stale
    assert paths.stale_files_in_overleaf == ["deleted.tex"]


def test_extract_title_from_tex(tmp_dir):
    # Test that we can extract a title from a simple LaTeX file
    tex = r"""
    \documentclass{article}
    \title{My Cool Paper}
    \begin{document}
    Hello world!
    \end{document}
    """
    with open("test.tex", "w") as f:
        f.write(tex)
    title = _extract_title_from_tex("test.tex")
    assert title == "My Cool Paper"


def test_overleaf_sync_trailing_slash_or_space(tmp_dir):
    pid = str(uuid.uuid4())
    ol_repo = _make_temp_overleaf_project(pid)
    ol_repo.git.config(["receive.denyCurrentBranch", "ignore"])
    subprocess.run(["calkit", "init"], check=True)
    repo = git.Repo()
    tmp_remote = (
        Path(tempfile.gettempdir()) / "overleaf-sync-remotes" / pid
    ).as_posix()
    os.makedirs(tmp_remote, exist_ok=True)
    remote_repo = git.Repo.init(path=tmp_remote, bare=True)
    remote_repo.git.config(["receive.denyCurrentBranch", "ignore"])
    repo.git.config(["push.autoSetupRemote", "true"])
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
            "pubs/applied-ocean-research",
            "--title",
            "Test Pub",
        ],
        check=True,
    )
    # Try syncing with a trailing slash
    res = subprocess.run(
        ["calkit", "overleaf", "sync", "pubs/applied-ocean-research/"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Trailing slash sync failed: {res.stderr}"
    # Try syncing with a trailing space
    res2 = subprocess.run(
        ["calkit", "overleaf", "sync", "pubs/applied-ocean-research "],
        capture_output=True,
        text=True,
    )
    assert res2.returncode == 0, f"Trailing space sync failed: {res2.stderr}"


def test_clone_disables_credential_store(tmp_dir):
    # Set up a source repo to act as the Overleaf remote
    src = os.path.join(str(tmp_dir), "src")
    src_repo = git.Repo.init(path=src)
    with open(os.path.join(src, "main.tex"), "w") as f:
        f.write("hello")
    src_repo.git.add("main.tex")
    src_repo.git.commit(["-m", "Initial commit"])
    # A fresh clone should reset the credential helper for that repo so only
    # the token embedded in the remote URL is used, never a stale one from the
    # OS credential store
    dest = os.path.join(str(tmp_dir), "dest")
    repo = calkit.overleaf.clone(src, dest)
    assert repo.git.config(["--local", "--get", "credential.helper"]) == ""
    assert (
        repo.git.config(["--local", "--get", "credential.interactive"])
        == "false"
    )
    # Opening an already-cloned project should refresh the remote URL so an
    # updated token takes effect, and keep the credential store disabled
    new_url = src + "?token=new"
    repo2 = calkit.overleaf.clone_or_open(new_url, dest)
    assert repo2.git.remote(["get-url", "origin"]) == new_url
    assert repo2.git.config(["--local", "--get", "credential.helper"]) == ""
    # A destination that does not yet exist should be cloned
    dest2 = os.path.join(str(tmp_dir), "dest2")
    calkit.overleaf.clone_or_open(src, dest2)
    assert os.path.isdir(os.path.join(dest2, ".git"))
