"""Tests for ``calkit.workspace``."""

import os
import subprocess

import git
import pytest

import calkit.workspace as ws


def _init_repo() -> git.Repo:
    repo = git.Repo.init(".")
    repo.git.config("user.name", "Test")
    repo.git.config("user.email", "test@example.com")
    with open("script.py", "w") as f:
        f.write("print('one')\n")
    repo.git.add("script.py")
    repo.git.commit("-m", "init")
    return repo


def test_snapshot_captures_uncommitted_work(tmp_dir):
    repo = _init_repo()
    committed = ws.create_snapshot(repo=repo)
    # An unchanged tree snapshots to the committed tree
    assert repo.git.show(f"{committed}:script.py") == "print('one')"
    # Editing without committing is picked up, since that's what the user
    # is asking to run
    with open("script.py", "w") as f:
        f.write("print('two')\n")
    dirty = ws.create_snapshot(repo=repo)
    assert dirty != committed
    assert repo.git.show(f"{dirty}:script.py") == "print('two')"
    # So is a brand new file that was never added
    with open("helper.py", "w") as f:
        f.write("x = 1\n")
    with_new = ws.create_snapshot(repo=repo)
    assert repo.git.show(f"{with_new}:helper.py") == "x = 1"
    # And a deletion
    os.remove("helper.py")
    assert ws.create_snapshot(repo=repo) == dirty


def test_snapshot_leaves_the_users_repo_alone(tmp_dir):
    repo = _init_repo()
    with open("staged.py", "w") as f:
        f.write("staged = True\n")
    repo.git.add("staged.py")
    head_before = repo.head.commit.hexsha
    staged_before = repo.git.diff("--cached", "--name-only")
    sha = ws.create_snapshot(repo=repo)
    # The snapshot exists as an object but nothing points at it, so the
    # caller decides where it goes
    assert repo.git.cat_file("-t", sha) == "commit"
    assert ws.list_snapshots(repo=repo) == []
    # The user's branch, HEAD, and index are all where they were
    assert repo.head.commit.hexsha == head_before
    assert repo.git.diff("--cached", "--name-only") == staged_before
    assert repo.active_branch.name in ("main", "master")


def test_snapshot_ignores_gitignored_data(tmp_dir):
    # DVC-tracked data is gitignored and moves through the DVC cache, so it
    # must not be dragged into the snapshot as Git blobs
    repo = _init_repo()
    with open(".gitignore", "w") as f:
        f.write("data/\n")
    os.makedirs("data", exist_ok=True)
    with open("data/big.csv", "w") as f:
        f.write("a,b\n1,2\n")
    sha = ws.create_snapshot(repo=repo)
    listed = repo.git.ls_tree("-r", "--name-only", sha).splitlines()
    assert "data/big.csv" not in listed
    assert "script.py" in listed


def test_snapshots_are_deterministic(tmp_dir):
    # A pipeline of many stages shares one working tree, so it should
    # transfer once rather than leaving a ref behind per stage
    repo = _init_repo()
    with open("script.py", "w") as f:
        f.write("print('changed')\n")
    first = ws.create_snapshot(repo=repo)
    second = ws.create_snapshot(repo=repo)
    assert first == second
    # Real commit metadata would make these differ; they must not
    assert "Calkit" in repo.git.show("-s", "--format=%an", first)


def test_snapshot_refs_never_collide_across_branch_names(tmp_dir):
    repo = _init_repo()
    repo.git.checkout("-b", "feature")
    with open("script.py", "w") as f:
        f.write("print('feature')\n")
    feature_sha = ws.create_snapshot(repo=repo)
    repo.git.update_ref(ws.snapshot_ref(feature_sha), feature_sha)
    # Git itself cannot hold 'feature' and 'feature/x' as branches at once,
    # which is the trap any branch-derived transfer naming walks into
    with pytest.raises(git.exc.GitCommandError, match="cannot create"):
        repo.git.checkout("-b", "feature/x")
    # Naming a snapshot by its content has no such structure to conflict
    with open("script.py", "w") as f:
        f.write("print('feature x')\n")
    nested_sha = ws.create_snapshot(repo=repo)
    repo.git.update_ref(ws.snapshot_ref(nested_sha), nested_sha)
    assert sorted(ws.list_snapshots(repo=repo)) == sorted(
        [feature_sha, nested_sha]
    )
    # Identical content reached from a differently named branch is the same
    # snapshot, not a second one, so clones that share branch names don't
    # multiply refs in a shared workspace
    repo.git.checkout("-f", "-b", "someone-elses-name", "feature")
    with open("script.py", "w") as f:
        f.write("print('feature x')\n")
    assert ws.create_snapshot(repo=repo) == nested_sha


def test_prune_forgets_snapshots_but_keeps_whats_running(tmp_dir):
    repo = _init_repo()
    shas = []
    for text in ["one-b", "two-b", "three-b"]:
        with open("script.py", "w") as f:
            f.write(f"print('{text}')\n")
        sha = ws.create_snapshot(repo=repo)
        repo.git.update_ref(ws.snapshot_ref(sha), sha)
        shas.append(sha)
    assert sorted(ws.list_snapshots(repo=repo)) == sorted(shas)
    # A workspace has the snapshot it's running checked out; pruning must
    # not drop the last ref to it, or the checkout becomes collectable
    repo.git.checkout("-f", "--detach", shas[1])
    pruned = ws.prune_snapshots(repo=repo)
    assert sorted(pruned) == sorted([shas[0], shas[2]])
    assert ws.list_snapshots(repo=repo) == [shas[1]]
    # An explicitly kept snapshot survives too, and everything else goes
    repo.git.checkout("-f", "-")
    for sha in shas:
        repo.git.update_ref(ws.snapshot_ref(sha), sha)
    ws.prune_snapshots(repo=repo, keep=[shas[0]])
    assert ws.list_snapshots(repo=repo) == [shas[0]]


def test_snapshot_can_be_pushed_to_a_workspace_and_checked_out(tmp_dir):
    # The whole point: the workspace ends up on the snapshot without a
    # branch being created on either side
    repo = _init_repo()
    workspace_dir = os.path.join(os.getcwd(), "workspace")
    subprocess.check_call(["git", "clone", "-q", os.getcwd(), workspace_dir])
    with open("script.py", "w") as f:
        f.write("print('uncommitted work')\n")
    sha = ws.create_snapshot(repo=repo)
    repo.git.push(workspace_dir, f"{sha}:{ws.snapshot_ref(sha)}")
    workspace = git.Repo(workspace_dir)
    branches_before = sorted(h.name for h in workspace.heads)
    workspace.git.checkout("--detach", sha)
    # The workspace now holds exactly what was on screen locally, including
    # the edit that was never committed
    with open(os.path.join(workspace_dir, "script.py")) as f:
        assert f.read() == "print('uncommitted work')\n"
    assert workspace.head.is_detached
    assert workspace.head.commit.hexsha == sha
    # No branch was created there, so nothing can collide with a branch of
    # the same name from another clone of the project
    assert sorted(h.name for h in workspace.heads) == branches_before
    assert ws.list_snapshots(repo=workspace) == [sha]
    # And cleanup is one namespace, not a set of names to recognize
    workspace.git.checkout("-f", "-")
    assert ws.prune_snapshots(repo=workspace) == [sha]
    assert ws.list_snapshots(repo=workspace) == []


def test_working_tree_matches_catches_edits_during_a_remote_run(tmp_dir):
    # DVC hashes a stage's deps from local files after the command returns.
    # If the tree changed while the stage ran elsewhere, recording the
    # result would pair inputs that never ran with outputs they never
    # produced, and that lock file reads as up to date forever.
    repo = _init_repo()
    with open("script.py", "w") as f:
        f.write("print('what was sent')\n")
    sent = ws.create_snapshot(repo=repo)
    # Nothing moved while the stage ran, so the result is safe to record
    assert ws.working_tree_matches(sent, repo=repo)
    # Someone edits a dependency mid-run
    with open("script.py", "w") as f:
        f.write("print('edited mid-run')\n")
    assert not ws.working_tree_matches(sent, repo=repo)
    # Putting it back makes it safe again, since the check is on content
    # rather than on timestamps
    with open("script.py", "w") as f:
        f.write("print('what was sent')\n")
    assert ws.working_tree_matches(sent, repo=repo)
