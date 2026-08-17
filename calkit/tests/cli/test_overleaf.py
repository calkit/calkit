"""Tests for the Overleaf CLI commands."""

import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import git
import pytest
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
    subprocess.run(["calkit", "overleaf", "sync", "--allow-stale"], check=True)
    # Test that we can properly resolve a merge conflict
    with open(os.path.join(ol_repo.working_dir, "main.tex"), "a") as f:
        f.write("\nHere's another line from Overleaf")
    ol_repo.git.commit(["main.tex", "-m", "Update on Overleaf"])
    with open("ol-project/main.tex", "a") as f:
        f.write("\nHere's another line from main project")
    repo.git.commit(["ol-project/main.tex", "-m", "Local edit"])
    res = subprocess.run(
        ["calkit", "overleaf", "sync", "--allow-stale"], capture_output=True
    )
    assert res.returncode != 0
    with open("ol-project/main.tex") as f:
        txt = f.read()
    assert ">>>>>>>" in txt
    # Now let's resolve the commit without actually editing the file
    subprocess.run(
        ["calkit", "overleaf", "sync", "--allow-stale", "--resolve"],
        check=True,
    )
    # Now make another change on Overleaf but allow the sync to succeed
    with open(os.path.join(ol_repo.working_dir, "main.tex"), "a") as f:
        f.write("\nHere's another line from Overleaf")
    ol_repo.git.commit(["main.tex", "-m", "Update on Overleaf"])
    subprocess.run(["calkit", "overleaf", "sync", "--allow-stale"], check=True)
    # Test that --no-commit pulls changes from Overleaf but does not create a
    # commit in the main repo, leaving the pulled changes staged instead
    with open(os.path.join(ol_repo.working_dir, "main.tex"), "a") as f:
        f.write("\nA line that should be pulled but not committed")
    ol_repo.git.commit(["main.tex", "-m", "Update on Overleaf"])
    head_before = repo.head.commit.hexsha
    subprocess.run(
        ["calkit", "overleaf", "sync", "--allow-stale", "--no-commit"],
        check=True,
    )
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
    subprocess.run(["calkit", "overleaf", "sync", "--allow-stale"], check=True)
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
    subprocess.run(
        ["calkit", "overleaf", "sync", "--allow-stale", "--verbose"],
        check=True,
    )
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
    subprocess.run(["calkit", "overleaf", "sync", "--allow-stale"], check=True)
    ol_repo_git_show = ol_repo.git.show()
    print("Git show in OL repo:\n", ol_repo_git_show)
    assert "figs/ignored-in-main.txt" not in get_overleaf_tree(ol_repo)
    # Test that LaTeX aux build files and main PDFs don't make it to Overleaf
    for fname in ["main.pdf", "main.log", "main.aux"]:
        with open(
            os.path.join(repo.working_dir, "ol-project", fname), "w"
        ) as f:
            f.write("Ignored locally and shouldn't make it to Overleaf")
    subprocess.run(["calkit", "overleaf", "sync", "--allow-stale"], check=True)
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
    subprocess.run(["calkit", "overleaf", "sync", "--allow-stale"], check=True)
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
    subprocess.run(
        ["calkit", "overleaf", "sync", "--allow-stale", "--verbose"],
        check=True,
    )
    ol_repo_git_show = ol_repo.git.show()
    print("Git show in OL repo:\n", ol_repo_git_show)
    assert "diff --git a/figs/fig2.txt b/figs/fig2.txt" in ol_repo_git_show
    assert "Fig2 created in main repo" in ol_repo_git_show
    assert "new file mode 100644" in ol_repo_git_show
    repo.git.rm("ol-project/figs/fig2.txt")
    repo.git.commit(["-m", "Delete figure 2"])
    subprocess.run(
        ["calkit", "overleaf", "sync", "--allow-stale", "--verbose"],
        check=True,
    )
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
    subprocess.run(
        ["calkit", "overleaf", "sync", "--allow-stale", "--verbose"],
        check=True,
    )
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
    subprocess.run(
        ["calkit", "overleaf", "sync", "--allow-stale", "--verbose"],
        check=True,
    )
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
    subprocess.run(
        ["calkit", "overleaf", "sync", "--allow-stale", "--verbose"],
        check=True,
    )
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
        [
            "calkit",
            "overleaf",
            "sync",
            "--allow-stale",
            "pubs/applied-ocean-research/",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Trailing slash sync failed: {res.stderr}"
    # Try syncing with a trailing space
    res2 = subprocess.run(
        [
            "calkit",
            "overleaf",
            "sync",
            "--allow-stale",
            "pubs/applied-ocean-research ",
        ],
        capture_output=True,
        text=True,
    )
    assert res2.returncode == 0, f"Trailing space sync failed: {res2.stderr}"


def test_get_repo_disables_credential_store(tmp_dir):
    # Set up a repo to act as the Overleaf remote (in the test env the remote
    # URL is a local directory)
    pid = str(uuid.uuid4())
    _make_temp_overleaf_project(pid)
    dest = calkit.overleaf.get_project_dir(pid)
    # A fresh clone should reset the credential helper for that repo so only
    # the token in its remote URL is used, never a stale one from the OS
    # credential store
    repo = calkit.overleaf.clone(pid, "sometoken")
    assert os.path.isdir(os.path.join(dest, ".git"))
    assert repo.git.config(["--local", "--get", "credential.helper"]) == ""
    assert (
        repo.git.config(["--local", "--get", "credential.interactive"])
        == "false"
    )
    # Opening an already-cloned project should refresh the remote URL so an
    # updated token takes effect, and keep the credential store disabled
    repo2 = calkit.overleaf.get_repo(pid, "newtoken")
    assert repo2.git.remote(
        ["get-url", "origin"]
    ) == calkit.overleaf.get_git_remote_url(pid, "newtoken")
    assert repo2.git.config(["--local", "--get", "credential.helper"]) == ""
    # A project that has not yet been cloned should be cloned
    pid2 = str(uuid.uuid4())
    _make_temp_overleaf_project(pid2)
    calkit.overleaf.get_repo(pid2, "sometoken")
    assert os.path.isdir(
        os.path.join(calkit.overleaf.get_project_dir(pid2), ".git")
    )


def test_overleaf_sync_paths_stage_outputs(tmp_dir):
    # Regression test for issue #979: a map-paths stage copies shared files
    # (a bibliography, a class file) into each publication's folder, so those
    # copies are gitignored pipeline outputs. They still have to reach
    # Overleaf, or the document can't compile there -- and edits made to them
    # on Overleaf must not be pulled back, since the next run overwrites them.
    # The same push-only rule covers stage outputs that are stored in Git,
    # such as a json-to-latex stage's .tex.
    main_dir = os.path.join(str(tmp_dir), "main")
    ol_dir = os.path.join(str(tmp_dir), "ol")
    os.makedirs(os.path.join(main_dir, "pubs", "shared"))
    os.makedirs(os.path.join(main_dir, "pubs", "mypub1", "figures"))
    os.makedirs(ol_dir)
    main_repo = git.Repo.init(main_dir)
    ol_repo = git.Repo.init(ol_dir)

    def write(*parts, content="x"):
        with open(os.path.join(main_dir, *parts), "w") as f:
            f.write(content)

    # Authored files: the document, and the shared files it needs
    write("pubs", "mypub1", "main.tex", content="Hello")
    write("pubs", "shared", "references.bib", content="@article{a}")
    write("pubs", "shared", "template.cls", content="\\ProvidesClass{t}")
    # The map-paths copies, as they exist after a run
    write("pubs", "mypub1", "references.bib", content="@article{a}")
    write("pubs", "mypub1", "template.cls", content="\\ProvidesClass{t}")
    # A git-stored stage output (json-to-latex) and an uncached build artifact
    write("pubs", "mypub1", "results.tex", content="\\newcommand{\\r}{1}")
    write("pubs", "mypub1", "figures", "fig.pdf", content="build artifact")
    # The copies are gitignored, exactly as Calkit writes them
    with open(os.path.join(main_dir, ".gitignore"), "w") as f:
        f.write("/pubs/mypub1/references.bib\n/pubs/mypub1/template.cls\n")
    ck_info = {
        "pipeline": {
            "stages": {
                "shared-to-mypub1": {
                    "kind": "map-paths",
                    "paths": [
                        {
                            "kind": "file-to-dir",
                            "src": "pubs/shared/references.bib",
                            "dest": "pubs/mypub1",
                        },
                        {
                            "kind": "file-to-file",
                            "src": "pubs/shared/template.cls",
                            "dest": "pubs/mypub1/template.cls",
                        },
                    ],
                }
            }
        }
    }
    with open(os.path.join(main_dir, "calkit.yaml"), "w") as f:
        calkit.ryaml.dump(ck_info, f)
    dvc_yaml = {
        "stages": {
            "shared-to-mypub1": {
                "cmd": "calkit map-paths",
                "outs": [
                    {"pubs/mypub1/references.bib": {"cache": False}},
                    {"pubs/mypub1/template.cls": {"cache": False}},
                ],
            },
            "results-to-tex": {
                "cmd": "calkit latex from-json",
                "outs": [{"pubs/mypub1/results.tex": {"cache": False}}],
            },
            "build": {
                "cmd": "echo build",
                "outs": [{"pubs/mypub1/figures": {"cache": False}}],
            },
        }
    }
    with open(os.path.join(main_dir, "dvc.yaml"), "w") as f:
        calkit.ryaml.dump(dvc_yaml, f)
    main_repo.git.add(
        "pubs/mypub1/main.tex",
        "pubs/mypub1/results.tex",
        "pubs/shared/references.bib",
        "pubs/shared/template.cls",
        ".gitignore",
        "calkit.yaml",
        "dvc.yaml",
    )
    main_repo.git.commit(["-m", "Init project"])
    for name, content in [
        ("main.tex", "Hello"),
        ("references.bib", "@article{a, note={edited on Overleaf}}"),
        ("results.tex", "\\newcommand{\\r}{2}"),
    ]:
        with open(os.path.join(ol_dir, name), "w") as f:
            f.write(content)
    ol_repo.git.add(".")
    ol_repo.git.commit(["-m", "Overleaf state"])
    paths = calkit.overleaf.OverleafSyncPaths(
        main_repo=main_repo,
        overleaf_repo=ol_repo,
        path_in_project="pubs/mypub1",
        sync_info_for_path={},
        last_sync_commit=ol_repo.head.commit.hexsha,
    )
    # The map-paths destinations are found and resolved per mapping kind:
    # file-to-dir keeps the source's filename inside the destination
    assert paths.map_paths_outputs == {"references.bib", "template.cls"}
    assert paths.mapped_files == {"references.bib", "template.cls"}
    # The gitignored copies are still not "stored"
    assert "references.bib" not in paths.stored_files
    # ...but they are pushed, so Overleaf can compile the document. The
    # uncached build artifact still is not.
    assert set(paths.files_to_copy_to_overleaf) == {
        "main.tex",
        "references.bib",
        "results.tex",
        "template.cls",
    }
    # Nothing the pipeline produces comes back, whether it's gitignored
    # (references.bib) or stored in Git (results.tex)
    assert set(paths.files_to_copy_from_overleaf) == {"main.tex"}
    # ...and none of it is deleted from Overleaf either
    assert paths.stale_files_in_overleaf == []


def test_overleaf_sync_all_overleaf_files_are_pipeline_outputs(tmp_dir):
    # When every file on Overleaf is a pipeline output there is nothing to
    # pull, which leaves no paths to pass to git format-patch -- and an empty
    # pathspec after `--` means *everything* to Git, not nothing. Without a
    # guard, the sync pulls in exactly the edits it just decided to skip.
    main_dir = os.path.join(str(tmp_dir), "main")
    ol_dir = os.path.join(str(tmp_dir), "ol")
    ol_remote_dir = os.path.join(str(tmp_dir), "ol-remote")
    os.makedirs(os.path.join(main_dir, "pubs", "mypub1"))
    os.makedirs(ol_dir)
    main_repo = git.Repo.init(main_dir)
    ol_remote = git.Repo.init(path=ol_remote_dir, bare=True)
    ol_repo = git.Repo.init(ol_dir)
    generated = "\\newcommand{\\r}{1}"
    results_fpath = os.path.join(main_dir, "pubs", "mypub1", "results.tex")
    with open(results_fpath, "w") as f:
        f.write(generated)
    ck_info = {"pipeline": {"stages": {}}}
    with open(os.path.join(main_dir, "calkit.yaml"), "w") as f:
        calkit.ryaml.dump(ck_info, f)
    dvc_yaml = {
        "stages": {
            "results-to-tex": {
                "cmd": "calkit latex from-json",
                "outs": [{"pubs/mypub1/results.tex": {"cache": False}}],
            }
        }
    }
    with open(os.path.join(main_dir, "dvc.yaml"), "w") as f:
        calkit.ryaml.dump(dvc_yaml, f)
    main_repo.git.add("pubs/mypub1/results.tex", "calkit.yaml", "dvc.yaml")
    main_repo.git.commit(["-m", "Init project"])
    # Overleaf holds only that generated file, and it was edited there
    with open(os.path.join(ol_dir, "results.tex"), "w") as f:
        f.write(generated)
    ol_repo.git.add(".")
    ol_repo.git.commit(["-m", "Overleaf state"])
    last_sync_commit = ol_repo.head.commit.hexsha
    with open(os.path.join(ol_dir, "results.tex"), "w") as f:
        f.write("\\newcommand{\\r}{999}")
    ol_repo.git.commit(["results.tex", "-m", "Update on Overleaf"])
    ol_repo.git.remote(["add", "origin", ol_remote_dir])
    ol_repo.git.push(["--set-upstream", "origin", ol_repo.active_branch.name])
    paths = calkit.overleaf.OverleafSyncPaths(
        main_repo=main_repo,
        overleaf_repo=ol_repo,
        path_in_project="pubs/mypub1",
        sync_info_for_path={},
        last_sync_commit=last_sync_commit,
    )
    assert paths.paths_to_use_for_git_patch == []
    res = calkit.overleaf.sync(
        main_repo=main_repo,
        overleaf_repo=ol_repo,
        path_in_project="pubs/mypub1",
        sync_info_for_path={},
        last_sync_commit=last_sync_commit,
        print_info=lambda *a, **k: None,
    )
    assert res["patch"] is None
    # The Overleaf edit stayed on Overleaf, and our version was pushed back
    with open(results_fpath) as f:
        assert f.read() == generated
    with open(os.path.join(ol_dir, "results.tex")) as f:
        assert f.read() == generated
    assert ol_remote.head.commit.hexsha == ol_repo.head.commit.hexsha


def test_overleaf_sync_map_paths_edits_go_back_to_source(tmp_dir):
    # A map-paths copy is generated, so an edit made to it on Overleaf can't
    # stay there -- the next run overwrites it. It does have somewhere to go
    # though: the file the stage copies from. That applies whether the
    # mapping names a file or a directory, but not when the source is itself
    # produced by another stage, since the edit would be overwritten just the
    # same.
    main_dir = os.path.join(str(tmp_dir), "main")
    ol_dir = os.path.join(str(tmp_dir), "ol")
    ol_remote_dir = os.path.join(str(tmp_dir), "ol-remote")
    os.makedirs(os.path.join(main_dir, "pubs", "shared", "sections"))
    os.makedirs(os.path.join(main_dir, "pubs", "mypub1", "sections"))
    os.makedirs(os.path.join(main_dir, "generated"))
    os.makedirs(ol_dir)
    main_repo = git.Repo.init(main_dir)
    ol_remote = git.Repo.init(path=ol_remote_dir, bare=True)
    ol_repo = git.Repo.init(ol_dir)

    def write(*parts, content="x"):
        fpath = os.path.join(main_dir, *parts)
        with open(fpath, "w") as f:
            f.write(content)

    # Authored files and the copies a run puts in the document's folder
    write("pubs", "mypub1", "main.tex", content="Hello")
    write("pubs", "shared", "references.bib", content="@article{a}")
    write("pubs", "mypub1", "references.bib", content="@article{a}")
    write("pubs", "shared", "sections", "intro.tex", content="Intro")
    write("pubs", "mypub1", "sections", "intro.tex", content="Intro")
    # A map-paths source that is itself generated by another stage
    write("generated", "numbers.tex", content="\\newcommand{\\n}{1}")
    write("pubs", "mypub1", "numbers.tex", content="\\newcommand{\\n}{1}")
    # A source edited locally without a run since, so its copy is behind it
    write("pubs", "shared", "appendix.tex", content="Appendix, edited here")
    write("pubs", "mypub1", "appendix.tex", content="Appendix")
    with open(os.path.join(main_dir, ".gitignore"), "w") as f:
        f.write(
            "/pubs/mypub1/references.bib\n"
            "/pubs/mypub1/sections/\n"
            "/pubs/mypub1/numbers.tex\n"
            "/pubs/mypub1/appendix.tex\n"
            "/generated/\n"
        )
    ck_info = {
        "pipeline": {
            "stages": {
                "shared-to-mypub1": {
                    "kind": "map-paths",
                    "paths": [
                        {
                            "kind": "file-to-dir",
                            "src": "pubs/shared/references.bib",
                            "dest": "pubs/mypub1",
                        },
                        {
                            "kind": "dir-to-dir-merge",
                            "src": "pubs/shared/sections",
                            "dest": "pubs/mypub1/sections",
                        },
                        {
                            "kind": "file-to-file",
                            "src": "generated/numbers.tex",
                            "dest": "pubs/mypub1/numbers.tex",
                        },
                        {
                            "kind": "file-to-file",
                            "src": "pubs/shared/appendix.tex",
                            "dest": "pubs/mypub1/appendix.tex",
                        },
                    ],
                }
            }
        }
    }
    with open(os.path.join(main_dir, "calkit.yaml"), "w") as f:
        calkit.ryaml.dump(ck_info, f)
    dvc_yaml = {
        "stages": {
            "shared-to-mypub1": {
                "cmd": "calkit map-paths",
                "outs": [
                    {"pubs/mypub1/references.bib": {"cache": False}},
                    {"pubs/mypub1/sections": {"cache": False}},
                    {"pubs/mypub1/numbers.tex": {"cache": False}},
                    {"pubs/mypub1/appendix.tex": {"cache": False}},
                ],
            },
            "make-numbers": {
                "cmd": "python make_numbers.py",
                "outs": [{"generated/numbers.tex": {"cache": False}}],
            },
        }
    }
    with open(os.path.join(main_dir, "dvc.yaml"), "w") as f:
        calkit.ryaml.dump(dvc_yaml, f)
    main_repo.git.add(
        "pubs/mypub1/main.tex",
        "pubs/shared/references.bib",
        "pubs/shared/sections/intro.tex",
        "pubs/shared/appendix.tex",
        ".gitignore",
        "calkit.yaml",
        "dvc.yaml",
    )
    main_repo.git.commit(["-m", "Init project"])
    # Overleaf starts out matching what the last run produced
    os.makedirs(os.path.join(ol_dir, "sections"))
    for parts, content in [
        (("main.tex",), "Hello"),
        (("references.bib",), "@article{a}"),
        (("sections", "intro.tex"), "Intro"),
        (("numbers.tex",), "\\newcommand{\\n}{1}"),
        (("appendix.tex",), "Appendix"),
    ]:
        with open(os.path.join(ol_dir, *parts), "w") as f:
            f.write(content)
    ol_repo.git.add(".")
    ol_repo.git.commit(["-m", "Overleaf state"])
    last_sync_commit = ol_repo.head.commit.hexsha
    # A collaborator edits the bibliography, a mapped section, the copy whose
    # source is generated, and the document itself
    edited_bib = "@article{a, note={added on Overleaf}}"
    edited_intro = "Intro, with a sentence added on Overleaf"
    for parts, content in [
        (("references.bib",), edited_bib),
        (("sections", "intro.tex"), edited_intro),
        (("numbers.tex",), "\\newcommand{\\n}{999}"),
        (("appendix.tex",), "Appendix, edited on Overleaf"),
        (("main.tex",), "Hello, and more"),
    ]:
        with open(os.path.join(ol_dir, *parts), "w") as f:
            f.write(content)
    ol_repo.git.commit(["-a", "-m", "Update on Overleaf"])
    ol_repo.git.remote(["add", "origin", ol_remote_dir])
    ol_repo.git.push(["--set-upstream", "origin", ol_repo.active_branch.name])
    paths = calkit.overleaf.OverleafSyncPaths(
        main_repo=main_repo,
        overleaf_repo=ol_repo,
        path_in_project="pubs/mypub1",
        sync_info_for_path={},
        last_sync_commit=last_sync_commit,
    )
    # Only the copies whose source is authored can be written back to
    assert paths.map_paths_sources == {
        "references.bib": "pubs/shared/references.bib",
        "sections/intro.tex": "pubs/shared/sections/intro.tex",
        "appendix.tex": "pubs/shared/appendix.tex",
    }
    messages = []
    res = calkit.overleaf.sync(
        main_repo=main_repo,
        overleaf_repo=ol_repo,
        path_in_project="pubs/mypub1",
        sync_info_for_path={},
        last_sync_commit=last_sync_commit,
        print_info=lambda *a, **k: messages.append(" ".join(map(str, a))),
    )
    assert res["map_paths_propagated"] == {
        "references.bib": "pubs/shared/references.bib",
        "sections/intro.tex": "pubs/shared/sections/intro.tex",
    }
    # The edits landed in the files the stage copies from...
    with open(os.path.join(main_dir, "pubs", "shared", "references.bib")) as f:
        assert f.read() == edited_bib
    with open(
        os.path.join(main_dir, "pubs", "shared", "sections", "intro.tex")
    ) as f:
        assert f.read() == edited_intro
    # ...and in the copies, so this sync doesn't push the old version back
    with open(os.path.join(main_dir, "pubs", "mypub1", "references.bib")) as f:
        assert f.read() == edited_bib
    with open(os.path.join(ol_dir, "references.bib")) as f:
        assert f.read() == edited_bib
    # The sources are committed, since they live outside the synced folder
    assert res["committed_project"]
    committed = main_repo.git.show(["--name-only", "--format=", "HEAD"])
    assert "pubs/shared/references.bib" in committed
    assert "pubs/shared/sections/intro.tex" in committed
    assert not main_repo.git.diff(["HEAD", "--", "pubs/shared"])
    # The copy built from a generated file is reported instead, and neither
    # it nor its source is touched
    assert res["pipeline_outputs_changed_on_overleaf"] == [
        "appendix.tex",
        "numbers.tex",
        "references.bib",
        "sections/intro.tex",
    ]
    with open(os.path.join(main_dir, "generated", "numbers.tex")) as f:
        assert f.read() == "\\newcommand{\\n}{1}"
    # A source with edits of its own is left alone rather than overwritten,
    # since the two versions need merging by hand
    assert res["map_paths_diverged"] == {
        "appendix.tex": "pubs/shared/appendix.tex"
    }
    with open(os.path.join(main_dir, "pubs", "shared", "appendix.tex")) as f:
        assert f.read() == "Appendix, edited here"
    # Both sides are left alone, so Overleaf keeps its version rather than
    # having it overwritten by the copy we declined to update
    assert "appendix.tex" not in res["files_to_copy_to_overleaf"]
    with open(os.path.join(ol_dir, "appendix.tex")) as f:
        assert f.read() == "Appendix, edited on Overleaf"
    warned = [m for m in messages if m.startswith("Warning:")]
    assert len(warned) == 2
    assert "numbers.tex" in warned[0]
    assert "references.bib" not in warned[0]
    assert "pubs/shared/appendix.tex" in warned[1]
    # The ordinary bidirectional pull still happened
    with open(os.path.join(main_dir, "pubs", "mypub1", "main.tex")) as f:
        assert f.read() == "Hello, and more"
    assert ol_remote.head.commit.hexsha == ol_repo.head.commit.hexsha


def test_overleaf_sync_readiness_guards(tmp_dir):
    # Overleaf has no branches, so a sync is what everyone there sees. Two
    # things make that misleading: results that don't match the code that
    # made them, and a branch missing work that's already on the trunk.
    # Both are refused by default and both can be overridden.
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
    subprocess.run(
        [
            "calkit",
            "overleaf",
            "import",
            ol_url,
            "paper",
            "--title",
            "Test Pub",
        ],
        check=True,
    )
    default_branch = repo.active_branch.name
    repo.git.push(["--set-upstream", "origin", default_branch])
    # Importing creates a build stage that has never run, so the pipeline is
    # out-of-date and a plain sync is refused
    res = subprocess.run(
        ["calkit", "overleaf", "sync"], capture_output=True, text=True
    )
    assert res.returncode == 1
    output = res.stdout + res.stderr
    assert "Pipeline is not up-to-date" in output
    assert "--allow-stale" in output
    res = subprocess.run(
        ["calkit", "overleaf", "sync", "--allow-stale"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    # A branch cut before work that's already on the default branch is
    # refused, since syncing it would take collaborators backwards
    behind_from = repo.head.commit.hexsha
    with open("notes.md", "w") as f:
        f.write("Something that landed on the default branch")
    repo.git.add("notes.md")
    repo.git.commit(["-m", "Add notes"])
    repo.git.push()
    repo.git.checkout(["-b", "stale-branch", behind_from])
    res = subprocess.run(
        ["calkit", "overleaf", "sync", "--allow-stale"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    output = res.stdout + res.stderr
    assert "stale-branch" in output
    assert "--any-branch" in output
    res = subprocess.run(
        ["calkit", "overleaf", "sync", "--allow-stale", "--any-branch"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    # A branch cut from the tip is fine, since it's missing nothing
    repo.git.checkout(default_branch)
    repo.git.checkout(["-b", "fresh-branch"])
    res = subprocess.run(
        ["calkit", "overleaf", "sync", "--allow-stale"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr


def test_overleaf_push_and_pull(tmp_dir):
    # The guided commands wrap the same sync with the preparation steps that
    # otherwise have to be remembered: push sends the project's current state
    # one way, pull brings Overleaf's writing back.
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
    subprocess.run(
        [
            "calkit",
            "overleaf",
            "import",
            ol_url,
            "paper",
            "--title",
            "Test Pub",
        ],
        check=True,
    )
    repo.git.push(["--set-upstream", "origin", repo.active_branch.name])
    # A figure that only exists locally should reach Overleaf
    os.makedirs(os.path.join("paper", "figures"), exist_ok=True)
    with open(os.path.join("paper", "figures", "fig.txt"), "w") as f:
        f.write("A figure")
    repo.git.add("paper/figures/fig.txt")
    repo.git.commit(["-m", "Add a figure"])
    res = subprocess.run(
        [
            "calkit",
            "overleaf",
            "push",
            "--yes",
            "--no-pull",
            "--allow-stale",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Overleaf is up-to-date with this project" in res.stdout
    ol_dir = calkit.overleaf.get_project_dir(pid)
    assert os.path.isfile(os.path.join(ol_dir, "figures", "fig.txt"))
    # An edit made on Overleaf comes back with pull
    with open(os.path.join(ol_repo.working_dir, "main.tex"), "w") as f:
        f.write("This text was written on Overleaf")
    ol_repo.git.commit(["-a", "-m", "Update on Overleaf"])
    res = subprocess.run(
        [
            "calkit",
            "overleaf",
            "pull",
            "--yes",
            "--no-pull",
            "--allow-stale",
            "--no-run",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    with open(os.path.join("paper", "main.tex")) as f:
        assert f.read() == "This text was written on Overleaf"


def test_overleaf_sync_push_path_edits_need_force(tmp_dir):
    # A push path says the project owns the file, so an edit made to one on
    # Overleaf would be silently destroyed by the next sync. Nothing
    # regenerates it, unlike a pipeline output, so the sync stops until the
    # user decides. Generated files under a push path keep their own warning.
    main_dir = os.path.join(str(tmp_dir), "main")
    ol_dir = os.path.join(str(tmp_dir), "ol")
    ol_remote_dir = os.path.join(str(tmp_dir), "ol-remote")
    os.makedirs(os.path.join(main_dir, "pub", "figures"))
    os.makedirs(ol_dir)
    main_repo = git.Repo.init(main_dir)
    ol_remote = git.Repo.init(path=ol_remote_dir, bare=True)
    ol_repo = git.Repo.init(ol_dir)
    for parts, content in [
        (("pub", "main.tex"), "Hello"),
        (("pub", "figures", "photo.txt"), "A hand-made figure"),
        (("pub", "figures", "plot.txt"), "A generated figure"),
    ]:
        with open(os.path.join(main_dir, *parts), "w") as f:
            f.write(content)
    dvc_yaml = {
        "stages": {
            "plot": {
                "cmd": "echo plot",
                "outs": [{"pub/figures/plot.txt": {"cache": False}}],
            }
        }
    }
    with open(os.path.join(main_dir, "dvc.yaml"), "w") as f:
        calkit.ryaml.dump(dvc_yaml, f)
    with open(os.path.join(main_dir, "calkit.yaml"), "w") as f:
        calkit.ryaml.dump({"pipeline": {"stages": {}}}, f)
    main_repo.git.add(
        "pub/main.tex",
        "pub/figures/photo.txt",
        "pub/figures/plot.txt",
        "dvc.yaml",
        "calkit.yaml",
    )
    main_repo.git.commit(["-m", "Init project"])
    os.makedirs(os.path.join(ol_dir, "figures"))
    for parts, content in [
        (("main.tex",), "Hello"),
        (("figures", "photo.txt"), "A hand-made figure"),
        (("figures", "plot.txt"), "A generated figure"),
    ]:
        with open(os.path.join(ol_dir, *parts), "w") as f:
            f.write(content)
    ol_repo.git.add(".")
    ol_repo.git.commit(["-m", "Overleaf state"])
    last_sync_commit = ol_repo.head.commit.hexsha
    ol_repo.git.remote(["add", "origin", ol_remote_dir])
    ol_repo.git.push(["--set-upstream", "origin", ol_repo.active_branch.name])
    sync_info = {"push_paths": ["figures"]}
    # Both files under the push path are edited on Overleaf
    for parts, content in [
        (("figures", "photo.txt"), "Replaced on Overleaf"),
        (("figures", "plot.txt"), "Replaced on Overleaf"),
    ]:
        with open(os.path.join(ol_dir, *parts), "w") as f:
            f.write(content)
    ol_repo.git.commit(["-a", "-m", "Update on Overleaf"])
    paths = calkit.overleaf.OverleafSyncPaths(
        main_repo=main_repo,
        overleaf_repo=ol_repo,
        path_in_project="pub",
        sync_info_for_path=sync_info,
        last_sync_commit=last_sync_commit,
    )
    # Only the authored one blocks; the generated one is reported separately
    assert paths.push_path_edits_on_overleaf == ["figures/photo.txt"]
    assert paths.pipeline_outputs_changed_on_overleaf == ["figures/plot.txt"]
    kwargs = dict(
        main_repo=main_repo,
        overleaf_repo=ol_repo,
        path_in_project="pub",
        sync_info_for_path=sync_info,
        last_sync_commit=last_sync_commit,
        print_info=lambda *a, **k: None,
    )
    with pytest.raises(RuntimeError, match="figures/photo.txt"):
        calkit.overleaf.sync(**kwargs)
    # Nothing was touched on either side by the refused sync
    with open(os.path.join(ol_dir, "figures", "photo.txt")) as f:
        assert f.read() == "Replaced on Overleaf"
    assert not main_repo.git.status("--porcelain")
    # With --force, the project's version wins
    res = calkit.overleaf.sync(**kwargs, force=True)
    assert res["push_path_edits_on_overleaf"] == ["figures/photo.txt"]
    with open(os.path.join(ol_dir, "figures", "photo.txt")) as f:
        assert f.read() == "A hand-made figure"
    with open(os.path.join(main_dir, "pub", "figures", "photo.txt")) as f:
        assert f.read() == "A hand-made figure"
    assert ol_remote.head.commit.hexsha == ol_repo.head.commit.hexsha


def test_overleaf_sync_drops_legacy_sync_paths(tmp_dir):
    # sync_paths stopped doing anything once every stored file started
    # syncing both ways, so a project carrying one gets it removed on the
    # next sync, and is told why.
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
    subprocess.run(
        [
            "calkit",
            "overleaf",
            "import",
            ol_url,
            "paper",
            "--title",
            "Test Pub",
            "--push-path",
            "figures",
        ],
        check=True,
    )
    # Nothing writes sync_paths anymore, so put one there as an older
    # version of Calkit would have
    ck_info = calkit.load_calkit_info()
    ck_info["overleaf_sync"]["paper"]["sync_paths"] = ["main.tex"]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    repo.git.add("calkit.yaml")
    repo.git.commit(["-m", "Add legacy sync_paths"])
    res = subprocess.run(
        ["calkit", "overleaf", "sync", "--allow-stale"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "Removed 'sync_paths' from calkit.yaml" in res.stdout
    ck_info = calkit.load_calkit_info()
    assert "sync_paths" not in ck_info["overleaf_sync"]["paper"]
    # Push paths are kept, and the removal is committed rather than left
    # dirty in the working tree
    assert ck_info["overleaf_sync"]["paper"]["push_paths"] == ["figures"]
    assert not repo.git.status("--porcelain")
