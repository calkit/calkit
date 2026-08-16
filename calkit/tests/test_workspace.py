"""Tests for ``calkit.workspace``."""

import os
import subprocess
import sys

import git
import pytest

import calkit.workspace as ws

# Not a Windows defect to fix later: the workspace shell is only ever
# executed on the far end of an SSH connection, which is POSIX by
# construction -- the transfer also leans on mkdir -p, nohup, and ps -p, and
# a workspace's wdir is always a POSIX path. Handing it a local C:\... path
# exercises a situation that cannot arise. Everything else in this module,
# including the push and detached checkout, still runs on Windows.
skipif_windows_remote_shell = pytest.mark.skipif(
    sys.platform == "win32",
    reason="The workspace shell only ever runs on the remote POSIX host",
)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    """Keep every test in this module out of the real home directory.

    Setup here writes SSH keys and ~/.ssh/config entries, which is
    someone's actual machine configuration. A test that reaches it is not
    a failing test, it is a damaged laptop, so the isolation is applied to
    the whole module rather than remembered per test.
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


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


def test_workspace_from_env_needs_only_a_host():
    # A host is the one thing the project has to say. Repeating the user
    # here would just be a second place for it to be wrong, so it's left to
    # SSH, which resolves it from ~/.ssh/config or the current account.
    w = ws.Workspace.from_env(
        env={"kind": "system", "host": "box.example.org"},
        env_name="remote",
        ck_info={"name": "example-ssh", "owner": "calkit"},
    )
    assert w.target == "box.example.org"
    assert w.user is None
    # And the workspace lands somewhere predictable rather than needing a
    # path spelled out that would be the same on every machine
    assert w.wdir == ".calkit/workspaces/calkit.io/calkit/example-ssh"
    # Declaring them still works, and wins
    w = ws.Workspace.from_env(
        env={
            "kind": "system",
            "host": "box.example.org",
            "user": "me",
            "wdir": "/home/me/proj",
            "ssh_key": "~/.ssh/id_ed25519",
        },
        env_name="remote",
        ck_info={"name": "example-ssh", "owner": "calkit"},
    )
    assert w.target == "me@box.example.org"
    # Pushed straight to the workspace, so snapshots never touch whatever
    # remote the project is hosted on
    assert w.git_url == "ssh://me@box.example.org/home/me/proj"
    assert w.ssh_key is not None
    assert w.ssh_key.startswith(os.path.expanduser("~"))
    assert w.ssh_options[0] == "-i"
    assert w.git_ssh_command.startswith("ssh -i ")
    assert w.ssh_argv("ls")[:1] == ["ssh"]
    assert w.ssh_argv("ls")[-2:] == ["me@box.example.org", "ls"]
    assert w.path("sub") == "/home/me/proj/sub"


def test_workspace_from_env_still_needs_somewhere_to_run():
    # Without a host there is nothing to reach
    with pytest.raises(ValueError, match="no host"):
        ws.Workspace.from_env(env={"kind": "system"}, env_name="remote")
    # A nameless project can't have a directory derived for it, and picking
    # one anyway would run the stage somewhere it never named
    with pytest.raises(ValueError, match="'wdir'"):
        ws.Workspace.from_env(
            env={"kind": "system", "host": "box"}, env_name="remote"
        )


def test_resolve_wdir_expands_against_the_far_ends_home(monkeypatch):
    # The default workspace is relative to the connecting user's home, which
    # only that machine can resolve; an ssh:// URL and a cd both need it
    # absolute
    calls = []

    def fake_check_output(argv, *a, **kw):
        calls.append(argv)
        return b"/home/parallels\n"

    monkeypatch.setattr(ws.subprocess, "check_output", fake_check_output)
    w = ws.Workspace(host="box", wdir="calkit/example-ssh")
    resolved = ws.resolve_wdir(w)
    assert resolved.wdir == "/home/parallels/calkit/example-ssh"
    assert resolved.git_url == "ssh://box/home/parallels/calkit/example-ssh"
    assert calls and calls[0][-1] == "echo $HOME"
    # A tilde means the same thing
    assert (
        ws.resolve_wdir(ws.Workspace(host="box", wdir="~/work")).wdir
        == "/home/parallels/work"
    )
    assert ws.resolve_wdir(ws.Workspace(host="box", wdir="~")).wdir == (
        "/home/parallels"
    )
    # An absolute one is already unambiguous, so nothing is asked
    calls.clear()
    already = ws.Workspace(host="box", wdir="/abs/dir")
    assert ws.resolve_wdir(already) is already
    assert calls == []


def test_check_connection_refuses_to_sit_at_a_prompt(monkeypatch):
    # BatchMode is what makes this a check rather than a hang waiting for a
    # password, which is the whole reason it can run during 'calkit run'
    seen = []
    monkeypatch.setattr(
        ws.subprocess,
        "run",
        lambda argv, **kw: (
            seen.append(argv) or subprocess.CompletedProcess(argv, 0)
        ),
    )
    ws.check_connection(ws.Workspace(host="box", user="me", wdir="/w"))
    assert "BatchMode=yes" in seen[0]
    assert "ConnectTimeout=10" in seen[0]


def test_ensure_calkit_installed_offers_to_install_it_there(monkeypatch):
    w = ws.Workspace(host="box", wdir="/w")
    monkeypatch.setattr(ws, "has_calkit", lambda ws_: True)
    assert ws.ensure_calkit_installed(w, interactive=False, required=True)
    # Missing but never called: don't block on a tool this run doesn't use
    monkeypatch.setattr(ws, "has_calkit", lambda ws_: False)
    assert not ws.ensure_calkit_installed(w, interactive=False, required=False)
    # Missing and needed, with nobody to ask: give the command
    with pytest.raises(ValueError, match="install.calkit.org"):
        ws.ensure_calkit_installed(w, interactive=False, required=True)
    # At a terminal, offer to run it there
    ran = []
    seen = [False]

    def has(ws_):
        return seen[0]

    monkeypatch.setattr(ws, "has_calkit", has)
    monkeypatch.setattr("builtins.input", lambda *a: "y")

    def run(argv, **kw):
        ran.append(argv)
        seen[0] = True

    monkeypatch.setattr(ws, "_run", run)
    assert ws.ensure_calkit_installed(w, interactive=True, required=True)
    assert ran and "install.calkit.org" in " ".join(ran[0])


def _ssh_failure(stderr: str):
    def run(argv, **kw):
        raise subprocess.CalledProcessError(255, argv, stderr=stderr.encode())

    return run


def test_check_connection_tells_the_failures_apart(monkeypatch):
    # SSH refuses for more than one reason and the fixes differ, so
    # reporting every failure as an unauthorized key sends people down the
    # wrong path
    w = ws.Workspace(host="box", wdir="/w", ssh_key="/k")
    monkeypatch.setattr(
        ws.subprocess, "run", _ssh_failure("Host key verification failed.")
    )
    with pytest.raises(ws.HostKeyUnknown, match="ssh box"):
        ws.check_connection(w)
    monkeypatch.setattr(
        ws.subprocess,
        "run",
        _ssh_failure("@ REMOTE HOST IDENTIFICATION HAS CHANGED! @"),
    )
    with pytest.raises(ws.HostKeyChanged, match="ssh-keygen -R box"):
        ws.check_connection(w)
    monkeypatch.setattr(
        ws.subprocess, "run", _ssh_failure("Permission denied (publickey).")
    )
    with pytest.raises(ws.ConnectionProblem) as excinfo:
        ws.check_connection(w)
    # ssh-copy-id takes the key with -i, ssh-add takes it positionally
    assert "ssh-copy-id -i /k box" in str(excinfo.value)
    assert "ssh-add /k" in str(excinfo.value)


def test_ensure_reachable_never_papers_over_a_changed_host_key(monkeypatch):
    # A changed key is what both a rebuilt VM and a machine-in-the-middle
    # look like, and only the user can tell those apart
    w = ws.Workspace(host="box", wdir="/w")

    def changed(ws_):
        raise ws.HostKeyChanged("changed")

    monkeypatch.setattr(ws, "check_connection", changed)
    monkeypatch.setattr(
        "builtins.input", lambda *a: pytest.fail("offered to fix it")
    )
    ran = []
    monkeypatch.setattr(ws, "_run", lambda argv, **kw: ran.append(argv))
    with pytest.raises(ws.HostKeyChanged):
        ws.ensure_reachable(w, interactive=True)
    assert ran == []


def test_ensure_reachable_lets_ssh_show_the_fingerprint(monkeypatch):
    # An unknown host is verified by the user, not accepted on their behalf
    w = ws.Workspace(host="box", wdir="/w")
    attempts = []

    def unknown_then_fine(ws_):
        attempts.append(ws_)
        if len(attempts) == 1:
            raise ws.HostKeyUnknown("unknown")

    monkeypatch.setattr(ws, "check_connection", unknown_then_fine)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    ran = []
    monkeypatch.setattr(ws, "_run", lambda argv, **kw: ran.append(argv))
    ws.ensure_reachable(w, interactive=True)
    assert ran and ran[0][0] == "ssh"
    # Neither of these may appear: they would skip the very check the
    # prompt exists to perform
    joined = " ".join(ran[0])
    assert "BatchMode" not in joined
    assert "StrictHostKeyChecking" not in joined
    assert len(attempts) == 2


def test_workspace_without_a_key_omits_the_identity_flag():
    # No key declared means SSH picks the identity itself, from its own
    # config or agent -- which is where a key for one particular host
    # belongs anyway
    w = ws.Workspace(host="box", user="me", wdir="/w")
    assert w.ssh_options == []
    assert "-i" not in w.git_ssh_command
    assert "-i" not in w.scp_to_argv(["a"], "/w")
    assert w.scp_to_argv(["a"], "/w")[-2:] == ["a", "me@box:/w"]
    assert w.scp_from_argv("/w/a", ".")[-2:] == ["me@box:/w/a", "."]


def test_paths_to_transfer_skips_what_the_snapshot_carries(tmp_dir):
    # Git-tracked files ride along in the snapshot; only DVC's ignored data
    # has to be sent separately
    repo = _init_repo()
    with open(".gitignore", "w") as f:
        f.write("data/\n")
    repo.git.add(".gitignore")
    repo.git.commit("-m", "ignore data")
    os.makedirs("data", exist_ok=True)
    with open("data/in.csv", "w") as f:
        f.write("a\n")
    assert ws.paths_to_transfer(["script.py"], repo=repo) == []
    assert ws.paths_to_transfer(["data/in.csv"], repo=repo) == ["data/in.csv"]
    assert ws.paths_to_transfer(["script.py", "data/in.csv"], repo=repo) == [
        "data/in.csv"
    ]
    # A path that doesn't exist locally has nothing to send
    assert ws.paths_to_transfer(["data/missing.csv"], repo=repo) == []
    assert ws.paths_to_transfer([], repo=repo) == []


def test_prune_command_cleans_a_workspace_without_touching_its_checkout(
    tmp_dir,
):
    # The prune runs as a shell one-liner on the far end, where a quoting
    # slip would either delete nothing or delete the ref a running stage is
    # holding. Exercise the shell itself rather than trusting it.
    repo = _init_repo()
    workspace_dir = os.path.join(os.getcwd(), "work space")
    subprocess.check_call(["git", "clone", "-q", os.getcwd(), workspace_dir])
    workspace = git.Repo(workspace_dir)
    shas = []
    for text in ["a", "b", "c"]:
        with open("script.py", "w") as f:
            f.write(f"print('{text}')\n")
        sha = ws.create_snapshot(repo=repo)
        repo.git.push(workspace_dir, f"{sha}:{ws.snapshot_ref(sha)}")
        shas.append(sha)
    workspace.git.checkout("--force", "--detach", shas[1])
    assert sorted(ws.list_snapshots(repo=workspace)) == sorted(shas)
    # A branch the workspace cares about must survive the sweep
    workspace.git.branch("keep-me", shas[0])
    subprocess.check_call(
        ["bash", "-c", ws.prune_command(workspace_dir)],
    )
    # Only what it's sitting on is left, and the branch is untouched
    assert ws.list_snapshots(repo=workspace) == [shas[1]]
    assert "keep-me" in [h.name for h in workspace.heads]
    assert workspace.head.commit.hexsha == shas[1]


def test_prune_command_is_quoted_and_scoped():
    # Runs everywhere, including Windows, since the risky parts of the
    # remote shell are in how it's built rather than in running it
    cmd = ws.prune_command("/home/me/work space")
    # A workspace path with a space has to survive as one argument
    assert "cd '/home/me/work space'" in cmd
    # Scoped to the reserved namespace, so no branch can be swept up
    assert ws.SNAPSHOT_REF_NS in cmd
    assert "refs/heads" not in cmd
    # And whatever the workspace is sitting on is spared
    assert "git rev-parse HEAD" in cmd
    assert '"$obj" != "$head"' in cmd


def test_remote_system_info_reads_the_machine_that_runs_the_stage(
    monkeypatch,
):
    # A system env's lock describes the machine the results depend on, which
    # is the far end, not this one
    monkeypatch.setattr(
        ws.subprocess,
        "check_output",
        lambda argv, *a, **kw: b'{"cpu_count": 64, "os": "Linux"}',
    )
    w = ws.Workspace(host="box", wdir="/w")
    assert ws.remote_system_info(w) == {"cpu_count": 64, "os": "Linux"}

    # Calkit has to be there to answer; say so rather than failing obscurely
    def fail(argv, *a, **kw):
        raise subprocess.CalledProcessError(127, argv)

    monkeypatch.setattr(ws.subprocess, "check_output", fail)
    with pytest.raises(ValueError, match="requires Calkit on that machine"):
        ws.remote_system_info(w)


def test_expand_with_prompts_asks_for_what_the_environment_lacks(
    tmp_dir, monkeypatch
):
    # A project shares calkit.yaml but not .env, so ${CK_SSH_HOST} is the
    # first thing to be missing for anyone but its author
    monkeypatch.delenv("CK_SSH_HOST", raising=False)
    monkeypatch.setattr("builtins.input", lambda *a: "box.example.org")
    assert (
        ws.expand_with_prompts(
            "${CK_SSH_HOST}", interactive=True, described_as="the host"
        )
        == "box.example.org"
    )
    # Stored, so it's only asked once, and kept out of Git
    assert os.environ["CK_SSH_HOST"] == "box.example.org"
    with open(".env") as f:
        assert "CK_SSH_HOST" in f.read()
    # Already set means no question
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("asked"))
    assert (
        ws.expand_with_prompts(
            "${CK_SSH_HOST}", interactive=True, described_as="the host"
        )
        == "box.example.org"
    )
    # With nobody to answer, say what to set rather than trying a host
    # literally named '${CK_SSH_KEY}'
    monkeypatch.delenv("CK_SSH_KEY", raising=False)
    with pytest.raises(ValueError, match="calkit set-env-var CK_SSH_KEY"):
        ws.expand_with_prompts(
            "${CK_SSH_KEY}", interactive=False, described_as="the key"
        )


def test_ensure_reachable_offers_to_authorize_this_machine(monkeypatch):
    w = ws.Workspace(host="box", user="me", wdir="/w", ssh_key="/tmp/k")
    # Already reachable: nothing is asked and nothing is changed
    monkeypatch.setattr(ws, "check_connection", lambda ws_: None)
    monkeypatch.setattr(
        "builtins.input", lambda *a: pytest.fail("asked needlessly")
    )
    ws.ensure_reachable(w, interactive=True)

    # Unreachable with nobody watching: fail with the commands to run,
    # since a pipeline in CI has nobody to answer
    def unreachable(ws_):
        raise ws.ConnectionProblem("Could not connect; run ssh-copy-id")

    monkeypatch.setattr(ws, "check_connection", unreachable)
    with pytest.raises(ValueError, match="ssh-copy-id"):
        ws.ensure_reachable(w, interactive=False)
    # Unreachable at a terminal, and the user declines: their answer stands
    monkeypatch.setattr(os.path, "isfile", lambda p: True)
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    with pytest.raises(ValueError, match="ssh-copy-id"):
        ws.ensure_reachable(w, interactive=True)
    # Accepting runs ssh-copy-id, then confirms it actually took rather
    # than trusting the copy
    ran = []
    attempts = []

    def sometimes(ws_):
        attempts.append(ws_)
        if len(attempts) == 1:
            raise ws.ConnectionProblem("Could not connect; run ssh-copy-id")

    monkeypatch.setattr(ws, "check_connection", sometimes)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    monkeypatch.setattr(ws, "_run", lambda argv, **kw: ran.append(argv))
    ws.ensure_reachable(w, interactive=True)
    assert ran and ran[0][0] == "ssh-copy-id"
    assert "-i" in ran[0] and "me@box" in ran[0]
    assert len(attempts) == 2


def test_default_wdir_is_qualified_and_tool_managed():
    # A host is shared, so two projects named the same from different
    # owners must not land on one checkout
    mine = ws.default_wdir(
        {"name": "example-ssh", "owner": "calkit", "hub": "calkit.io"}
    )
    theirs = ws.default_wdir(
        {"name": "example-ssh", "owner": "someone-else", "hub": "calkit.io"}
    )
    assert mine == ".calkit/workspaces/calkit.io/calkit/example-ssh"
    assert mine != theirs
    # Hidden and tool-managed, because transfers check out with --force:
    # a path that looks like the user's own checkout is one whose edits we
    # would silently destroy
    assert mine.startswith(".calkit/workspaces/")
    # A hub may be written with a scheme, and a project may have neither
    # hub nor owner
    assert (
        ws.default_wdir(
            {"name": "p", "owner": "o", "hub": "https://hub.example.org/"}
        )
        == ".calkit/workspaces/hub.example.org/o/p"
    )
    assert ws.default_wdir({"name": "p"}).startswith(
        ".calkit/workspaces/calkit.io/"
    )
    # These come from a config file, so they can't be trusted to be
    # well-behaved directory names
    escaped = ws.default_wdir(
        {"name": "../evil", "owner": "..", "hub": "x/../y"}
    )
    assert ".." not in escaped.split("/")
    assert escaped.startswith(".calkit/workspaces/")
    with pytest.raises(ValueError, match="no name"):
        ws.default_wdir({})


def test_lock_is_beside_the_workspace_not_inside_it():
    # Inside would put it in the checkout that transfers overwrite, and in
    # the project whose files the stage reads
    assert (
        ws.lock_path("/home/me/.calkit/workspaces/h/o/p")
        == "/home/me/.calkit/workspaces/h/o/p.lock"
    )
    assert ws.lock_path("/w/") == "/w.lock"


def test_acquire_lock_takes_turns_and_says_who_has_it(monkeypatch):
    w = ws.Workspace(host="box", wdir="/w")
    # mkdir is the gate because it's atomic; winning it means it's ours
    monkeypatch.setattr(
        ws.subprocess, "check_output", lambda argv, **kw: b"ACQUIRED\n"
    )
    ws.acquire_lock(w, holder="abc", info="stage x")
    # Held by this same run, e.g. waiting again on a job dispatched
    # earlier, is not a conflict with ourselves
    monkeypatch.setattr(
        ws.subprocess,
        "check_output",
        lambda argv, **kw: b"HELD\tabc\tstage x from laptop\n",
    )
    ws.acquire_lock(w, holder="abc", info="stage x")
    # Held by someone else: say who, and how to clear it if they're gone
    monkeypatch.setattr(
        ws.subprocess,
        "check_output",
        lambda argv, **kw: b"HELD\tzzz\tother-stage from server\n",
    )
    with pytest.raises(ws.WorkspaceBusy) as excinfo:
        ws.acquire_lock(w, holder="abc", info="stage x")
    assert "other-stage from server" in str(excinfo.value)
    assert "rm -rf /w.lock" in str(excinfo.value)
    # A login banner ahead of the answer must not be mistaken for one
    monkeypatch.setattr(
        ws.subprocess,
        "check_output",
        lambda argv, **kw: b"Welcome to Ubuntu\nACQUIRED\n",
    )
    ws.acquire_lock(w, holder="abc", info="stage x")


def test_holds_snapshot_guards_against_a_workspace_that_moved(monkeypatch):
    w = ws.Workspace(host="box", wdir="/w")
    sha = "a" * 40
    monkeypatch.setattr(
        ws.subprocess, "check_output", lambda argv, **kw: (sha + "\n").encode()
    )
    assert ws.holds_snapshot(w, sha)
    monkeypatch.setattr(
        ws.subprocess,
        "check_output",
        lambda argv, **kw: (("b" * 40) + "\n").encode(),
    )
    assert not ws.holds_snapshot(w, sha)

    # An unreachable or non-repo workspace is not proof it's on our commit
    def fail(argv, **kw):
        raise subprocess.CalledProcessError(128, argv)

    monkeypatch.setattr(ws.subprocess, "check_output", fail)
    assert not ws.holds_snapshot(w, sha)


def test_login_argv_runs_the_way_logging_in_would():
    # ssh gives a non-login, non-interactive shell, so ~/.local/bin -- where
    # Calkit's own installer puts it -- is not on PATH
    w = ws.Workspace(host="box", wdir="/w")
    argv = w.login_argv("command -v calkit")
    assert argv[0] == "ssh"
    assert argv[-2] == "box"
    assert argv[-1].startswith("bash -lc ")
    assert "command -v calkit" in argv[-1]


def test_run_in_workspace_survives_a_disconnect(tmp_dir, monkeypatch):
    # The whole point of dispatching detached: losing the connection, or
    # stopping the pipeline, must not kill the work, and running again has
    # to pick the same job back up rather than starting a second one
    repo = _init_repo()
    w = ws.Workspace(host="box", wdir="/w")
    monkeypatch.setattr(ws, "acquire_lock", lambda *a, **kw: None)
    released = []
    monkeypatch.setattr(
        ws, "release_lock", lambda ws_, holder, **kw: released.append(holder)
    )
    monkeypatch.setattr(ws, "send_snapshot", lambda **kw: None)
    monkeypatch.setattr(ws, "send_paths", lambda **kw: None)
    monkeypatch.setattr(ws, "prune_remote_snapshots", lambda **kw: None)
    monkeypatch.setattr(ws, "holds_snapshot", lambda ws_, sha: True)
    fetched = []
    monkeypatch.setattr(
        ws, "fetch_paths", lambda workspace, paths, **kw: fetched.extend(paths)
    )
    monkeypatch.setattr(ws, "_run", lambda argv, **kw: None)
    monkeypatch.setattr(ws.time, "sleep", lambda s: None)
    dispatched = []
    alive = [True]

    def check_output(argv, **kw):
        joined = " ".join(argv)
        if "nohup" in joined:
            dispatched.append(joined)
            return b"Welcome to Ubuntu\n4242\n"
        if "ps -p" in joined:
            if alive[0]:
                alive[0] = False
                return b"  PID TTY\n 4242 ?\n"
            raise subprocess.CalledProcessError(1, argv)
        raise AssertionError(f"unexpected: {joined}")

    monkeypatch.setattr(ws.subprocess, "check_output", check_output)
    ws.run_in_workspace(
        workspace=w,
        command="calkit scheduler batch --name sim -- ./run.sh",
        job_key="cluster::sim",
        label="cluster",
        get=["results"],
        repo=repo,
        echo=lambda *a: None,
    )
    # Started detached, and the PID survives a login banner on stdout
    assert len(dispatched) == 1 and "nohup" in dispatched[0]
    assert fetched == ["results"]
    assert released
    # The job is recorded so a later run can find it again
    jobs = ws._load_jobs(ws.JOBS_FPATH)
    assert "cluster::sim" in jobs
    assert jobs["cluster::sim"]["remote_pid"] is None
    assert jobs["cluster::sim"]["snapshot"]


def test_run_in_workspace_resumes_instead_of_starting_a_second_job(
    tmp_dir, monkeypatch
):
    repo = _init_repo()
    w = ws.Workspace(host="box", wdir="/w")
    snapshot = ws.create_snapshot(repo=repo)
    # Stand in for a previous run that was interrupted while waiting
    ws._save_jobs(
        ws.JOBS_FPATH,
        {"cluster::sim": {"remote_pid": "4242", "snapshot": snapshot}},
    )
    monkeypatch.setattr(ws, "acquire_lock", lambda *a, **kw: None)
    monkeypatch.setattr(ws, "release_lock", lambda *a, **kw: None)
    monkeypatch.setattr(ws, "prune_remote_snapshots", lambda **kw: None)
    monkeypatch.setattr(ws, "holds_snapshot", lambda ws_, sha: True)
    monkeypatch.setattr(ws, "_run", lambda argv, **kw: None)
    monkeypatch.setattr(ws.time, "sleep", lambda s: None)

    def no_dispatch(**kw):
        pytest.fail("started a second job instead of waiting for the first")

    monkeypatch.setattr(ws, "send_snapshot", no_dispatch)

    def check_output(argv, **kw):
        joined = " ".join(argv)
        assert "nohup" not in joined, "resubmitted an already-running job"
        raise subprocess.CalledProcessError(1, argv)  # already finished

    monkeypatch.setattr(ws.subprocess, "check_output", check_output)
    ws.run_in_workspace(
        workspace=w,
        command="whatever",
        job_key="cluster::sim",
        label="cluster",
        repo=repo,
        echo=lambda *a: None,
    )
    assert ws._load_jobs(ws.JOBS_FPATH)["cluster::sim"]["remote_pid"] is None


def test_run_in_workspace_refuses_results_from_a_moved_workspace(
    tmp_dir, monkeypatch
):
    repo = _init_repo()
    w = ws.Workspace(host="box", wdir="/w")
    snapshot = ws.create_snapshot(repo=repo)
    ws._save_jobs(
        ws.JOBS_FPATH,
        {"c::s": {"remote_pid": "1", "snapshot": snapshot}},
    )
    monkeypatch.setattr(ws, "acquire_lock", lambda *a, **kw: None)
    monkeypatch.setattr(ws, "release_lock", lambda *a, **kw: None)
    monkeypatch.setattr(ws.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        ws.subprocess,
        "check_output",
        lambda argv, **kw: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, argv)
        ),
    )
    # The workspace is no longer on the commit we sent it, so its outputs
    # came from something this run never sent
    monkeypatch.setattr(ws, "holds_snapshot", lambda ws_, sha: False)
    monkeypatch.setattr(
        ws, "fetch_paths", lambda **kw: pytest.fail("collected anyway")
    )
    with pytest.raises(ws.WorkspaceStateChanged, match="no longer on the"):
        ws.run_in_workspace(
            workspace=w,
            command="whatever",
            job_key="c::s",
            label="c",
            get=["results"],
            repo=repo,
            echo=lambda *a: None,
        )


def test_changed_deps_only_cares_about_the_job_s_dependencies(tmp_dir):
    # Hashing deps at dispatch and comparing when the job finishes is the
    # same check a scheduler job makes about its own validity
    _init_repo()
    os.makedirs("scripts", exist_ok=True)
    with open("scripts/collect.py", "w") as f:
        f.write("print('one')\n")
    with open("README.md", "w") as f:
        f.write("unrelated\n")
    deps = ["scripts/collect.py"]
    before = ws.dep_md5s(deps)
    assert ws.changed_deps(before, deps) == []
    # An untracked dependency still counts -- it was sent, so it matters.
    # (A plain 'git diff <commit> -- path' would call it deleted.)
    assert "scripts/collect.py" in before
    # Editing something the job never read must not discard a finished job
    with open("README.md", "w") as f:
        f.write("edited while the job ran\n")
    assert ws.changed_deps(before, deps) == []
    # Editing what it did read must
    with open("scripts/collect.py", "w") as f:
        f.write("print('two')\n")
    assert ws.changed_deps(before, deps) == ["scripts/collect.py"]
    # So must deleting it
    os.remove("scripts/collect.py")
    assert ws.changed_deps(before, deps) == ["scripts/collect.py"]
    # A job with no declared deps has nothing to invalidate
    assert ws.changed_deps({}, []) == []


def test_hosts_work_the_same_written_as_a_name_or_an_address():
    # A project writes its machine down whichever way is convenient, and
    # neither form should be second class
    for host in ["cluster.example.org", "10.211.55.5"]:
        w = ws.Workspace(host=host, user="me", wdir="/home/me/p")
        assert w.git_url == f"ssh://me@{host}/home/me/p"
        assert w.scp_to_argv(["a"], "/d")[-1] == f"me@{host}:/d"
        assert w.ssh_argv("ls")[-2] == f"me@{host}"
    # An IPv6 literal is all colons, which is what separates a host from a
    # port, so a URL has to bracket it or it isn't a URL at all
    w = ws.Workspace(host="::1", user="me", wdir="/home/me/p")
    assert w.git_url == "ssh://me@[::1]/home/me/p"
    assert w.scp_to_argv(["a"], "/d")[-1] == "me@[::1]:/d"
    # ssh itself takes the bare form
    assert w.ssh_argv("ls")[-2] == "me@::1"
    # And a host with no user declared stays userless in every form
    w = ws.Workspace(host="10.0.0.9", wdir="/w")
    assert w.git_url == "ssh://10.0.0.9/w"
    assert w.scp_target == "10.0.0.9"


def test_ensure_reachable_creates_a_key_when_there_is_none(
    tmp_dir, monkeypatch
):
    # Someone starting from nothing shouldn't have to know the ssh-keygen
    # incantation; the point is that the setup walks them through it
    home = os.path.join(os.getcwd(), "home")
    os.makedirs(home)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", home))
    w = ws.Workspace(host="box", wdir="/w")
    attempts = []

    def unreachable_then_fine(ws_):
        attempts.append(ws_)
        if len(attempts) == 1:
            raise ws.ConnectionProblem("no key")

    monkeypatch.setattr(ws, "check_connection", unreachable_then_fine)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    ran = []
    monkeypatch.setattr(ws, "_run", lambda argv, **kw: ran.append(argv))
    result = ws.ensure_reachable(w, interactive=True)
    keygen = [a for a in ran if a[0] == "ssh-keygen"]
    assert keygen, "did not offer to create a key"
    # ed25519 with no passphrase, so stages can run unattended
    assert "-t" in keygen[0] and "ed25519" in keygen[0]
    assert keygen[0][keygen[0].index("-N") + 1] == ""
    key_path = keygen[0][keygen[0].index("-f") + 1]
    assert key_path.endswith("id_ed25519")
    # The created key has to come back with the workspace, or the caller
    # goes on connecting without the key that was just made for it
    assert result.ssh_key == key_path
    # Then it authorizes with that key, and confirms rather than assuming
    copy = [a for a in ran if a[0] == "ssh-copy-id"]
    assert copy and key_path in copy[0]
    assert len(attempts) == 2


def test_unattended_work_never_waits_on_a_password():
    # Every transfer and remote command can run mid-pipeline, where a
    # password prompt has nobody to answer it and no way to be seen. Key
    # authentication is the only kind offered, so its absence is reported
    # rather than hung on -- which is also what pushes people toward keys.
    w = ws.Workspace(host="box", user="me", wdir="/w", ssh_key="/k")
    assert "BatchMode=yes" in w.ssh_argv("ls")
    assert "BatchMode=yes" in w.login_argv("ls")
    assert "BatchMode=yes" in w.scp_to_argv(["a"], "/d")
    assert "BatchMode=yes" in w.scp_from_argv("/d/a", ".")
    assert "BatchMode=yes" in w.git_ssh_command
    # Setting a machine up is the exception: ssh-copy-id needs a password
    # once to install the key that makes it unnecessary, and verifying a
    # host's fingerprint needs its prompt
    assert "BatchMode=yes" not in w.ssh_options


def test_ensure_reachable_asks_who_to_log_in_as(monkeypatch):
    # A login user is only ever needed at this moment -- to install the key
    # that makes it unnecessary -- so asking here is what lets a project
    # leave 'user' out entirely
    w = ws.Workspace(host="box", wdir="/w")
    attempts = []

    def unreachable_then_fine(ws_):
        attempts.append(ws_)
        if len(attempts) == 1:
            raise ws.ConnectionProblem("not authorized")

    monkeypatch.setattr(ws, "check_connection", unreachable_then_fine)
    monkeypatch.setattr(ws, "_existing_key", lambda: "/tmp/k")
    real_isfile = os.path.isfile
    monkeypatch.setattr(
        os.path, "isfile", lambda p: p == "/tmp/k" or real_isfile(p)
    )
    monkeypatch.setattr(ws, "ssh_login_user", lambda host: "pete")
    answers = iter(["parallels", "y", "y"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    ran = []
    monkeypatch.setattr(ws, "_run", lambda argv, **kw: ran.append(argv))
    result = ws.ensure_reachable(w, interactive=True)
    # The answer is used to authorize, and comes back on the workspace
    copy = [a for a in ran if a[0] == "ssh-copy-id"]
    assert copy and "parallels@box" in copy[0]
    assert result.user == "parallels"
    # And it's offered to ~/.ssh/config, where plain ssh reads it too, so
    # it never has to be asked again or carried in the project
    config = os.path.join(os.environ["HOME"], ".ssh", "config")
    with open(config) as f:
        written = f.read()
    assert "Host box" in written and "User parallels" in written
    # Someone's private config: readable only by them
    assert oct(os.stat(config).st_mode)[-3:] == "600"


def test_declining_still_says_who_to_authorize_as(monkeypatch):
    # The suggested command has to carry the user we just learned, or it
    # leaves the reader to work out what was missing
    w = ws.Workspace(host="box", wdir="/w")
    monkeypatch.setattr(
        ws,
        "check_connection",
        lambda ws_: (_ for _ in ()).throw(ws.ConnectionProblem("nope")),
    )
    monkeypatch.setattr(ws, "_existing_key", lambda: "/tmp/k")
    real_isfile = os.path.isfile
    monkeypatch.setattr(
        os.path, "isfile", lambda p: p == "/tmp/k" or real_isfile(p)
    )
    monkeypatch.setattr(ws, "ssh_login_user", lambda host: None)
    answers = iter(["parallels", "n", "n"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    monkeypatch.setattr(ws, "_run", lambda argv, **kw: None)
    with pytest.raises(ws.ConnectionProblem) as excinfo:
        ws.ensure_reachable(w, interactive=True)
    assert "ssh-copy-id -i /tmp/k parallels@box" in str(excinfo.value)


def test_tests_cannot_reach_the_real_home():
    # The guard above is load-bearing: this module writes SSH keys and
    # ~/.ssh/config entries, and reaching a real one damages a machine
    home = os.environ["HOME"]
    assert "pytest" in home, f"HOME is not isolated: {home}"
    assert os.path.expanduser("~") == home
