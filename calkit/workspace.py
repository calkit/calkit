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

import os
import tempfile

import git

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
_SNAPSHOT_AUTHOR = "Calkit <noreply@calkit.io>"
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
            GIT_AUTHOR_NAME="Calkit",
            GIT_AUTHOR_EMAIL="noreply@calkit.io",
            GIT_AUTHOR_DATE=_SNAPSHOT_DATE,
            GIT_COMMITTER_NAME="Calkit",
            GIT_COMMITTER_EMAIL="noreply@calkit.io",
            GIT_COMMITTER_DATE=_SNAPSHOT_DATE,
        ):
            return repo.git.commit_tree(*args, "-m", _SNAPSHOT_MESSAGE)


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
