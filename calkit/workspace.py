"""Workspaces: a project's checkout on a machine that isn't this one.

A ``system`` environment whose host isn't this machine runs its stages in a
*workspace* -- a clone of the project living at the environment's ``wdir``
on that host. Getting the project's current state there is the problem this
module solves.

Nothing here is specific to SSH, or to a host at all. A workspace is
wherever a stage runs when that somewhere isn't this working tree, so a
scheduler's scratch directory or a pod's volume is the same problem with a
different way of reaching it. Keeping the transfer described purely as
"which commit, which cache objects" is what lets the reaching part vary.

The state that has to move is whatever the stage would see locally, which
includes uncommitted work: people iterate on a script and run it before
committing, and a transfer that only carried committed state would silently
run something other than what they are looking at. So the tree is captured
as a Git commit object and pushed to the workspace, where it is checked out
detached.

Two things make that safe to do repeatedly, both of which come from never
creating a branch:

Collisions
    A snapshot is named by its own commit hash, under one reserved
    namespace, so two transfers can only land on the same ref when they
    carry byte-identical content. Nothing is keyed by branch name, so
    branches that share a name across clones (or ``feature`` alongside
    ``feature/x``, which cannot both exist as ref paths) never meet. The
    workspace checks out the commit detached, so no branch is created there
    either, and a workspace shared by several people or several clones of
    one project stays consistent.

Cleanup
    Everything lives under ``refs/calkit/snapshots/``, so forgetting a
    transfer is one namespace to delete rather than a set of branch names
    to recognize. ``prune_snapshots`` does that, keeping whatever the
    workspace currently has checked out so a running stage is never pulled
    out from under itself.

Snapshots are also deterministic: the same tree at the same commit produces
the same hash, so a pipeline of ten stages sharing one working tree
transfers once and reuses a single ref, rather than leaving ten behind.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import posixpath
import re
import shlex
import socket
import subprocess
import tempfile
import time
import warnings
from dataclasses import dataclass, replace

import git

import calkit
import calkit.git

# Everything this module writes lives here, so cleanup is one namespace.
# Deliberately not under refs/heads or refs/tags: these are not branches
# and should not appear as such, be fetched by default, or be pushed by a
# plain ``git push``.
SNAPSHOT_REF_NS = "refs/calkit/snapshots"

# A snapshot commit is identified by its content, so everything about it
# except the tree and parent is fixed. Real identity and timestamps would
# make an unchanged tree hash differently on every transfer, which is what
# fills a workspace up with refs.
_SNAPSHOT_NAME = "Calkit"
_SNAPSHOT_EMAIL = "noreply@calkit.io"
_SNAPSHOT_DATE = "1970-01-01T00:00:00+0000"
_SNAPSHOT_MESSAGE = "Calkit workspace snapshot"


def snapshot_ref(sha: str) -> str:
    """The ref a snapshot commit is pushed to."""
    return f"{SNAPSHOT_REF_NS}/{sha}"


def sha_from_snapshot_ref(ref: str) -> str | None:
    """The commit a snapshot ref names, or None if it isn't one."""
    prefix = SNAPSHOT_REF_NS + "/"
    if not ref.startswith(prefix):
        return None
    return ref[len(prefix) :] or None


def create_snapshot(repo: git.Repo | None = None) -> str:
    """Capture the working tree as a commit and return its hash.

    Includes uncommitted changes and files that aren't tracked yet, since
    those are part of what the user is asking to run. Ignored files are
    left out, which is what keeps DVC-tracked data from being dragged in as
    Git blobs -- that data moves through the DVC cache instead.

    The user's index and branch are untouched: the tree is assembled in a
    scratch index, and the resulting commit is left unreferenced for the
    caller to push. Nothing here writes to the repository's refs.
    """
    if repo is None:
        repo = calkit.git.get_repo()
    head_sha = None
    if repo.head.is_valid():
        head_sha = repo.head.commit.hexsha
    # A scratch index so staging for the snapshot doesn't disturb whatever
    # the user has staged for their next commit
    with tempfile.TemporaryDirectory() as tmpdir:
        index_path = os.path.join(tmpdir, "index")
        with repo.git.custom_environment(GIT_INDEX_FILE=index_path):
            if head_sha is not None:
                repo.git.read_tree(head_sha)
            # Picks up modifications, additions, and deletions, while
            # honoring .gitignore
            repo.git.add("--all")
            tree_sha = repo.git.write_tree()
        # The parent is what makes this cheap to push: the workspace
        # already has the project's history, so only the objects that
        # actually differ go over the wire.
        args = [tree_sha]
        if head_sha is not None:
            args += ["-p", head_sha]
        with repo.git.custom_environment(
            GIT_AUTHOR_NAME=_SNAPSHOT_NAME,
            GIT_AUTHOR_EMAIL=_SNAPSHOT_EMAIL,
            GIT_AUTHOR_DATE=_SNAPSHOT_DATE,
            GIT_COMMITTER_NAME=_SNAPSHOT_NAME,
            GIT_COMMITTER_EMAIL=_SNAPSHOT_EMAIL,
            GIT_COMMITTER_DATE=_SNAPSHOT_DATE,
        ):
            return repo.git.commit_tree(*args, "-m", _SNAPSHOT_MESSAGE)


def dep_md5s(paths: list[str]) -> dict[str, str]:
    """Hash a job's dependencies, the way scheduler jobs already do.

    Recorded when a job is dispatched and compared when it finishes, to
    confirm its outputs came from what is here now. Narrower than comparing
    the whole tree on purpose: what matters is the stage's dependencies,
    since those are what DVC hashes into ``dvc.lock``. Editing a comment in
    an unrelated file while a long job runs should not throw the job away.
    """
    md5s = {}
    for path in paths:
        if os.path.exists(path):
            md5s[path] = calkit.get_md5(path)
    return md5s


def changed_deps(before: dict[str, str], paths: list[str]) -> list[str]:
    """Which dependencies no longer hash to what they did at dispatch."""
    now = dep_md5s(paths)
    changed = [p for p, md5 in now.items() if before.get(p) != md5]
    # A dependency that has since been deleted also means what ran is no
    # longer what is here
    changed += [p for p in before if p not in now]
    return sorted(set(changed))


def working_tree_matches(sha: str, repo: git.Repo | None = None) -> bool:
    """Whether the working tree still hashes to the snapshot ``sha``.

    Worth checking after a remote stage finishes and before its result is
    recorded. DVC hashes a stage's dependencies from the local files, so if
    the tree moved on while the stage was running elsewhere, ``dvc.lock``
    would pair inputs that were never used with outputs they never
    produced. That record then reads as up to date forever, which is worse
    than the stage simply being stale: a stale stage reruns, while a lock
    file that lies about what produced what does not announce itself.

    Comparing hashes turns that into something the caller can refuse.
    """
    return create_snapshot(repo=repo) == sha


def list_snapshots(repo: git.Repo | None = None) -> list[str]:
    """The snapshot commits this repo is currently holding refs for."""
    if repo is None:
        repo = calkit.git.get_repo()
    out = repo.git.for_each_ref(SNAPSHOT_REF_NS, format="%(refname)")
    shas = []
    for line in out.splitlines():
        sha = sha_from_snapshot_ref(line.strip())
        if sha is not None:
            shas.append(sha)
    return shas


def prune_snapshots(
    repo: git.Repo | None = None,
    keep: list[str] | None = None,
) -> list[str]:
    """Delete snapshot refs, returning the commits that were forgotten.

    Whatever the repo currently has checked out is kept even when it isn't
    named in ``keep``: in a workspace that is the commit a stage may still
    be running against, and dropping its last ref would leave the checkout
    liable to be garbage collected out from under it.

    Only refs are removed. The objects themselves go on the next ``git gc``,
    which is left to the caller so that pruning stays cheap and safe to run
    while other work is in flight.
    """
    if repo is None:
        repo = calkit.git.get_repo()
    keep_set = set(keep or [])
    if repo.head.is_valid():
        keep_set.add(repo.head.commit.hexsha)
    pruned = []
    for sha in list_snapshots(repo=repo):
        if sha in keep_set:
            continue
        repo.git.update_ref("-d", snapshot_ref(sha))
        pruned.append(sha)
    return pruned


# Workspaces live somewhere tool-managed rather than somewhere a person
# would think to work. Transfers check out with --force, so a directory
# that looks like the user's own checkout is a directory whose edits we
# would silently destroy.
WORKSPACES_DIR = posixpath.join(".calkit", "workspaces")
# Projects with no hub set belong to calkit.io, per ProjectInfo.hub
DEFAULT_HUB = "calkit.io"
# A project that was never shared still needs somewhere to go
LOCAL_OWNER = "_local"


def _path_segment(value: str) -> str:
    """Make a value safe to use as one path component.

    A hub, owner, or project name reaches us from a config file, so it is
    not automatically a well-behaved directory name. Anything that could
    climb out of the workspaces directory or confuse a shell is replaced
    rather than escaped, since these only have to be stable and readable.
    """
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return cleaned or "unknown"


def default_wdir(ck_info: dict) -> str:
    """Where a project's workspace goes on a host, if it doesn't say.

    Qualified by hub and owner as well as name, because a host is shared:
    two projects called ``example-ssh`` from different owners are different
    projects and must not land on the same checkout.

    Relative, so it resolves against the connecting user's home.
    """
    name = ck_info.get("name")
    if not name:
        raise ValueError("the project has no name to derive one from")
    hub = ck_info.get("hub") or DEFAULT_HUB
    # Accept a hub written with a scheme, which the field allows
    hub = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", hub).strip("/")
    owner = ck_info.get("owner") or LOCAL_OWNER
    return posixpath.join(
        WORKSPACES_DIR,
        _path_segment(hub or DEFAULT_HUB),
        _path_segment(owner),
        _path_segment(name),
    )


@dataclass
class Workspace:
    """A project checkout on another machine, reached over SSH.

    Everything here builds commands rather than running them, so what gets
    executed can be asserted in a test without a second machine to talk to.
    """

    host: str
    wdir: str
    user: str | None = None
    ssh_key: str | None = None
    # What the far end has to report as its own ID, if the env declared one
    machine_id: str | None = None

    @classmethod
    def from_env(
        cls,
        env: dict,
        env_name: str,
        ck_info: dict | None = None,
    ) -> Workspace:
        """Build a workspace from a ``system`` environment definition.

        Only the host has to be declared. The user is left to SSH, which
        already resolves it from ``~/.ssh/config`` or the current account,
        and repeating it in the project would just be a second place for it
        to be wrong. The directory defaults to a tool-managed path under
        the connecting user's home (see ``default_wdir``), which is the
        same path a project would otherwise spell out on every machine it
        runs on.
        """
        host = os.path.expandvars(env.get("host") or "")
        if not host:
            raise ValueError(
                f"System environment '{env_name}' has no host to connect to"
            )
        user = os.path.expandvars(env.get("user") or "") or None
        wdir = env.get("wdir") or ""
        if not wdir:
            try:
                wdir = default_wdir(ck_info or {})
            except ValueError as e:
                raise ValueError(
                    f"System environment '{env_name}' runs on host "
                    f"'{host}', which this is not, so it needs a 'wdir' "
                    f"workspace to run in: {e}"
                )
        ssh_key = env.get("ssh_key")
        if ssh_key is not None:
            ssh_key = os.path.expanduser(os.path.expandvars(ssh_key))
        machine_id = os.path.expandvars(env.get("machine_id") or "") or None
        return cls(
            host=host,
            user=user,
            wdir=wdir,
            ssh_key=ssh_key,
            machine_id=machine_id,
        )

    @property
    def target(self) -> str:
        """What to hand SSH: a bare host unless a user was declared."""
        return f"{self.user}@{self.host}" if self.user else self.host

    @property
    def url_host(self) -> str:
        """The host as it has to appear inside a URL.

        A bare IPv6 literal is full of colons, which is what separates a
        host from a port, so a URL has to bracket it. Names and IPv4
        addresses are already unambiguous and are left alone.
        """
        try:
            if ipaddress.ip_address(self.host).version == 6:
                return f"[{self.host}]"
        except ValueError:
            pass
        return self.host

    @property
    def scp_target(self) -> str:
        """The host as scp needs it, bracketing an IPv6 literal too."""
        user = f"{self.user}@" if self.user else ""
        return f"{user}{self.url_host}"

    @property
    def git_url(self) -> str:
        """The workspace as a Git remote.

        Pushing straight to the workspace keeps snapshots off whatever
        remote the project is hosted on, which matters both because a
        cluster often can't reach it and because WIP snapshots have no
        business in a shared history.
        """
        user = f"{self.user}@" if self.user else ""
        return f"ssh://{user}{self.url_host}/{self.wdir.lstrip('/')}"

    @property
    def ssh_options(self) -> list[str]:
        return ["-i", self.ssh_key] if self.ssh_key else []

    @property
    def batch_options(self) -> list[str]:
        """SSH options for anything that runs unattended.

        ``BatchMode`` is the difference between failing and hanging. Every
        transfer and remote command here may run in the middle of a
        pipeline, where a password prompt has nobody to answer it and no
        way to be seen -- so key authentication is the only kind offered,
        and its absence is reported rather than waited on.

        Deliberately not used for setting a machine up: ``ssh-copy-id``
        needs a password once to install the key that makes it
        unnecessary, and verifying a host's fingerprint needs its prompt.
        """
        return self.ssh_options + ["-o", "BatchMode=yes"]

    @property
    def git_ssh_command(self) -> str:
        """What Git should use as its transport, honoring the env's key."""
        return " ".join(["ssh"] + [shlex.quote(o) for o in self.batch_options])

    def ssh_argv(self, remote_command: str) -> list[str]:
        return ["ssh"] + self.batch_options + [self.target, remote_command]

    def login_argv(self, remote_command: str) -> list[str]:
        """Run a command the way logging in to the host would.

        ``ssh host cmd`` gets a shell that is neither a login shell nor an
        interactive one, so on most systems nothing sources the profile
        that puts ``~/.local/bin`` on PATH. A Calkit installed there --
        which is where its own installer puts it -- is then invisible, and
        so is anything else the machine's setup provides. Asking for a
        login shell is what makes "it works when I log in" also true here.
        """
        return self.ssh_argv(f"bash -lc {shlex.quote(remote_command)}")

    def path(self, *parts: str) -> str:
        return posixpath.join(self.wdir, *parts)

    def scp_to_argv(self, srcs: list[str], dest: str) -> list[str]:
        return (
            ["scp", "-r"]
            + self.batch_options
            + srcs
            + [f"{self.scp_target}:{dest}"]
        )

    def scp_from_argv(self, src: str, dest: str) -> list[str]:
        return (
            ["scp", "-r"]
            + self.batch_options
            + [f"{self.scp_target}:{src}", dest]
        )


def _run(argv: list[str], verbose: bool = False) -> None:
    if verbose:
        print(f"Running: {argv}")
    subprocess.check_call(argv)


def ensure_workspace(workspace: Workspace, verbose: bool = False) -> None:
    """Make sure the workspace exists and is a repository.

    A snapshot is delivered by pushing to the workspace, and there is
    nothing to push into until one is there. Created empty rather than
    cloned from wherever the project is hosted, since a cluster often
    cannot reach that, and the snapshot carries the history anyway.

    Idempotent: an existing workspace is left exactly as it is.
    """
    _run(
        workspace.ssh_argv(
            f"mkdir -p {shlex.quote(workspace.wdir)} && "
            f"cd {shlex.quote(workspace.wdir)} && "
            "if [ ! -d .git ]; then git init -q . ; fi"
        ),
        verbose=verbose,
    )


def send_snapshot(
    workspace: Workspace,
    sha: str,
    repo: git.Repo | None = None,
    verbose: bool = False,
) -> None:
    """Put the workspace on ``sha``, pushing it there if it's missing.

    The checkout is forced because a workspace is derived state: whatever
    it holds came from a previous transfer, and the local tree is the only
    thing that decides what a stage should see. Ignored files, which is
    where DVC keeps its data and cache, are left alone by this.
    """
    if repo is None:
        repo = calkit.git.get_repo()
    ref = snapshot_ref(sha)
    with repo.git.custom_environment(
        GIT_SSH_COMMAND=workspace.git_ssh_command
    ):
        repo.git.push(workspace.git_url, f"{sha}:{ref}")
    _run(
        workspace.ssh_argv(
            f"cd {shlex.quote(workspace.wdir)} && "
            f"git checkout --force --detach {shlex.quote(sha)}"
        ),
        verbose=verbose,
    )


def paths_to_transfer(
    paths: list[str], repo: git.Repo | None = None
) -> list[str]:
    """Which of ``paths`` the snapshot doesn't already carry.

    Git-tracked files ride along in the snapshot, so re-sending them would
    be wasted transfer. What's left is the ignored ones, which is where
    DVC-tracked data lives.
    """
    if not paths:
        return []
    if repo is None:
        repo = calkit.git.get_repo()
    existing = [p for p in paths if os.path.exists(p)]
    if not existing:
        return []
    # check-ignore exits 1 when nothing matches, which is not an error here
    try:
        out = repo.git.check_ignore(*existing)
    except git.exc.GitCommandError:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def send_paths(
    workspace: Workspace,
    paths: list[str],
    verbose: bool = False,
) -> None:
    """Copy paths into the workspace, keeping their layout."""
    for path in paths:
        if not os.path.exists(path):
            continue
        dest_dir = posixpath.dirname(path.replace(os.sep, "/"))
        dest = workspace.path(dest_dir) if dest_dir else workspace.wdir
        _run(
            workspace.ssh_argv(f"mkdir -p {shlex.quote(dest)}"),
            verbose=verbose,
        )
        _run(workspace.scp_to_argv([path], dest), verbose=verbose)


def fetch_paths(
    workspace: Workspace,
    paths: list[str],
    verbose: bool = False,
) -> None:
    """Copy paths back out of the workspace, keeping their layout."""
    for path in paths:
        local_dir = os.path.dirname(path)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)
        _run(
            workspace.scp_from_argv(
                workspace.path(path.replace(os.sep, "/")),
                local_dir or ".",
            ),
            verbose=verbose,
        )


def prune_command(wdir: str) -> str:
    """The shell command that forgets a workspace's stale snapshot refs.

    Split out from the SSH call so the shell can be exercised directly,
    since a quoting mistake here would either delete nothing or delete the
    ref a running stage is holding.
    """
    return (
        f"cd {shlex.quote(wdir)} && "
        "head=$(git rev-parse HEAD) && "
        "git for-each-ref --format='%(refname) %(objectname)' "
        f"{SNAPSHOT_REF_NS} | "
        "while read ref obj; do "
        'if [ "$obj" != "$head" ]; then git update-ref -d "$ref"; fi; '
        "done"
    )


def prune_remote_snapshots(
    workspace: Workspace,
    verbose: bool = False,
) -> None:
    """Forget snapshot refs in the workspace, except what it's sitting on.

    Run after a transfer so refs don't pile up. This is why the namespace
    is reserved: one pattern deletes everything Calkit put there, with no
    risk of catching a branch someone cares about.
    """
    _run(workspace.ssh_argv(prune_command(workspace.wdir)), verbose=verbose)


def resolve_wdir(workspace: Workspace, verbose: bool = False) -> Workspace:
    """Return a workspace whose ``wdir`` is absolute on the far end.

    A workspace directory is written relative to the connecting user's home
    (that's the default), but ``~`` and relative paths mean nothing to the
    commands built here: an ``ssh://`` URL takes an absolute path, and a
    ``cd`` would otherwise depend on wherever the login shell happens to
    start. Asking the host once and carrying the answer keeps every later
    command unambiguous.
    """
    if workspace.wdir.startswith("/"):
        return workspace
    home = (
        subprocess.check_output(workspace.ssh_argv("echo $HOME"))
        .decode()
        .strip()
    )
    if not home:
        raise ValueError(
            f"Could not determine the home directory on '{workspace.host}', "
            "so there is nowhere to put the workspace; set an absolute "
            "'wdir'"
        )
    rel = workspace.wdir
    if rel.startswith("~/"):
        rel = rel[2:]
    elif rel == "~":
        rel = ""
    resolved = posixpath.join(home, rel) if rel else home
    if verbose:
        print(f"Workspace resolved to {resolved}")
    return replace(workspace, wdir=resolved)


class ConnectionProblem(ValueError):
    """A host that can't be reached, with what to do about it."""


class HostKeyUnknown(ConnectionProblem):
    """SSH has never seen this host, so it won't connect to it yet."""


class HostKeyChanged(ConnectionProblem):
    """The host is not presenting the key SSH recorded for it.

    Kept separate from every other failure and never remedied
    automatically: this is what a machine-in-the-middle looks like, and it
    is also what a rebuilt VM looks like. Only the person running it can
    tell those apart.
    """


def _authorize_hint(workspace: Workspace) -> str:
    """How to authorize this machine, spelled out for the user to run.

    Built from the workspace rather than fixed at the point of failure, so
    a user learned during setup shows up in the command we suggest instead
    of leaving them to work out that it was missing.
    """
    # ssh-copy-id takes the key with -i; ssh-add takes it positionally
    copy_id_key = f" -i {workspace.ssh_key}" if workspace.ssh_key else ""
    add_key = f" {workspace.ssh_key}" if workspace.ssh_key else ""
    return (
        f"Could not connect to '{workspace.host}' without being prompted. "
        "Check the host is reachable, then authorize this machine with:"
        f"\n\n    ssh-copy-id{copy_id_key} {workspace.target}"
        "\n\nIf the key has a passphrase, add it to your agent with "
        f"'ssh-add{add_key}' so commands can run unattended."
    )


def check_connection(workspace: Workspace) -> None:
    """Verify the host can be reached without a prompt.

    ``BatchMode`` is what makes this a check rather than a hang: without it
    SSH would sit waiting for a password or passphrase, which is exactly the
    state a project wants to be told about while it is checking
    environments rather than halfway through a pipeline.

    SSH refuses for more than one reason and the fixes are different, so
    the reason is read back out rather than reporting every failure as an
    unauthorized key.
    """
    argv = (
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        + workspace.ssh_options
        + [workspace.target, "true"]
    )
    try:
        subprocess.run(
            argv,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        return
    except FileNotFoundError:
        raise ConnectionProblem(
            "Could not run 'ssh'; it has to be installed to reach "
            f"'{workspace.host}'"
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode(errors="replace")
    if "REMOTE HOST IDENTIFICATION HAS CHANGED" in stderr:
        raise HostKeyChanged(
            f"The key '{workspace.host}' is presenting is not the one SSH "
            "recorded for it. If you rebuilt or replaced that machine this "
            "is expected, and you can drop the old entry with:\n\n"
            f"    ssh-keygen -R {workspace.host}\n\n"
            "If you did not, stop: something is answering in its place."
        )
    if "Host key verification failed" in stderr or "key is known" in stderr:
        raise HostKeyUnknown(
            f"SSH has not seen '{workspace.host}' before, so it will not "
            "connect yet. Verify the fingerprint it offers, which means "
            "connecting once by hand:\n\n"
            f"    ssh {workspace.target}\n\n"
            "Answering 'yes' records it, and later connections are checked "
            "against it."
        )
    raise ConnectionProblem(_authorize_hint(workspace))


def remote_system_info(workspace: Workspace) -> dict:
    """Read the far end's machine properties.

    A ``system`` env's lock describes the machine the results depend on,
    which is that host and not this one, so the properties have to be read
    where the stage actually runs. Calkit is already required there to
    activate any inner environment, so it can report them itself rather
    than needing a second, shell-based way to ask the same questions.
    """
    try:
        out = subprocess.check_output(
            workspace.login_argv("calkit describe system --json")
        ).decode()
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise ValueError(
            f"Could not read machine properties from '{workspace.host}'. "
            "Locking them requires Calkit on that machine; install it "
            "there, or remove 'lock' from the environment."
        )
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        pass
    # A login shell is what makes Calkit findable at all here, and logging
    # in is also what prints a MOTD or whatever else the profile echoes.
    # The description is one JSON object, so take it from where it starts.
    start = out.find("{")
    if start != -1:
        try:
            return json.loads(out[start:])
        except json.JSONDecodeError:
            pass
    raise ValueError(
        f"Got an unreadable system description from '{workspace.host}'"
    )


class MachineMismatch(ConnectionProblem):
    """The host answered, but it isn't the machine the project named.

    Separate from being unable to connect because the fix is different and
    the situation is worse: something is reachable and would have run the
    stage. A name that has come to point somewhere else is the ordinary
    cause, and re-pointing it is invisible from here -- which is the whole
    reason an environment can name a machine by ID instead.
    """


def verify_machine_id(workspace: Workspace, system_info: dict) -> None:
    """Check the far end is the machine the environment named.

    Only meaningful once we've connected, since asking the machine who it
    is means asking the machine. A host that stops resolving to the box it
    used to is otherwise silent: SSH connects, the workspace syncs, and the
    stage runs somewhere the project never named.

    A machine that can't report an ID is not treated as a mismatch. It is
    the same "unknown is not different" rule as locally, and here it also
    covers an older Calkit on the far end that doesn't report the field at
    all -- which is a reason to say nothing can be verified, not a reason
    to claim the machine is the wrong one.
    """
    if not workspace.machine_id:
        return
    reported = system_info.get("machine_id")
    if reported is None:
        warnings.warn(
            f"'{workspace.host}' did not report a machine ID, so it could "
            "not be verified as the machine this environment names. Calkit "
            "there may predate machine IDs."
        )
        return
    if calkit.machine_ids_match(workspace.machine_id, reported):
        return
    raise MachineMismatch(
        f"'{workspace.host}' is not the machine this environment names. "
        f"It expects machine ID '{workspace.machine_id}', but that host "
        f"reports '{reported}'. If the name now points at a different "
        "machine, correct 'host'; if the machine itself was rebuilt or "
        "replaced, update 'machine_id' to the new value it reports."
    )


def requirements_need_system_info(requirements: list) -> bool:
    """Whether checking these requires reading the machine's properties.

    Reading them means Calkit has to be installed on the far end, which is
    a real thing to ask of a host, so it's only asked for when something
    actually needs an answer from there.
    """
    from calkit.core import _normalize_requirement

    prop_kinds = calkit.system_property_requirement_kinds()
    for raw in requirements:
        req = _normalize_requirement(raw)
        if req["kind"] in prop_kinds:
            return True
        if req["kind"] == "app" and req.get("version_spec"):
            return True
    return False


def check_requirements(
    workspace: Workspace,
    requirements: list,
    system_info: dict | None = None,
    verbose: bool = False,
) -> None:
    """Check a ``system`` environment's requirements on the host it names.

    What a stage needs is what the machine it runs on has, so the questions
    are asked there rather than here: an app is looked for on that host's
    PATH, a variable is read from the shell a login gets there, and a setup
    step's check command runs there. Machine properties come from the
    description that host gives of itself.

    Nothing is offered as a fix. Installing something or answering a prompt
    belongs to whoever administers that machine, and the useful thing to do
    from here is say precisely what was missing and where.
    """
    from calkit.core import _normalize_requirement

    reqs = [_normalize_requirement(raw) for raw in requirements]
    if not reqs:
        return
    described_as = f"host '{workspace.host}'"
    prop_kinds = calkit.system_property_requirement_kinds()
    properties = [req for req in reqs if req["kind"] in prop_kinds]
    if properties or any(
        req["kind"] == "app" and req.get("version_spec") for req in reqs
    ):
        if system_info is None:
            system_info = remote_system_info(workspace)
    for req in properties:
        calkit.check_property_requirement(
            req, system_info or {}, described_as=described_as
        )
    for req in reqs:
        kind = req["kind"]
        name = req["name"]
        if kind in prop_kinds:
            continue
        elif kind == "env-var":
            # Quoted so the remote shell expands the variable rather than
            # this one, and ``:-`` so an unset variable isn't an error
            # under a profile that runs with 'set -u'.
            cmd = f'test -n "${{{name}:-}}"'
            if _remote_rc(workspace, cmd, verbose=verbose) != 0:
                raise ValueError(
                    f"env-var '{name}' is not set on {described_as}. Set it "
                    "in that machine's shell profile, since a stage running "
                    "there reads its environment, not this one's."
                )
        elif kind == "app":
            cmd = f"command -v {shlex.quote(name)}"
            if _remote_rc(workspace, cmd, verbose=verbose) != 0:
                raise ValueError(
                    f"app '{name}' was not found on {described_as}"
                )
            spec = req.get("version_spec")
            if spec:
                calkit.check_app_version(
                    name,
                    spec,
                    system_info=system_info or {},
                    described_as=described_as,
                    probe_locally=False,
                )
        elif kind == "setup":
            check_command = req.get("check_command")
            if not check_command:
                raise ValueError(
                    f"setup requirement '{name}' must declare 'check_command'"
                )
            if _remote_rc(workspace, check_command, verbose=verbose) != 0:
                setup_command = req.get("setup_command")
                msg = (
                    f"setup requirement '{name}' is not satisfied on "
                    f"{described_as}"
                )
                if setup_command:
                    msg += f". To satisfy it there, run: {setup_command}"
                raise ValueError(msg)
        else:
            raise ValueError(
                f"Requirement kind '{kind}' can't be checked on another "
                f"machine ({described_as})"
            )


def _remote_rc(
    workspace: Workspace, command: str, verbose: bool = False
) -> int:
    """Run a command on the far end and return its exit code."""
    argv = workspace.login_argv(command)
    if verbose:
        print(f"Running: {argv}")
    return subprocess.run(argv, capture_output=not verbose).returncode


def _referenced_env_vars(value: str) -> list[str]:
    """The environment variables a config value refers to."""
    return [
        name
        for match in re.finditer(r"\$\{(\w+)\}|\$(\w+)", value)
        for name in [match.group(1) or match.group(2)]
    ]


# The fields that say how to reach a machine, and so the ones worth
# resolving before anything tries to connect. Kept as a list rather than
# expanding every string in the environment so that a description
# mentioning a dollar sign never turns into a prompt.
CONNECTION_FIELDS = ["host", "user", "ssh_key", "wdir"]


def expand_with_prompts(
    value: str,
    interactive: bool,
    described_as: str,
) -> str:
    """Expand a config value, asking for anything the environment lacks.

    A project shares its ``calkit.yaml`` but not its ``.env``, so a host or
    a key path written as ``${CK_SSH_HOST}`` is exactly the sort of thing
    that is missing the first time someone else runs the project. Asking
    beats expanding to the literal ``${CK_SSH_HOST}`` and then failing
    against a host by that name. Answers are stored in ``.env`` so the
    question is only asked once.
    """
    from calkit.dependencies import prompt_and_store_env_var

    for name in _referenced_env_vars(value):
        if os.environ.get(name):
            continue
        if not interactive:
            raise ValueError(
                f"Environment variable '{name}' is not set, and it is what "
                f"{described_as} refers to. Set it, e.g. with "
                f"'calkit set-env-var {name} <value>'."
            )
        print(f"'{name}' is not set, and it is what {described_as} refers to")
        if prompt_and_store_env_var(name) is None:
            raise ValueError(f"No value given for '{name}'")
    return os.path.expandvars(value)


def _confirm(question: str) -> bool:
    try:
        return input(f"{question} [y/N]: ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


DEFAULT_SSH_KEY_PATH = "~/.ssh/id_ed25519"
# Keys SSH would offer on its own, so we only generate one when the user
# has nothing at all to authorize with.
_CANDIDATE_KEY_PATHS = [
    "~/.ssh/id_ed25519",
    "~/.ssh/id_ecdsa",
    "~/.ssh/id_rsa",
]


def _existing_key() -> str | None:
    for path in _CANDIDATE_KEY_PATHS:
        expanded = os.path.expanduser(path)
        if os.path.isfile(expanded):
            return expanded
    return None


SSH_CONFIG_PATH = "~/.ssh/config"


def ssh_login_user(host: str) -> str | None:
    """Who SSH would log in to ``host`` as, given its own configuration.

    Asking SSH rather than guessing means an existing ``~/.ssh/config``
    entry is honored, and that the default we offer is the one the user
    would get by typing ``ssh <host>`` themselves.
    """
    try:
        out = subprocess.check_output(
            ["ssh", "-G", host], stderr=subprocess.DEVNULL
        ).decode()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    for line in out.splitlines():
        if line.startswith("user "):
            return line.split(None, 1)[1].strip() or None
    return None


def ssh_config_has_host(host: str) -> bool:
    """Whether ``~/.ssh/config`` already has a Host block for this host."""
    path = os.path.expanduser(SSH_CONFIG_PATH)
    if not os.path.isfile(path):
        return False
    try:
        with open(path) as f:
            content = f.read()
    except OSError:
        return False
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("host "):
            continue
        if host in stripped.split()[1:]:
            return True
    return False


def remember_ssh_user(host: str, user: str) -> str:
    """Record the login user for a host in ``~/.ssh/config``.

    This is where "which user for which host" belongs: plain ``ssh`` reads
    it too, so the project never has to carry a value that differs per
    person. Appended rather than merged, and only when there is no block
    for this host already, so an existing configuration is never rewritten.
    """
    path = os.path.expanduser(SSH_CONFIG_PATH)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    exists = os.path.isfile(path)
    with open(path, "a") as f:
        if exists and os.path.getsize(path):
            f.write("\n")
        f.write(f"# Added by Calkit\nHost {host}\n    User {user}\n")
    if not exists:
        os.chmod(path, 0o600)
    return path


def ensure_reachable(
    workspace: Workspace,
    interactive: bool,
    verbose: bool = False,
) -> Workspace:
    """Get to the point where the host answers without a prompt.

    Setting a machine up is a few steps that are easy to get subtly wrong
    by hand and easy to run for someone who is sitting there, so on a
    terminal we offer to do them. Nothing happens without being asked
    first: generating a key and authorizing this machine on a remote host
    both change state outside the project.

    Without a terminal this is only a check, and it fails with the commands
    to run, since a pipeline in CI has nobody to answer.

    Returns the workspace to use, which is not always the one passed in: a
    key created here belongs to it, and dropping that would leave the
    caller connecting without the key it just made.
    """
    unreachable: ValueError
    try:
        check_connection(workspace)
        return workspace
    except HostKeyChanged:
        # Never remedied here, interactive or not. Removing the recorded
        # key on the user's behalf is exactly the wrong move when the
        # reason it changed might not be a rebuilt machine.
        raise
    except ValueError as e:
        if not interactive:
            raise
        # Python clears the name at the end of the except block, so hold
        # on to it: this is what gets re-raised if any step is declined
        unreachable = e
    if isinstance(unreachable, HostKeyUnknown):
        print(f"SSH has not seen '{workspace.host}' before")
        if not _confirm("Connect once now to check its fingerprint?"):
            raise unreachable
        # Deliberately without BatchMode and without StrictHostKeyChecking
        # off: SSH prompts, shows the fingerprint, and the user decides.
        # Accepting it for them would throw away the check entirely.
        _run(
            ["ssh"] + workspace.ssh_options + [workspace.target, "true"],
            verbose=verbose,
        )
        try:
            check_connection(workspace)
            return workspace
        except ValueError as e:
            unreachable = e
    key = workspace.ssh_key or _existing_key()
    if key and workspace.ssh_key is None:
        # Once we know which key we're using, say so: it goes into the
        # command we suggest, and into every later connection
        workspace = replace(workspace, ssh_key=key)
    if key is None or not os.path.isfile(key):
        key = key or os.path.expanduser(DEFAULT_SSH_KEY_PATH)
        print(f"No SSH key found at {key}")
        if not _confirm("Create one?"):
            raise unreachable
        os.makedirs(os.path.dirname(key), exist_ok=True)
        # No passphrase, so stages can run unattended; that is the whole
        # point of a key dedicated to a machine you run pipelines on
        _run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                key,
                "-C",
                f"calkit-{workspace.host}",
            ],
            verbose=verbose,
        )
        workspace = replace(workspace, ssh_key=key)
    # ssh-copy-id has to log in to install the key, which needs a user.
    # Asking here is what makes declaring one in the project unnecessary:
    # it is only ever needed at this moment, and the answer belongs in
    # ~/.ssh/config, where plain ssh reads it too.
    if workspace.user is None:
        default = ssh_login_user(workspace.host)
        prompt = f"Log in to '{workspace.host}' as"
        prompt += f" [{default}]" if default else ""
        try:
            answer = input(f"{prompt}: ").strip() or default
        except EOFError:
            answer = None
        if not answer:
            raise unreachable
        workspace = replace(workspace, user=answer)
        if answer != default and not ssh_config_has_host(workspace.host):
            if _confirm(f"Remember that in {SSH_CONFIG_PATH}?"):
                written = remember_ssh_user(workspace.host, answer)
                print(
                    f"Added a Host entry for '{workspace.host}' to {written}"
                )
    print(f"This machine is not authorized on '{workspace.host}' yet")
    if not _confirm(
        f"Authorize it now with ssh-copy-id as {workspace.target}?"
    ):
        raise ConnectionProblem(_authorize_hint(workspace))
    _run(
        ["ssh-copy-id"] + (["-i", key] if key else []) + [workspace.target],
        verbose=verbose,
    )
    # Confirm it actually took, rather than trusting the copy
    check_connection(workspace)
    return workspace


CALKIT_INSTALL_CMD = "curl -LsSf install.calkit.org | sh"


def has_calkit(workspace: Workspace) -> bool:
    """Whether the host can run Calkit."""
    try:
        subprocess.check_call(
            workspace.login_argv("command -v calkit"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def ensure_calkit_installed(
    workspace: Workspace,
    interactive: bool,
    required: bool,
    verbose: bool = False,
) -> bool:
    """Make sure Calkit is on the host, offering to install it.

    Needed there to activate an inner environment and to report the
    machine's properties for a lock. ``required`` says whether this run
    actually depends on it, so an environment that only dispatches a
    command isn't blocked on a tool it never calls.
    """
    if has_calkit(workspace):
        return True
    message = f"Calkit is not installed on '{workspace.host}'"
    if not interactive:
        if not required:
            return False
        raise ValueError(
            f"{message}, and it is needed there. Install it with:\n\n"
            f"    ssh {workspace.target} '{CALKIT_INSTALL_CMD}'"
        )
    print(message)
    if not _confirm("Install it there now?"):
        if required:
            raise ValueError(
                f"{message}, and it is needed there. Install it with:\n\n"
                f"    ssh {workspace.target} '{CALKIT_INSTALL_CMD}'"
            )
        return False
    # Login shell so the installer's PATH changes are picked up the same
    # way they would be for someone typing this themselves
    _run(workspace.login_argv(CALKIT_INSTALL_CMD), verbose=verbose)
    if not has_calkit(workspace):
        raise ValueError(
            f"Calkit still isn't on PATH on '{workspace.host}' after "
            "installing; check the login shell's PATH there"
        )
    return True


class WorkspaceBusy(ValueError):
    """Another run is already using this workspace."""


def lock_path(wdir: str) -> str:
    """Where a workspace's lock lives: beside it, not inside it.

    Inside would put it in the checkout that transfers overwrite, and in
    the project whose files the stage reads.
    """
    return wdir.rstrip("/") + ".lock"


def status_file(wdir: str) -> str:
    """Where a job records its exit code, inside its own lock directory.

    The lock exists for exactly as long as the job does, including across
    a disconnect and a later resume, so a status written there is still
    readable when we come back for it and is cleaned up with the lock.
    """
    return posixpath.join(lock_path(wdir), "status")


def log_file(wdir: str) -> str:
    """Where a job's output is kept, alongside its exit status."""
    return posixpath.join(lock_path(wdir), "log")


LOG_TAIL_LINES = 40


def _log_tail(workspace: Workspace) -> str:
    """The end of a failed job's output, for the error that reports it.

    A job runs detached on the far side of a connection that has since
    closed, so its output is the only account of what went wrong. Printing
    the tail beats telling someone a status code and leaving them to go
    and find the rest themselves.
    """
    try:
        out = subprocess.check_output(
            workspace.ssh_argv(
                f"tail -n {LOG_TAIL_LINES} "
                f"{shlex.quote(log_file(workspace.wdir))} 2>/dev/null"
            ),
            stderr=subprocess.DEVNULL,
        ).decode(errors="replace")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    out = out.strip()
    if not out:
        return ""
    return f"\n\nWhat it printed:\n\n{out}"


def read_status(workspace: Workspace) -> int | None:
    """The exit code a finished job recorded, or None if it recorded none.

    None means the job stopped without saying how it went -- killed, or the
    machine went away -- which is not the same as success and must not be
    treated as it.
    """
    try:
        out = subprocess.check_output(
            workspace.ssh_argv(
                f"cat {shlex.quote(status_file(workspace.wdir))} 2>/dev/null"
            ),
            stderr=subprocess.DEVNULL,
        ).decode()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    for line in reversed(out.splitlines()):
        stripped = line.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def clear_outputs(
    workspace: Workspace, paths: list[str], verbose: bool = False
) -> None:
    """Remove a job's declared outputs from the workspace before it runs.

    A workspace is reused, so last run's outputs are still sitting there. A
    command that fails to write one would otherwise have the old file
    collected and recorded as though this run had produced it.
    """
    if not paths:
        return
    quoted = " ".join(
        shlex.quote(workspace.path(p.replace(os.sep, "/"))) for p in paths
    )
    _run(workspace.ssh_argv(f"rm -rf {quoted}"), verbose=verbose)


# Never collected back, however the workspace changed them. Local DVC
# writes dvc.lock itself from what it hashes here, and .dvc/config.local
# is per-machine by definition -- ours points at the workspace, theirs
# would point somewhere meaningless.
NOT_COLLECTED = ["dvc.lock", ".dvc/config.local"]


def produced_paths(workspace: Workspace) -> list[str]:
    """What the run produced, as the workspace's own Git sees it.

    Asked rather than declared. The workspace was checked out at the
    snapshot we sent, so anything modified or newly appeared since is the
    run's doing -- and .gitignore already filters out the noise a command
    leaves behind. This is why a stage's outputs no longer have to be
    repeated into the command that runs it.
    """
    remote_command = (
        f"cd {shlex.quote(workspace.wdir)} && "
        "git diff --name-only HEAD; "
        "git ls-files --others --exclude-standard"
    )
    try:
        out = subprocess.check_output(
            workspace.ssh_argv(remote_command), stderr=subprocess.DEVNULL
        ).decode()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    paths = []
    for line in out.splitlines():
        path = line.strip()
        if path and path not in NOT_COLLECTED and path not in paths:
            paths.append(path)
    return paths


def _stage_for_command(command: str, wdir: str | None = None) -> dict:
    """The compiled stage whose command this is, if it can be found."""
    import calkit.dvc

    wanted = command.strip()
    pipeline = calkit.dvc.read_pipeline(wdir or ".") or {}
    for stage in (pipeline.get("stages") or {}).values():
        if not isinstance(stage, dict):
            continue
        cmd = stage.get("cmd")
        if isinstance(cmd, str) and cmd.strip().endswith(wanted):
            return stage
    return {}


def outs_for_command(command: str, wdir: str | None = None) -> list[str]:
    """The outputs DVC records for the stage running this command.

    Needed because an output DVC caches is added to .gitignore, which makes
    it invisible to the workspace's own Git -- the very thing that finds
    everything else a run produced. Read from the compiled pipeline for the
    same reason the dependencies are: it is already written down there.
    """
    outs = []
    for out in _stage_for_command(command, wdir=wdir).get("outs") or []:
        if isinstance(out, str):
            outs.append(out)
        elif isinstance(out, dict) and out:
            outs.append(next(iter(out)))
    return outs


def remote_existing(workspace: Workspace, paths: list[str]) -> list[str]:
    """Which of ``paths`` are actually present in the workspace."""
    if not paths:
        return []
    tests = "; ".join(
        f"[ -e {shlex.quote(workspace.path(p))} ] && echo {shlex.quote(p)}"
        for p in paths
    )
    try:
        out = subprocess.check_output(
            workspace.ssh_argv(tests), stderr=subprocess.DEVNULL
        ).decode()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    found = {line.strip() for line in out.splitlines() if line.strip()}
    return [p for p in paths if p in found]


def deps_for_command(command: str, wdir: str | None = None) -> list[str]:
    """The dependencies DVC records for the stage running this command.

    Read from the compiled pipeline rather than passed in. They are already
    written down in dvc.yaml a few lines from the command itself, and a
    second copy threaded through that command is one that can disagree with
    the first.
    """
    stage = _stage_for_command(command, wdir=wdir)
    return [d for d in stage.get("deps") or [] if isinstance(d, str)]


def acquire_lock(
    workspace: Workspace,
    holder: str,
    info: str,
    verbose: bool = False,
) -> None:
    """Claim the workspace for this run, or say who already has it.

    A workspace is one checkout at one commit, so two runs sharing it would
    check out over each other and each would then be running against the
    other's code. Reusing the workspace is what keeps environments and the
    DVC cache warm, so the answer is to take turns rather than to stop
    reusing it.

    ``mkdir`` is the gate because it is atomic: two runs racing here cannot
    both succeed. Re-acquiring a lock this run already holds is fine, which
    is what lets a disconnected job be waited on again.
    """
    lock = lock_path(workspace.wdir)
    # The parent has to exist before the lock can be made inside it, and on
    # a first run none of it does. Only the lock directory itself needs to
    # be created atomically, so the path down to it is made first and the
    # race is left where it belongs.
    remote_command = (
        f"lock={shlex.quote(lock)}; "
        'mkdir -p "$(dirname "$lock")" || { echo NOPARENT; exit 0; }; '
        'if mkdir "$lock" 2>/dev/null; then '
        f"printf '%s' {shlex.quote(holder)} > \"$lock/holder\"; "
        f"printf '%s' {shlex.quote(info)} > \"$lock/info\"; "
        "echo ACQUIRED; "
        'elif [ -d "$lock" ]; then '
        'printf "HELD\\t"; cat "$lock/holder" 2>/dev/null; '
        'printf "\\t"; cat "$lock/info" 2>/dev/null; echo; '
        "else echo NOLOCK; fi"
    )
    out = subprocess.check_output(workspace.ssh_argv(remote_command)).decode()
    line = ""
    for candidate in out.splitlines():
        if candidate.startswith(("ACQUIRED", "HELD", "NOPARENT", "NOLOCK")):
            line = candidate
    # A directory we could not create is not a directory somebody else is
    # using, and saying so would send the reader looking for a run that
    # does not exist
    if line.startswith("NOPARENT"):
        raise ConnectionProblem(
            f"Could not create the workspace directory on '{workspace.host}' "
            f"for '{workspace.wdir}'. Check the path is writable."
        )
    if line.startswith("NOLOCK"):
        raise ConnectionProblem(
            f"Could not lock the workspace on '{workspace.host}' at "
            f"'{lock}', and nothing is holding it. Check the path is "
            "writable."
        )
    if line.startswith("ACQUIRED"):
        if verbose:
            print(f"Acquired workspace lock at {lock}")
        return
    parts = line.split("\t")
    held_by = parts[1] if len(parts) > 1 else ""
    held_info = parts[2] if len(parts) > 2 else ""
    if held_by == holder:
        # Ours already, e.g. waiting again on a job we dispatched earlier
        return
    raise WorkspaceBusy(
        f"The workspace on '{workspace.host}' is in use by another run"
        + (f" ({held_info})" if held_info else "")
        + ".\n\nWait for it to finish, or give this environment its own "
        "'wdir'. If that run is gone, clear the lock with:\n\n"
        f"    ssh {workspace.target} 'rm -rf {shlex.quote(lock)}'"
    )


def release_lock(
    workspace: Workspace,
    holder: str,
    verbose: bool = False,
) -> None:
    """Give the workspace back, if this run is what's holding it.

    Checking the holder first means a lock that was cleared and retaken
    while we were away isn't yanked out from under whoever has it now.
    """
    lock = lock_path(workspace.wdir)
    remote_command = (
        f"lock={shlex.quote(lock)}; "
        f'if [ "$(cat "$lock/holder" 2>/dev/null)" = {shlex.quote(holder)} ]; '
        'then rm -rf "$lock"; fi'
    )
    try:
        _run(workspace.ssh_argv(remote_command), verbose=verbose)
    except subprocess.CalledProcessError:
        # Losing a lock file is not worth failing a finished run over
        pass


def holds_snapshot(workspace: Workspace, sha: str) -> bool:
    """Whether the workspace is still on the commit we sent it.

    Checked before collecting results. The lock should make this
    impossible, but a lock that was cleared by hand, or a workspace
    somebody worked in directly, would otherwise hand back outputs built
    from code this run never sent -- and that would be recorded as though
    it had.
    """
    try:
        out = subprocess.check_output(
            workspace.ssh_argv(
                f"git -C {shlex.quote(workspace.wdir)} rev-parse HEAD"
            )
        ).decode()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return sha in out.split()


# Under .calkit/local, which is always gitignored. Anywhere tracked and
# writing this file would itself change the working tree, so the check that
# the tree didn't move while a job ran would fail on its own bookkeeping.
JOBS_FPATH = posixpath.join(".calkit", "local", "jobs.yaml")


def _load_jobs(jobs_fpath: str) -> dict:
    if not os.path.isfile(jobs_fpath):
        return {}
    with open(jobs_fpath) as f:
        return calkit.ryaml.load(f) or {}


def _save_jobs(jobs_fpath: str, jobs: dict) -> None:
    # ensure_local_dir writes the '*' .gitignore that keeps this private
    calkit.ensure_local_dir()
    os.makedirs(os.path.dirname(jobs_fpath) or ".", exist_ok=True)
    with open(jobs_fpath, "w") as f:
        calkit.ryaml.dump(jobs, f)


def run_in_workspace(
    workspace: Workspace,
    command: str,
    job_key: str,
    label: str,
    wdir: str | None = None,
    deps: list[str] | None = None,
    outs: list[str] | None = None,
    repo: git.Repo | None = None,
    poll_seconds: float = 2.0,
    echo=print,
    verbose: bool = False,
) -> None:
    """Run a command in the workspace on another machine, and wait for it.

    The command is started detached and its PID recorded, so losing the
    connection -- or stopping the pipeline -- doesn't kill the work. Running
    again picks the same job back up and carries on waiting rather than
    starting a second one.

    Shared by every kind of environment that runs somewhere else, because
    the problem is the same whether the command is the stage itself or a
    ``calkit scheduler batch`` that queues it: get this working tree there,
    start something, survive a disconnect, bring the results back.

    Nothing is declared about what moves. The tree goes as a snapshot, and
    what comes back is whatever the workspace says the run produced.

    ``deps`` and ``outs`` are for a caller that already knows them, such as
    ``calkit scheduler batch``, whose own --dep/--out options say so.
    Everyone else leaves them out and they are read from the compiled
    pipeline, which is where they are already written down.
    """
    if repo is None:
        repo = calkit.git.get_repo()
    run_wdir = workspace.path(wdir) if wdir else workspace.wdir
    # Detached so the connection can drop, with output kept rather than
    # discarded: when a job fails, what it said is the only thing that
    # explains why, and it is on the other side of an ssh connection that
    # has already closed.
    # The exit code is written where we can read it afterwards, because a
    # vanished PID says only that the command stopped -- not whether it
    # worked. Without this a failing job looks exactly like a successful
    # one, and whatever happened to be in the workspace gets collected and
    # recorded as its output.
    status_path = status_file(workspace.wdir)
    log_path = log_file(workspace.wdir)
    # The command runs in a subshell so that its own 'exit' ends that
    # subshell rather than the one recording the status. Without it, any
    # command that exits explicitly -- which is most scripts that fail on
    # purpose -- would leave no verdict behind at all.
    inner = f"( {command} ); echo $? > {shlex.quote(status_path)}"
    remote_cmd = (
        f"cd {shlex.quote(run_wdir)} ; "
        f"nohup sh -c {shlex.quote(inner)} > {shlex.quote(log_path)} 2>&1 "
        "& echo $!"
    )
    jobs = _load_jobs(JOBS_FPATH)
    job = jobs.get(job_key, {})
    remote_pid = job.get("remote_pid")
    snapshot = job.get("snapshot")
    # A workspace is one checkout at one commit, so two runs sharing it
    # would check out over each other and each would then be running
    # against the other's code. Take turns instead of giving up the reuse
    # that keeps environments and the DVC cache warm. The holder is this
    # job, so waiting again on a job we already dispatched re-acquires
    # rather than deadlocking against ourselves.
    holder = hashlib.sha1(job_key.encode()).hexdigest()[:16]
    info = (
        f"{label} from {socket.gethostname()} "
        f"at {calkit.utcnow().isoformat(timespec='seconds')}"
    )
    acquire_lock(workspace, holder=holder, info=info, verbose=verbose)
    if remote_pid is None:
        # Anything that goes wrong before the job is dispatched leaves no
        # remote work behind, so the workspace is free and the lock has to
        # come off with it. Only once something is actually running there
        # does a held lock mean anything.
        try:
            echo("Preparing workspace")
            ensure_workspace(workspace, verbose=verbose)
            # Put the workspace on exactly this working tree
            snapshot = create_snapshot(repo=repo)
            echo(f"Sending workspace snapshot {snapshot[:8]}")
            send_snapshot(
                workspace=workspace, sha=snapshot, repo=repo, verbose=verbose
            )
            # Last run's leftovers are still in the workspace; a command
            # that fails to write an output must not have the old file
            # collected as though this run had produced it
            stale = produced_paths(workspace) + (job.get("outs") or [])
            clear_outputs(workspace, stale, verbose=verbose)
            # Data the snapshot cannot carry, because Git ignores it, goes
            # through the workspace's own DVC cache
            hydrate_workspace_cache(
                workspace,
                paths=job.get("deps") or [],
                repo=repo,
                verbose=verbose,
                echo=echo,
            )
            echo(f"Running on {workspace.host}: {command}")
            if verbose:
                echo(f"Full command: {remote_cmd}")
        except BaseException:
            release_lock(workspace, holder=holder, verbose=verbose)
            raise
        # A login shell: Calkit installs itself into ~/.local/bin, which a
        # non-login ssh shell never has on PATH
        remote_pid = (
            subprocess.check_output(workspace.login_argv(remote_cmd))
            .decode()
            .strip()
            .splitlines()[-1]
        )
        echo(f"Running with remote PID: {remote_pid}")
        job["remote_pid"] = remote_pid
        job["snapshot"] = snapshot
        # Hashed at dispatch, compared when it finishes -- the same way a
        # scheduler job decides whether it is still valid
        job["deps"] = (
            list(deps) if deps is not None else deps_for_command(command)
        )
        job["outs"] = (
            list(outs) if outs is not None else outs_for_command(command)
        )
        job["dep_md5s"] = dep_md5s(job["deps"])
        job["submitted"] = time.time()
        job["finished"] = None
        jobs[job_key] = job
        _save_jobs(JOBS_FPATH, jobs)
    echo(f"Waiting for remote PID {remote_pid} to finish")
    ps_cmd = workspace.ssh_argv(f"ps -p {shlex.quote(str(remote_pid))}")
    while True:
        try:
            subprocess.check_output(ps_cmd, stderr=subprocess.DEVNULL)
            time.sleep(poll_seconds)
        except subprocess.CalledProcessError:
            echo("Remote process finished")
            break
    # The job has stopped, so the workspace is free whatever the
    # verdict was. Everything from here releases it and clears the
    # record: a job that merely failed would otherwise hold the
    # workspace until someone deleted the lock by hand, and would be
    # waited on again forever instead of being retried.
    try:
        # A vanished PID is not a verdict. Ask what the job actually reported
        # before anything it left behind is treated as a result.
        status = read_status(workspace)
        if status is None:
            raise RemoteJobFailed(
                f"The job on '{workspace.host}' stopped without recording an "
                "exit status, so there is no way to tell whether it worked. "
                "Nothing was collected; run it again." + _log_tail(workspace)
            )
        if status != 0:
            raise RemoteJobFailed(
                f"The job on '{workspace.host}' exited with status {status}. "
                "Nothing was collected." + _log_tail(workspace)
            )
        if snapshot is not None:
            # DVC hashes this stage's dependencies from the local files once we
            # return. If they moved while it ran elsewhere, recording the result
            # would pair inputs that were never used with outputs they never
            # produced, and that lock file reads as up to date forever.
            changed = changed_deps(
                job.get("dep_md5s") or {}, job.get("deps") or []
            )
            if changed:
                raise WorkspaceStateChanged(
                    "These changed while the job was running on "
                    f"'{workspace.host}', so its outputs did not come from "
                    "what is here now: "
                    + ", ".join(sorted(changed))
                    + ". Nothing was collected; run it again."
                )
            # And the workspace has to still be on what we sent it. The lock
            # should make this impossible, but a lock cleared by hand, or a
            # workspace somebody worked in directly, would otherwise hand back
            # outputs built from code this run never sent.
            if not holds_snapshot(workspace, sha=snapshot):
                raise WorkspaceStateChanged(
                    f"The workspace on '{workspace.host}' is no longer on the "
                    "commit this run sent it, so its outputs came from "
                    "something else. Nothing was collected; run it again."
                )
        # Outputs DVC tracks are ignored by Git, so the workspace has to say
        # what they were; committing them is what makes it able to
        commit_workspace_outputs(workspace, verbose=verbose)
        produced = produced_paths(workspace)
        # An output DVC caches is added to .gitignore, so the workspace's Git
        # cannot see it and it has to be asked for by name
        for out in remote_existing(workspace, job.get("outs") or []):
            if out not in produced:
                produced.append(out)
        if produced:
            echo(f"Collecting {len(produced)} path(s) the run produced")
            fetch_paths(workspace=workspace, paths=produced, verbose=verbose)
        try:
            prune_remote_snapshots(workspace=workspace, verbose=verbose)
        except subprocess.CalledProcessError:
            echo("Warning: failed to clean up workspace snapshots")
    finally:
        job["remote_pid"] = None
        job["finished"] = time.time()
        jobs[job_key] = job
        _save_jobs(JOBS_FPATH, jobs)
        release_lock(workspace, holder=holder, verbose=verbose)


class WorkspaceStateChanged(ValueError):
    """Something moved underneath a run, so its results can't be trusted."""


class RemoteJobFailed(ValueError):
    """A job on another machine did not finish successfully."""


# Written to .dvc/config.local, which is gitignored, so pointing a project
# at one person's workspace never lands in the project itself.
DVC_REMOTE_NAME = "calkit-workspace"


def dvc_remote_url(workspace: Workspace) -> str:
    """The workspace's DVC cache, addressed as a DVC remote.

    A cache directory already has the layout a remote does, so the
    workspace can serve as one without anything being set up there. That
    is what lets data move as content-addressed objects -- only what is
    missing, deduplicated -- rather than as a list of files someone had to
    write down.
    """
    return f"ssh://{workspace.scp_target}{workspace.path('.dvc', 'cache')}"


def _dvc(
    args: list[str], wdir: str | None = None
) -> subprocess.CompletedProcess:

    return subprocess.run(
        ["dvc"] + args,
        cwd=wdir,
        capture_output=True,
        text=True,
    )


def configure_dvc_remote(workspace: Workspace, verbose: bool = False) -> bool:
    """Point a local DVC remote at the workspace's cache.

    Local, so it is per-machine and gitignored: a workspace belongs to
    whoever is running, not to the project.
    """
    url = dvc_remote_url(workspace)
    result = _dvc(["remote", "add", "--local", "-f", DVC_REMOTE_NAME, url])
    if result.returncode != 0:
        if verbose:
            print(f"Could not add DVC remote: {result.stderr.strip()}")
        return False
    if workspace.ssh_key:
        _dvc(
            [
                "remote",
                "modify",
                "--local",
                DVC_REMOTE_NAME,
                "keyfile",
                workspace.ssh_key,
            ]
        )
    if workspace.user:
        _dvc(
            [
                "remote",
                "modify",
                "--local",
                DVC_REMOTE_NAME,
                "user",
                workspace.user,
            ]
        )
    return True


def dvc_tracked_deps(
    paths: list[str], repo: git.Repo | None = None
) -> list[str]:
    """Which dependencies DVC tracks, i.e. the ones Git does not carry.

    These are exactly the paths the snapshot leaves behind, so they are
    exactly the ones that have to travel some other way.
    """
    return paths_to_transfer(paths, repo=repo)


def hydrate_workspace_cache(
    workspace: Workspace,
    paths: list[str],
    repo: git.Repo | None = None,
    verbose: bool = False,
    echo=print,
) -> None:
    """Put the data a job needs into the workspace, via its own cache.

    Pushed as DVC objects rather than copied as files: only what the
    workspace is missing crosses the wire, and it lands addressed by
    content so a second project or a second run reuses it.
    """
    tracked = dvc_tracked_deps(paths, repo=repo)
    if not tracked:
        return
    if not configure_dvc_remote(workspace, verbose=verbose):
        echo("Warning: could not reach the workspace cache; sending files")
        send_paths(workspace=workspace, paths=tracked, verbose=verbose)
        return
    echo(f"Sending {len(tracked)} data path(s) to the workspace cache")
    push = _dvc(["push", "-r", DVC_REMOTE_NAME] + tracked)
    if push.returncode != 0:
        echo("Warning: DVC push failed; sending files instead")
        send_paths(workspace=workspace, paths=tracked, verbose=verbose)
        return
    # Objects in the cache are not files in the tree until checked out
    _run(
        workspace.login_argv(
            f"cd {shlex.quote(workspace.wdir)} && "
            "calkit dvc checkout " + " ".join(shlex.quote(p) for p in tracked)
        ),
        verbose=verbose,
    )


def commit_workspace_outputs(
    workspace: Workspace, verbose: bool = False
) -> None:
    """Have the workspace record what the job produced.

    Nothing runs DVC out there on its own, so a stage's outputs sit in the
    working tree and in no cache at all. Committing them is what puts them
    somewhere they can be fetched from, and is also what makes the
    workspace's dvc.lock say which paths they were.
    """
    # Through Calkit rather than DVC directly: a project's remotes can use
    # the ck:// scheme, which only Calkit registers, and a bare dvc there
    # fails on the config before it gets as far as committing anything.
    result = subprocess.run(
        workspace.login_argv(
            f"cd {shlex.quote(workspace.wdir)} && calkit dvc commit -f"
        ),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # A project with nothing DVC-tracked has nothing to commit, which
        # is not a failure of the job that just ran
        if verbose:
            print(
                f"Nothing committed in the workspace: {result.stderr.strip()}"
            )
