"""Functionality for working with Git."""

import atexit
import hashlib
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from contextlib import contextmanager
from datetime import timezone
from typing import Any

import git
from fastapi import HTTPException
from filelock import FileLock, Timeout
from git.exc import GitCommandError
from ruamel.yaml import YAMLError
from sqlmodel import Session, select

import calkit
from app import cache, github, users
from app.config import settings
from app.core import load_yaml_fast, logger, ryaml
from app.models import GitRef, Project, User, UserProjectAccess

_SYMLINK_MODE = 0o120000

# Max seconds a single git network subprocess may run before being killed,
# so a stalled remote can't wedge a worker indefinitely. Clone gets a
# larger budget than fetch since initial clones of large repos are
# legitimately slower: a research project carrying its results in Git runs
# to a gigabyte across a few thousand commits, which is several minutes on
# a good connection. Anything under that is not a safety limit, it is a
# project the hub can never open, because each attempt restarts from
# nothing.
GIT_CLONE_TIMEOUT = 900
GIT_FETCH_TIMEOUT = 120


@contextmanager
def _timed(operation: str, **fields):
    """Log the wall-clock duration of a git operation as structured JSON.

    Emitted fields land in Loki so a slow/hanging step is visible in
    Grafana (e.g. filter ``git_op="fetch"`` and sort by ``duration_ms``).
    A line is logged on entry too, so a hang shows the start with no
    matching completion.
    """
    logger.info(
        f"git op start: {operation}",
        extra={"git_op": operation, "git_phase": "start", **fields},
    )
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            f"git op done: {operation}",
            extra={
                "git_op": operation,
                "git_phase": "done",
                "duration_ms": duration_ms,
                **fields,
            },
        )


# Path to a persistent git credential helper script created at first use
# The script reads credentials from GIT_TOKEN / GIT_USER env vars so the
# token never appears in URLs, command-line arguments, or .git/config
_CREDENTIAL_HELPER_PATH: str | None = None


def _get_credential_helper() -> str:
    """Return the path to the git credential helper, creating it if needed."""
    global _CREDENTIAL_HELPER_PATH
    if _CREDENTIAL_HELPER_PATH and os.path.isfile(_CREDENTIAL_HELPER_PATH):
        return _CREDENTIAL_HELPER_PATH
    # Git calls the helper with "get", "store", or "erase" as $1
    # For "get" we read and discard stdin then emit credentials
    # For everything else we drain stdin and do nothing
    script = (
        "#!/bin/sh\n"
        'case "$1" in\n'
        "    get)\n"
        '        while IFS= read -r line; do [ -z "$line" ] && break; done\n'
        '        echo "username=${GIT_USER:-x-access-token}"\n'
        '        echo "password=$GIT_TOKEN"\n'
        "        ;;\n"
        "    *) cat > /dev/null ;;\n"
        "esac\n"
    )
    fd, path = tempfile.mkstemp(prefix="ck_credhelper_", suffix=".sh")
    os.write(fd, script.encode())
    os.close(fd)
    os.chmod(path, stat.S_IRWXU)  # owner-only: rwx------
    atexit.register(lambda: os.path.isfile(path) and os.unlink(path))
    _CREDENTIAL_HELPER_PATH = path
    return path


def _make_git_auth_env(
    token: str, username: str | None = None
) -> dict[str, str]:
    """Return env vars that authenticate any git HTTPS operation.

    Installs a transient credential helper via GIT_CONFIG_COUNT that reads
    from GIT_TOKEN (and optionally GIT_USER). The first config entry clears
    any pre-existing credential helpers so ours is the only one invoked.
    The token never appears in the remote URL, .git/config, or process args.

    Pass ``username`` for hosts that use a fixed git username (e.g. ``"git"``
    for Overleaf); omit it for GitHub where ``x-access-token`` is the default.
    """
    env: dict[str, str] = {
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "credential.helper",
        "GIT_CONFIG_VALUE_0": "",  # Clear any existing helpers
        "GIT_CONFIG_KEY_1": "credential.helper",
        "GIT_CONFIG_VALUE_1": f"!{_get_credential_helper()}",
        "GIT_TOKEN": token,
        "GIT_TERMINAL_PROMPT": "0",
        # Abort HTTPS transfers that stall (<1 KB/s for 60s) so a slow or
        # unresponsive remote can't wedge a worker indefinitely.
        "GIT_HTTP_LOW_SPEED_LIMIT": "1000",
        "GIT_HTTP_LOW_SPEED_TIME": "60",
    }
    if username is not None:
        env["GIT_USER"] = username
    return env


# How long a remote's head SHA is trusted.
#
# Longer than a clone's own TTL, deliberately: a clone that lapses asks
# whether the remote moved, so a shorter window here would mean the answer
# had always expired by the time it was wanted, and every lapse would pay
# for its own round trip. At several times the clone TTL, one answer covers
# many lapses, across every user's clone of the project.
#
# Being minutes stale costs little now that a push says so directly, through
# the GitHub App's webhook or `calkit push` (see ``app.warm``). This poll is
# the fallback for pushes that arrive without either.
REMOTE_HEAD_TTL = 300


def get_remote_head_sha(
    repo: git.Repo, remote_url: str, branch: str, use_cache: bool = True
) -> str | None:
    """The SHA ``origin`` has for ``branch``, or None if it can't be read.

    ``ls-remote`` costs about as much as a fetch that has nothing to
    transfer -- both are a round trip to the host -- so this is only worth
    doing because the answer is cached and a fetch's isn't. When it comes
    back equal to what we already have, the fetch can be skipped entirely.
    """
    key = cache.make_key("remote-head", remote_url, branch)
    if use_cache:
        cached = cache.get_json(key)
        if isinstance(cached, str):
            return cached
    try:
        with _timed("ls-remote", branch=branch):
            out = repo.git.ls_remote(
                ["origin", branch], kill_after_timeout=GIT_FETCH_TIMEOUT
            )
    except GitCommandError as e:
        logger.warning(f"Could not read remote head for {branch}: {e}")
        return None
    line = out.strip().split("\n")[0] if out.strip() else ""
    sha = line.split()[0] if line else None
    if sha:
        cache.set_json(key, sha, ttl=REMOTE_HEAD_TTL)
    return sha


# Where the one checkout everybody reads from lives, under CLONE_ROOT. No
# GitHub name can be spelled this way, and ``_clone_dir_segment`` keeps the
# per-user directories out of it too.
SHARED_READER_DIR = "_shared"


def _clone_dir_segment(name: str) -> str:
    """Make ``name`` safe to use as one directory under ``CLONE_ROOT``.

    An account name is whatever someone typed at signup, so ``..`` (outside
    CLONE_ROOT) and ``_shared`` (on top of the tree everyone reads) are both
    one signup away.
    """
    segment = name.replace(os.sep, "_").replace("/", "_")
    if segment in ("", ".", "..", SHARED_READER_DIR):
        # Stable, so the account finds its checkout again next time.
        segment = "acct_" + hashlib.sha256(name.encode()).hexdigest()[:16]
    return segment


def is_shared_read_checkout(repo: git.Repo) -> bool:
    """Whether this repo is the checkout everybody reads from."""
    return (os.sep + SHARED_READER_DIR + os.sep) in os.path.abspath(
        str(repo.working_dir)
    )


def refuse_if_shared(repo: git.Repo) -> None:
    """Stop a write that has landed on the shared checkout.

    Committing there would author it in a tree other people are reading, and
    push it under whatever credentials that copy holds.
    """
    if is_shared_read_checkout(repo):
        raise HTTPException(
            500, "Refusing to write to the shared read-only checkout"
        )


# Refuse writes to the shared checkout from inside Git itself. `pre-push`
# goes with `pre-commit` because that copy carries the project's own
# credentials.
_SHARED_HOOKS = ("pre-commit", "pre-push")
_SHARED_HOOK_SCRIPT = (
    "#!/bin/sh\n"
    "# Installed by Calkit. This is the shared read-only checkout every\n"
    "# reader of this project sees; writes get their own copy.\n"
    'echo "calkit: refusing to write to the shared read-only checkout" >&2\n'
    "exit 1\n"
)


def _install_read_only_hooks(repo_dir: str) -> None:
    """Make ``repo_dir`` refuse commits and pushes at the Git level.

    ``refuse_if_shared`` only catches writes going through our own helpers;
    these catch anything reaching ``git commit``. Best effort: a checkout we
    can't write a hook into is still readable.
    """
    hooks_dir = os.path.join(repo_dir, ".git", "hooks")
    try:
        os.makedirs(hooks_dir, exist_ok=True)
        for name in _SHARED_HOOKS:
            fpath = os.path.join(hooks_dir, name)
            # A hook that isn't executable is one Git ignores.
            if os.path.isfile(fpath) and os.access(fpath, os.X_OK):
                continue
            with open(fpath, "w") as f:
                f.write(_SHARED_HOOK_SCRIPT)
            os.chmod(fpath, 0o755)
    except OSError as e:
        logger.warning(f"Could not install read-only hooks in {repo_dir}: {e}")


def _shared_read_token(project: Project) -> tuple[bool, str | None]:
    """Whether this project can be read from one shared checkout, and how.

    A public repo needs no credentials; a private one takes the App
    installation token, which belongs to the project rather than to whoever
    asked first. Returns ``(False, None)`` when neither applies.
    """
    if project.is_public:
        return True, None
    gh_owner, gh_repo = (
        project.github_repo.split("/", 1)
        if project.github_repo
        else (project.owner_github_name, project.name)
    )
    try:
        return True, github.get_app_installation_token(gh_owner, gh_repo)
    except (github.GitHubAppNotConfigured, HTTPException) as e:
        logger.info(
            f"No shared checkout for private {gh_owner}/{gh_repo}: {e}"
        )
        return False, None


def get_repo(
    project: Project,
    user: User | None,
    session: Session,
    ttl: int | None = None,
    fresh=False,
    ref: str | None = None,
    read_only: bool = False,
) -> git.Repo:
    """Ensure that the repo exists and is ready for operating upon for the user.

    Handles concurrency in case multiple API calls request the repo
    simultaneously. If TTL is None, the latest version is always fetched.

    ``read_only`` promises the caller will only read, which lets every
    reader of a project share one warm checkout instead of cloning their
    own. Opt-in, so the cost of missing one is a slow read rather than a
    wrong write; breaking the promise is caught by ``refuse_if_shared``.
    """
    owner_name = project.owner_github_name
    project_name = project.name
    shared_token: str | None = None
    # A private repo the App isn't installed on falls back to a per-user
    # checkout, still read-only.
    shared = False
    if read_only:
        shared, shared_token = _shared_read_token(project)
    # Add the file to the repo(s) -- we may need to clone it.
    # Ref-based reads should not mutate this working tree checkout.
    if shared:
        base_dir = os.path.join(
            settings.CLONE_ROOT, SHARED_READER_DIR, owner_name, project_name
        )
    elif user is not None:
        # github_username is None for GitHub-less users; fall back to the
        # (always-present, unique) account name for a stable temp path.
        user_dir = _clone_dir_segment(
            user.github_username or user.account.name
        )
        base_dir = os.path.join(
            settings.CLONE_ROOT, user_dir, owner_name, project_name
        )
    else:
        base_dir = os.path.join(
            settings.CLONE_ROOT, "anonymous", owner_name, project_name
        )
    repo_dir = os.path.join(base_dir, "repo")
    updated_fpath = os.path.join(base_dir, "updated.txt")
    lock_fpath = os.path.join(base_dir, "updating.lock")
    lock = FileLock(lock_fpath, timeout=5)
    os.makedirs(base_dir, exist_ok=True)
    if fresh and os.path.isdir(repo_dir):
        logger.info("Deleting repo directory to clone a fresh copy")
        shutil.rmtree(repo_dir, ignore_errors=True)
        # The marker is what says a complete checkout exists, so it has to go
        # with the tree it described. Leaving it behind claims a repo that is
        # no longer there, and the next read fails on the missing directory
        # instead of cloning again.
        if os.path.isfile(updated_fpath):
            os.remove(updated_fpath)
    # Clone the repo if it doesn't exist -- it will be in a "repo" dir
    access_token: str | None = None
    if shared:
        # The project's credentials, never a user's. This authorizes
        # nothing; the caller has already been through get_project.
        access_token = shared_token
    elif user is not None:
        if user.account.github_name is not None:
            # GitHub user: operate with their personal token.
            logger.info(f"Getting {user.email}'s token for Git operations")
            with _timed("get-github-token", user=user.github_username):
                access_token = users.get_github_token(
                    session=session, user=user
                )
        else:
            # GitHub-less member. Native access (role_id, e.g. from an invite)
            # is what lets us mint the repo-scoped, write-capable App
            # installation token; a public repo is still readable
            # unauthenticated without it. Requiring native access to mint is
            # defense in depth: callers already gate on get_project, but this
            # fails closed if one ever reaches get_repo without authorizing.
            has_native_access = session.exec(
                select(UserProjectAccess.role_id)
                .where(UserProjectAccess.project_id == project.id)
                .where(UserProjectAccess.user_id == user.id)
                .where(UserProjectAccess.role_id.is_not(None))  # type: ignore
            ).first()
            if has_native_access is not None:
                # Native collaborator: use the App token (needed for private
                # repos and pushes). Commits are still authored as this user.
                logger.info(
                    f"Getting GitHub App installation token for {user.email}"
                )
                # Mint against the actual GitHub repo parsed from git_repo_url,
                # not the Calkit slug, in case the project name/owner differs
                # from the repo (the installation is looked up by repo).
                gh_owner, gh_repo = (
                    project.github_repo.split("/", 1)
                    if project.github_repo
                    else (owner_name, project_name)
                )
                try:
                    with _timed("get-app-installation-token", user=user.email):
                        access_token = github.get_app_installation_token(
                            gh_owner, gh_repo
                        )
                except (github.GitHubAppNotConfigured, HTTPException) as e:
                    # A public repo can still be read/cloned unauthenticated,
                    # so fall back regardless of why the token was unavailable.
                    if project.is_public:
                        logger.warning(
                            "GitHub App token unavailable; using "
                            "unauthenticated access to public repo "
                            f"{owner_name}/{project_name}: {e}"
                        )
                        access_token = None
                    elif isinstance(e, github.GitHubAppNotConfigured):
                        # No App key at all (e.g. local dev without it set up).
                        raise HTTPException(
                            502,
                            "The Calkit GitHub App is not configured, so this "
                            "private project can't be accessed for a user "
                            "without a linked GitHub account.",
                        )
                    else:
                        # App configured but minting failed (bad/rotated key,
                        # App not installed on the repo, GitHub outage, ...).
                        # Surface the real error rather than masking it.
                        raise
            elif project.is_public:
                # No native access, but a public repo is readable
                # unauthenticated -- no App token needed.
                access_token = None
            else:
                # No access to a private project.
                raise HTTPException(
                    403, "You do not have access to this project."
                )
    # Plain URL with no embedded token -- credentials handled in helper
    git_plain_url = project.git_repo_url
    if not git_plain_url.endswith(".git"):
        git_plain_url += ".git"
    newly_cloned = False
    repo = None
    # `updated.txt` appears only after a clone has finished, so a repo
    # directory without one is a clone that is still running or that died
    # partway -- not something to read.
    if not os.path.isfile(updated_fpath):
        newly_cloned = True
        logger.info(f"Git cloning into {repo_dir}")
        try:
            with lock:
                # Whoever holds the lock owns this directory, so re-check
                # inside it: another worker may have finished the clone while
                # we waited, in which case there is nothing left to do.
                if not os.path.isfile(updated_fpath):
                    # Clone alongside the destination and move it into place
                    # only once git says it finished. `repo_dir` then either
                    # doesn't exist or holds a complete checkout -- never a
                    # tree that a reader could mistake for a project with no
                    # files in it. Anything left from an earlier attempt that
                    # died is ours to clear, since we hold the lock.
                    staging_dir = repo_dir + ".cloning"
                    for stale in (staging_dir, repo_dir):
                        if os.path.isdir(stale):
                            logger.warning(f"Removing incomplete {stale}")
                            shutil.rmtree(stale, ignore_errors=True)
                    try:
                        clone_cmd = ["git", "clone"]
                        if settings.GIT_CLONE_FILTER:
                            clone_cmd.append(
                                f"--filter={settings.GIT_CLONE_FILTER}"
                            )
                        clone_cmd += [git_plain_url, staging_dir]
                        env = (
                            {**os.environ, **_make_git_auth_env(access_token)}
                            if access_token
                            else None
                        )
                        with _timed(
                            "clone",
                            repo=f"{owner_name}/{project_name}",
                        ):
                            subprocess.check_call(
                                clone_cmd,
                                env=env,
                                timeout=GIT_CLONE_TIMEOUT,
                            )
                    except subprocess.CalledProcessError:
                        logger.error("Failed to clone repo")
                        shutil.rmtree(staging_dir, ignore_errors=True)
                        raise HTTPException(404, "Git repo not found")
                    except subprocess.TimeoutExpired:
                        # Every retry starts this repo over from nothing, so
                        # a repo too big to clone inside the budget never
                        # converges however many times it is asked for. Say
                        # so rather than letting it look like a server error.
                        logger.error(
                            f"Clone of {owner_name}/{project_name} exceeded "
                            f"{GIT_CLONE_TIMEOUT}s"
                        )
                        shutil.rmtree(staging_dir, ignore_errors=True)
                        raise HTTPException(
                            504,
                            "This project's repository took too long to "
                            "download.",
                        )
                    os.rename(staging_dir, repo_dir)
                    # Touch a file so we can compute a TTL
                    subprocess.check_call(["touch", updated_fpath])
                repo = git.Repo(repo_dir)
        except Timeout:
            logger.warning("Git repo lock timed out")
    # `updated.txt` is only written once a clone has finished, so its absence
    # means this checkout has never been complete -- either a first clone is
    # running right now behind the lock we just gave up on, or one died
    # partway. Reading the directory anyway hands callers a tree with no
    # calkit.yaml and no files, which they cannot tell apart from a project
    # that genuinely has neither: the request 200s with an empty list, or
    # 404s on a file that does exist. Say "not ready yet" instead.
    if not os.path.isfile(updated_fpath):
        logger.warning(
            f"Repo for {owner_name}/{project_name} is not ready "
            "(no completed clone)"
        )
        raise HTTPException(
            503,
            "This project is still being prepared. Try again in a moment.",
            headers={"Retry-After": "5"},
        )
    if shared:
        # Here rather than next to the clone so it covers existing checkouts
        # and the TTL fast path that returns below.
        _install_read_only_hooks(repo_dir)
    last_updated = os.path.getmtime(updated_fpath)
    did_refresh = newly_cloned
    if not newly_cloned:
        # TODO: Only pull if we know we need to, perhaps with a call to GitHub
        # for the latest rev
        repo = git.Repo(repo_dir)
        ttl_expired = ttl is None or ((time.time() - last_updated) > ttl)
        # Legacy shallow repos must be unshallowed regardless of TTL, so
        # force the slow path when we detect one.
        is_shallow = os.path.isfile(os.path.join(repo.git_dir, "shallow"))
        # Fast path: if the cache is still warm we skip the lock and the
        # subprocesses that would otherwise run on every read (committer
        # config, URL migration). These are only relevant when we plan to
        # hit the network or mutate the tree.
        if not ttl_expired and not is_shallow:
            if access_token:
                repo.git.update_environment(**_make_git_auth_env(access_token))
            return repo
        try:
            with lock:
                # Re-check the TTL now that we hold the lock. A page load
                # fires many requests at once, so they all see the same
                # expired timestamp and queue here together -- and without
                # this, every one of them would fetch in turn, each paying
                # the network round trip and the working-tree reset behind
                # it. The winner touches `updated_fpath` below, so everyone
                # behind it can see the refresh already happened and go
                # straight to reading. An explicit `ttl=None`/`0` still
                # always refreshes, which is what callers asking for that
                # mean.
                if os.path.isfile(updated_fpath):
                    last_updated = os.path.getmtime(updated_fpath)
                ttl_expired = ttl is None or (
                    (time.time() - last_updated) > ttl
                )
                if not ttl_expired and not is_shallow:
                    if access_token:
                        repo.git.update_environment(
                            **_make_git_auth_env(access_token)
                        )
                    return repo
                # Migrate repos cloned with an embedded token in the remote
                # URL to the plain URL so our credential helper is used
                # instead. Plain https URLs from GitHub never contain "@", so
                # this heuristic is safe for our inputs.
                try:
                    current_url = repo.remotes.origin.url
                    if "@" in current_url:
                        logger.info("Stripping token from remote URL")
                        repo.remotes.origin.set_url(git_plain_url)
                except (GitCommandError, AttributeError) as e:
                    # Best-effort migration; log but continue
                    logger.warning(f"Could not migrate remote URL: {e}")
                # Set credentials on the git object before any network ops
                if access_token:
                    repo.git.update_environment(
                        **_make_git_auth_env(access_token)
                    )
                # Unshallow any repo that was cloned with --depth before we
                # switched to always doing full clones.
                repo_label = f"{owner_name}/{project_name}"
                if is_shallow:
                    logger.info("Unshallowing legacy shallow repo")
                    with _timed("fetch-unshallow", repo=repo_label):
                        repo.git.fetch(
                            ["--unshallow", "--tags"],
                            kill_after_timeout=GIT_FETCH_TIMEOUT,
                        )
                    subprocess.call(["touch", updated_fpath])
                # Ask what the remote has before going to get it. That
                # answer is shared between everyone's clone of the project,
                # so most expiries are settled without touching the network,
                # and when it matches ours there is nothing to fetch at all.
                already_current = False
                if not is_shallow and ref is None:
                    branch_name = repo.active_branch.name
                    try:
                        local_head: str | None = repo.head.commit.hexsha
                    except (ValueError, GitCommandError):
                        local_head = None
                    # A caller asking for ttl 0/None wants the truth, not
                    # a cached answer. That is the path a push takes, and a
                    # head cached from before it would say "already current"
                    # and mark a stale clone fresh -- so the warm a push
                    # queues would rebuild everything at the old commit.
                    remote_head = (
                        get_remote_head_sha(
                            repo,
                            git_plain_url,
                            branch_name,
                            use_cache=bool(ttl),
                        )
                        if local_head
                        else None
                    )
                    if remote_head is not None and remote_head == local_head:
                        logger.info(
                            f"{repo_label} is already at {remote_head[:7]}"
                        )
                        subprocess.call(["touch", updated_fpath])
                        did_refresh = True
                        already_current = True
                if not is_shallow and not already_current:
                    logger.info("Git fetching")
                    if ref is None:
                        with _timed(
                            "fetch", repo=repo_label, branch=branch_name
                        ):
                            repo.git.fetch(
                                ["origin", branch_name],
                                kill_after_timeout=GIT_FETCH_TIMEOUT,
                            )
                        # Only rewrite the working tree when the remote
                        # actually moved. The reset/clean/checkout dance below
                        # rewrites files that concurrent readers of this same
                        # checkout are parsing right now -- the file lock
                        # serializes writers against each other, not against
                        # readers -- and a torn read of calkit.yaml surfaces
                        # as a bogus parse error or a 500. The fetch itself
                        # only writes .git, so it is safe to leave running on
                        # every refresh; skipping the rewrite when there is
                        # nothing new removes the hazard from the common case.
                        try:
                            local_sha = repo.head.commit.hexsha
                            remote_sha = repo.commit(
                                f"origin/{branch_name}"
                            ).hexsha
                        except Exception as e:
                            logger.warning(f"Could not compare to origin: {e}")
                            local_sha, remote_sha = None, None
                        if local_sha is None or local_sha != remote_sha:
                            # If we had any failed previous transactions, reset
                            # and clean
                            repo.git.reset()
                            repo.git.clean("-fd")
                            repo.git.stash("save", "Auto-stash before pull")
                            repo.git.checkout([f"origin/{branch_name}"])
                            repo.git.branch(["-D", branch_name])
                            repo.git.checkout(["-b", branch_name])
                    else:
                        with _timed("fetch-all", repo=repo_label):
                            repo.git.fetch(
                                ["--all", "--tags"],
                                kill_after_timeout=GIT_FETCH_TIMEOUT,
                            )
                    subprocess.call(["touch", updated_fpath])
                did_refresh = True
        except Timeout:
            logger.warning("Git repo lock timed out")
        except GitCommandError as e:
            logger.error(f"Failed to refresh repo: {e}")
    if repo is None:
        repo = git.Repo(repo_dir)
    # Attach credentials to the repo's git runner so every subsequent
    # push/fetch/pull in callers (routes/core.py etc.) is authenticated
    # without embedding the token in any URL or argument
    if access_token:
        repo.git.update_environment(**_make_git_auth_env(access_token))
    # (Re)configure committer identity only when we just refreshed or
    # cloned. `user.full_name` may have been None at the time of the
    # initial clone (GitHub users without a display name), which would
    # have stored the literal string "None" as the committer, so we
    # re-run on every refresh to repair that -- but not on every cached
    # read, which would be pure overhead.
    if user is not None and did_refresh and not shared:
        _configure_committer(repo, user, session=session)
    if did_refresh:
        record_project_update(project, repo, session)
    return repo


def record_project_update(
    project: Project, repo: git.Repo, session: Session
) -> None:
    """Move the project's "last updated" up to its head commit, if newer.

    The time follows the repo rather than the database row: a push from
    the CLI, a collaborator's commit, an Overleaf sync, or a commit the
    hub itself just made. It's recorded lazily, whenever something sees a
    newer head, which is what "most recently worked on" should mean on
    the projects list.
    """
    try:
        head_dt = repo.head.commit.committed_datetime.astimezone(
            timezone.utc
        ).replace(tzinfo=None)
        if project.updated is None or head_dt > project.updated:
            project.updated = head_dt
            session.add(project)
            session.commit()
            # The commit expires the row's attributes; callers go on using
            # the project, so load them back now rather than lazily later
            session.refresh(project)
    except Exception as e:
        logger.warning(f"Could not record project update time: {e}")


def _detect_full_name_from_history(repo: git.Repo, email: str) -> str | None:
    """Look for a prior commit by ``email`` with a usable author name.

    Returns the first non-empty name that isn't the literal "None" (which is
    what a ``None`` ``user.full_name`` got stringified to in earlier commits).
    """
    if not email:
        return None
    try:
        out = repo.git.log(
            "--all",
            f"--author={email}",
            "--pretty=%an",
            "-n",
            "50",
        )
    except GitCommandError:
        return None
    for line in out.splitlines():
        candidate = line.strip()
        if candidate and candidate.lower() != "none":
            return candidate
    return None


def _configure_committer(
    repo: git.Repo, user: User, session: Session | None = None
) -> None:
    """Set the repo's user.name/user.email so commits are authored correctly.

    If ``user.full_name`` is missing, tries to recover a real name from the
    repo's own history (prior commits by the same email) and persists it back
    to the User row. Falls back through ``full_name`` -> ``github_username``
    -> ``email`` so we never pass ``None`` (which GitPython would stringify
    to "None").
    """
    refuse_if_shared(repo)
    email = user.email or f"{user.github_username}@users.noreply.github.com"
    if not user.full_name and session is not None:
        detected = _detect_full_name_from_history(repo, email)
        if detected:
            logger.info(
                f"Recovered full_name '{detected}' for {user.email} "
                "from repo history"
            )
            user.full_name = detected
            session.add(user)
            session.commit()
    name = user.full_name or user.github_username or user.email
    repo.git.config(["user.name", name])
    repo.git.config(["user.email", email])


def get_zip_path_map_from_repo(repo: git.Repo) -> dict:
    """Return the dvc-zip workspace→zip path map from .calkit/zip/paths.json."""
    paths_json = os.path.join(repo.working_dir, ".calkit", "zip", "paths.json")
    if not os.path.isfile(paths_json):
        return {}
    try:
        with open(paths_json) as f:
            return json.load(f) or {}
    except Exception:
        return {}


def get_ck_info_from_repo(repo: git.Repo, read_only: bool = False) -> dict:
    """Load calkit.yaml from the repo's working tree.

    Pass ``read_only=True`` when the result is only inspected, never written
    back: it swaps ruamel's round-trip parser for the C loader, which is far
    faster but drops the comments and quoting a faithful rewrite needs.
    """
    try:
        ck_info = calkit.load_calkit_info(
            wdir=repo.working_dir,
            read_only=read_only,
        )
    except (YAMLError, IndexError) as e:
        # A user's calkit.yaml can be malformed (e.g., multiple YAML documents
        # in a single file), or empty/whitespace-only, which makes ruamel raise
        # a bare IndexError from its scanner. That's bad data in their repo, not
        # a server error, so treat it as empty rather than 500-ing the project.
        logger.warning(
            f"Failed to parse calkit.yaml in {repo.working_dir}: "
            f"{type(e).__name__}: {e}"
        )
        return {}
    if not isinstance(ck_info, dict):
        # calkit.yaml can hold any YAML value (empty, a list, a string);
        # only a mapping is usable project metadata
        ck_info = {}
    return ck_info


def get_ck_info(
    project: Project,
    user: User | None,
    session: Session,
    ttl=None,
    ref: str | None = None,
    read_only: bool = False,
) -> dict:
    """Load the calkit.yaml file contents into a dictionary.

    ``read_only`` promises the caller never writes the result back, which
    buys both the shared checkout and the fast parser.
    """
    repo = get_repo(
        project=project,
        user=user,
        session=session,
        ttl=ttl,
        ref=ref,
        read_only=read_only,
    )
    return get_ck_info_from_repo(repo=repo, read_only=read_only)


def get_dvc_pipeline(
    project: Project,
    user: User | None,
    session: Session,
    ttl=None,
    ref: str | None = None,
) -> dict:
    repo = get_repo(
        project=project, user=user, session=session, ttl=ttl, ref=ref
    )
    return get_dvc_pipeline_from_repo(repo)


def get_dvc_pipeline_from_repo(
    repo: git.Repo, read_only: bool = False
) -> dict:
    """Load dvc.yaml from the repo's working tree.

    ``read_only`` swaps ruamel's round-trip parser for the C loader; on a
    large dvc.yaml that is the difference between ~300ms and a few.
    """
    fpath = os.path.join(repo.working_dir, "dvc.yaml")
    if not os.path.isfile(fpath):
        return {}
    with open(fpath) as f:
        return (load_yaml_fast(f.read()) if read_only else ryaml.load(f)) or {}


def get_overleaf_repo(
    project: Project, user: User, session: Session, overleaf_project_id: str
) -> git.Repo:
    """Get a freshly pulled Overleaf repository for a user/project."""
    owner_name, project_name = project.owner_github_name, project.name
    base_dir = (
        f"{settings.CLONE_ROOT}/{user.github_username}/{owner_name}/"
        f"{project_name}/overleaf/{overleaf_project_id}"
    )
    repo_dir = os.path.join(base_dir, "repo")
    os.makedirs(base_dir, exist_ok=True)
    overleaf_token = users.get_overleaf_token(session=session, user=user)
    # Plain URL — credentials supplied via credential helper
    # (username "git" for Overleaf)
    git_plain_url = f"https://git.overleaf.com/{overleaf_project_id}"
    overleaf_auth = _make_git_auth_env(overleaf_token, username="git")
    if os.path.isdir(repo_dir):
        repo = git.Repo(repo_dir)
        repo.git.update_environment(**overleaf_auth)
        repo.git.pull()
    else:
        subprocess.check_call(
            ["git", "clone", git_plain_url, repo_dir],
            env={**os.environ, **overleaf_auth},
            timeout=300,
        )
        repo = git.Repo(repo_dir)
        repo.git.update_environment(**overleaf_auth)
    # Run git config so we make commits as this user (with safe fallbacks)
    _configure_committer(repo, user, session=session)
    return repo


def get_default_branch(repo: git.Repo) -> str:
    """Return the default branch name (e.g. 'main' or 'master')."""
    try:
        # origin/HEAD symbolic ref is the most reliable source
        origin_head = repo.remotes.origin.refs["HEAD"]
        ref_path = origin_head.ref.name  # e.g. "origin/main"
        return ref_path.removeprefix("origin/")
    except Exception:
        pass
    # Fall back: look for common default names
    branch_names = {b.name for b in repo.branches}
    for candidate in ("main", "master", "trunk", "develop"):
        if candidate in branch_names:
            return candidate
    # Last resort: use whatever HEAD points to
    try:
        return repo.active_branch.name
    except Exception:
        return "main"


def _ahead_behind(
    repo: git.Repo, branch_ref: str, base_ref: str
) -> tuple[int, int]:
    """Return (ahead, behind) commit counts of branch_ref vs base_ref."""
    try:
        ahead = sum(
            1
            for _ in repo.iter_commits(
                f"{base_ref}..{branch_ref}", max_count=200
            )
        )
        behind = sum(
            1
            for _ in repo.iter_commits(
                f"{branch_ref}..{base_ref}", max_count=200
            )
        )
        return ahead, behind
    except Exception:
        return 0, 0


def search_refs(repo: git.Repo, query: str | None = None) -> list["GitRef"]:
    """Search for refs (branches, tags, commits) in a repository.

    Parameters
    ----------
    repo : git.Repo
        GitPython Repo object.
    query : str, optional
        Filter by branch name, tag name, commit message, or author name.

    Returns
    -------
    list[GitRef]
        Refs with name, type, message, author, timestamp.
    """
    refs = []
    query_lower = query.lower() if query else None

    default_branch = get_default_branch(repo)

    # Add branches--prefer remote refs so shallow clones see all branches
    seen_branches: set[str] = set()
    try:
        remote_refs = list(repo.remotes.origin.refs)
    except Exception:
        remote_refs = []
    branch_sources = [
        (ref.name.removeprefix("origin/"), ref)
        for ref in remote_refs
        if not ref.name.endswith("/HEAD")
    ] + [
        (branch.name, branch)
        for branch in repo.branches
        if branch.name
        not in {
            r.name.removeprefix("origin/")
            for r in remote_refs
            if not r.name.endswith("/HEAD")
        }
    ]
    for name, ref in branch_sources:
        if name in seen_branches:
            continue
        seen_branches.add(name)
        if query_lower and query_lower not in name.lower():
            try:
                commit = ref.commit
                msg = (
                    commit.message
                    if isinstance(commit.message, str)
                    else bytes(commit.message).decode()
                )
                if (
                    query_lower not in msg.lower()
                    and query_lower not in (commit.author.name or "").lower()
                ):
                    continue
            except Exception:
                continue
        try:
            commit = ref.commit
            msg = (
                commit.message
                if isinstance(commit.message, str)
                else bytes(commit.message).decode()
            )
            is_default = name == default_branch
            ahead, behind = (
                (0, 0)
                if is_default
                else _ahead_behind(repo, name, default_branch)
            )
            refs.append(
                {
                    "name": name,
                    "kind": "branch",
                    "message": msg.split("\n")[0],
                    "author": commit.author.name,
                    "timestamp": commit.committed_datetime.isoformat(),
                    "hash": commit.hexsha,
                    "short_hash": commit.hexsha[:7],
                    "is_default": is_default,
                    "ahead": ahead,
                    "behind": behind,
                }
            )
        except Exception as e:
            logger.warning(f"Failed to get commit info for branch {name}: {e}")
            refs.append(
                {
                    "name": name,
                    "kind": "branch",
                    "is_default": name == default_branch,
                    "ahead": 0,
                    "behind": 0,
                }
            )

    # Add tags
    try:
        for tag in repo.tags:
            name = tag.name
            if query_lower and query_lower not in name.lower():
                # Try to get tag message for fuzzy matching
                try:
                    if tag.tag and tag.tag.message:
                        if query_lower not in tag.tag.message.lower():
                            continue
                except Exception:
                    pass

            try:
                commit = tag.commit
                message = None
                if tag.tag and tag.tag.message:
                    message = tag.tag.message.split("\n")[0]
                elif commit.message:
                    raw = commit.message
                    msg_str = (
                        raw if isinstance(raw, str) else bytes(raw).decode()
                    )
                    message = msg_str.split("\n")[0]

                refs.append(
                    {
                        "name": name,
                        "kind": "tag",
                        "message": message,
                        "author": commit.author.name
                        if commit.author
                        else None,
                        "timestamp": commit.committed_datetime.isoformat()
                        if commit.committed_datetime
                        else None,
                        "hash": commit.hexsha,
                        "short_hash": commit.hexsha[:7],
                    }
                )
            except Exception as e:
                logger.warning(
                    f"Failed to get commit info for tag {name}: {e}"
                )
                refs.append(
                    {
                        "name": name,
                        "kind": "tag",
                    }
                )
    except Exception as e:
        logger.warning(f"Failed to list tags: {e}")

    # Add recent commits
    try:
        max_commits = 50
        for commit in repo.iter_commits("HEAD", max_count=max_commits):
            short_hash = commit.hexsha[:7]
            raw_msg = commit.message
            message = (
                (
                    raw_msg
                    if isinstance(raw_msg, str)
                    else bytes(raw_msg).decode()
                ).split("\n")[0]
                if raw_msg
                else ""
            )
            # Check if this commit matches the query
            if query_lower:
                if not (
                    query_lower in short_hash.lower()
                    or query_lower in message.lower()
                    or query_lower in (commit.author.name or "").lower()
                ):
                    continue
            # Avoid duplicates with branches/tags
            if short_hash not in [r.get("short_hash", "") for r in refs]:
                refs.append(
                    {
                        "name": short_hash,
                        "kind": "commit",
                        "message": message,
                        "author": commit.author.name,
                        "timestamp": commit.committed_datetime.isoformat(),
                        "hash": commit.hexsha,
                        "short_hash": short_hash,
                    }
                )
    except Exception as e:
        logger.warning(f"Failed to list commits: {e}")
    # Sort refs: branches first, then tags, then commits; newest first in each
    kind_order = {"branch": 0, "tag": 1, "commit": 2}
    refs.sort(
        key=lambda r: (
            kind_order.get(r.get("kind", "commit"), 3),
            r.get("timestamp") or "",
            r.get("name") or "",
        ),
        reverse=False,
    )
    refs.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    refs.sort(
        key=lambda r: kind_order.get(r.get("kind", "commit"), 3),
        reverse=False,
    )
    return [GitRef(**r) for r in refs]


# Cache for get_file_history results, keyed by (repo_dir, path, max_count,
# head_sha)
# Bounded to 256 entries; keyed by HEAD SHA so stale entries are never
# returned
_FILE_HISTORY_CACHE: OrderedDict[tuple, list[dict]] = OrderedDict()
_FILE_HISTORY_CACHE_MAX = 256

# Cache of parsed dvc.lock blobs: {blob_sha: {out_path: md5}}.
# Shared across all file-history requests in the process so the YAML parse
# for any given dvc.lock revision only happens once.
_DVC_LOCK_PARSE_CACHE: OrderedDict[str, dict[str, str]] = OrderedDict()
_DVC_LOCK_PARSE_CACHE_MAX = 512


def _dvc_lock_outs_at(commit: git.Commit) -> dict[str, str] | None:
    """Return the {out_path: md5} map parsed from dvc.lock at ``commit``.

    Caches by dvc.lock blob SHA so the same revision is never parsed twice,
    even across different file-history requests.
    """
    try:
        blob = commit.tree / "dvc.lock"
    except KeyError:
        return None
    return _parse_dvc_lock_outs(blob.hexsha, blob.data_stream.read)


def _peek_dvc_lock_outs(blob_sha: str) -> dict[str, str] | None:
    """Return a parsed dvc.lock blob if cached, without parsing on a miss.

    Refreshes LRU recency on a hit exactly as ``_parse_dvc_lock_outs`` does,
    so a revision that keeps getting read isn't evicted ahead of a colder one.
    """
    cached = _DVC_LOCK_PARSE_CACHE.get(blob_sha)
    if cached is not None:
        _DVC_LOCK_PARSE_CACHE.move_to_end(blob_sha)
    return cached


def _parse_dvc_lock_outs(blob_sha: str, read_bytes) -> dict[str, str]:
    """Return {out_path: md5} for a dvc.lock blob, caching by blob SHA.

    ``read_bytes`` is a zero-arg callable returning the blob contents, only
    invoked on cache miss so batched callers don't pay the cost twice.
    """
    cached = _peek_dvc_lock_outs(blob_sha)
    if cached is not None:
        return cached
    # A history walk reads dvc.lock at every commit that touched the file,
    # and a project of any size keeps a megabyte of it: parsing a thousand
    # revisions is minutes of work that is identical for every worker, every
    # viewer and every restart. Keyed by the blob, so it is only ever done
    # once anywhere.
    shared_key = cache.make_key("dvc-lock-outs", blob_sha)
    shared = cache.get_json(shared_key)
    if isinstance(shared, dict):
        _DVC_LOCK_PARSE_CACHE[blob_sha] = shared
        if len(_DVC_LOCK_PARSE_CACHE) > _DVC_LOCK_PARSE_CACHE_MAX:
            _DVC_LOCK_PARSE_CACHE.popitem(last=False)
        return shared
    try:
        # Not ryaml: we only pull plain strings out of this and never write it
        # back. On a 47 KB dvc.lock that is ~6 ms/parse versus ~94 ms, which
        # dominates file-history requests walking hundreds of revisions.
        data = load_yaml_fast(read_bytes()) or {}
    except Exception:
        data = {}
    outs: dict[str, str] = {}
    for stage in (data.get("stages") or {}).values():
        # A revision can carry a stage name with nothing under it, which
        # parses to None. Walking history means reading every dvc.lock a
        # project ever had, so one malformed old revision must not take the
        # whole file history down with it.
        if not isinstance(stage, dict):
            continue
        for out in stage.get("outs") or []:
            if not isinstance(out, dict):
                continue
            p = out.get("path")
            if not p:
                continue
            outs[p] = out.get("md5") or out.get("hash") or ""
    _DVC_LOCK_PARSE_CACHE[blob_sha] = outs
    if len(_DVC_LOCK_PARSE_CACHE) > _DVC_LOCK_PARSE_CACHE_MAX:
        _DVC_LOCK_PARSE_CACHE.popitem(last=False)
    cache.set_json(shared_key, outs)
    return outs


# ASCII separators used in `git log --format` output so commit bodies can
# include newlines without breaking our parser.
_LOG_US = "\x1f"  # unit separator (between fields)
_LOG_RS = "\x1e"  # record separator (between commits)
_LOG_FMT = (
    f"%H{_LOG_US}%ct{_LOG_US}%cI{_LOG_US}%an{_LOG_US}%ae"
    f"{_LOG_US}%P{_LOG_US}%s{_LOG_US}%B{_LOG_RS}"
)


def _parse_log_records(out: str) -> list[dict]:
    """Parse the output of ``git log --format=<_LOG_FMT>`` into commit dicts."""
    commits: list[dict] = []
    for rec in out.split(_LOG_RS):
        rec = rec.lstrip("\n")
        if not rec:
            continue
        parts = rec.split(_LOG_US)
        if len(parts) < 8:
            continue
        h, ct, ci, an, ae, parents, subject, body = parts[:8]
        commits.append(
            {
                "hash": h,
                "short_hash": h[:7],
                "message": body.rstrip("\n"),
                "author": an,
                "author_email": ae,
                "timestamp": ci,
                "committed_date": int(ct),
                "parent_hashes": [p[:7] for p in parents.split() if p],
                "summary": subject,
            }
        )
    return commits


def _get_commits_for_paths(
    repo: git.Repo, max_count: int, paths: list[str]
) -> list[dict]:
    """Return commits touching any of ``paths`` via a single ``git log``
    call.
    """
    if not paths:
        return []
    args = [
        "git",
        "log",
        f"--max-count={max_count}",
        f"--format={_LOG_FMT}",
        "HEAD",
        "--",
        *paths,
    ]
    try:
        proc = subprocess.run(
            args,
            cwd=repo.working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        logger.warning(f"git log failed to start for {paths!r}: {exc}")
        return []
    if proc.returncode != 0:
        logger.warning(
            f"git log failed for {paths!r}: "
            f"{proc.stderr.decode('utf-8', errors='replace').strip()}"
        )
        return []
    return _parse_log_records(proc.stdout.decode("utf-8", errors="replace"))


def _batch_check_blobs(repo: git.Repo, specs: list[str]) -> dict[str, str]:
    """Return ``{spec: blob_sha}`` via ``git cat-file --batch-check``.

    Unlike ``_batch_read_blobs`` this transfers only object headers, not
    content. Naming the blob a commit points at is what lets a caller answer
    from ``_DVC_LOCK_PARSE_CACHE`` (keyed by blob SHA, and shared across
    requests) without transferring the blob at all -- so a revision parsed by
    an earlier request costs nothing here beyond its header.
    """
    results: dict[str, str] = {}
    if not specs:
        return results
    try:
        proc = subprocess.Popen(
            ["git", "cat-file", "--batch-check"],
            cwd=repo.working_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        logger.warning(f"git cat-file --batch-check failed to start: {exc}")
        return results
    stdout, stderr = proc.communicate(("\n".join(specs) + "\n").encode())
    if proc.returncode != 0:
        logger.warning(
            f"git cat-file --batch-check failed (exit {proc.returncode}): "
            f"{stderr.decode('utf-8', errors='replace').strip()}"
        )
        return results
    lines = stdout.decode("utf-8", errors="replace").splitlines()
    for spec, line in zip(specs, lines):
        parts = line.split(" ")
        # "<name> missing" or "<name> ambiguous"
        if len(parts) < 3 or parts[1] != "blob":
            continue
        results[spec] = parts[0]
    return results


def _batch_read_blobs(
    repo: git.Repo, specs: list[str]
) -> dict[str, tuple[str, bytes] | None]:
    """Return ``{spec: (blob_sha, content)}`` via ``git cat-file --batch``.

    Missing/ambiguous specs map to ``None``. A single subprocess handles all
    specs, so we avoid per-commit tree walks through GitPython.
    """
    results: dict[str, tuple[str, bytes] | None] = {s: None for s in specs}
    if not specs:
        return results
    try:
        proc = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            cwd=repo.working_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        logger.warning(f"git cat-file --batch failed to start: {exc}")
        return results
    payload = ("\n".join(specs) + "\n").encode()
    stdout, stderr = proc.communicate(payload)
    if proc.returncode != 0:
        logger.warning(
            f"git cat-file --batch failed (exit {proc.returncode}): "
            f"{stderr.decode('utf-8', errors='replace').strip()}"
        )
        return results
    idx = 0
    for spec in specs:
        nl = stdout.find(b"\n", idx)
        if nl < 0:
            break
        header = stdout[idx:nl].decode("utf-8", errors="replace")
        idx = nl + 1
        parts = header.split(" ")
        # "<name> missing" or "<name> ambiguous"
        if len(parts) == 2 and parts[1] in ("missing", "ambiguous"):
            continue
        if len(parts) < 3:
            continue
        sha = parts[0]
        try:
            size = int(parts[2])
        except ValueError:
            continue
        content = stdout[idx : idx + size]
        idx += size + 1  # trailing newline after content
        results[spec] = (sha, content)
    return results


def _commit_to_dict(commit: git.Commit) -> dict:
    msg = (
        commit.message
        if isinstance(commit.message, str)
        else bytes(commit.message).decode()
    )
    return {
        "hash": commit.hexsha,
        "short_hash": commit.hexsha[:7],
        "message": msg,
        "author": commit.author.name,
        "author_email": commit.author.email,
        "timestamp": commit.committed_datetime.isoformat(),
        "committed_date": commit.committed_date,
        "parent_hashes": [p.hexsha[:7] for p in commit.parents],
        "summary": msg.split("\n")[0],
    }


def get_file_history(
    repo: git.Repo,
    path: str,
    max_count: int = 100,
    storage: str | None = None,
) -> list[dict]:
    """Get commit history for a specific file path.

    Checks only the sources relevant to the artifact's ``storage`` class:

    - ``git``: only commits that touched the file itself.
    - ``dvc``: the file (legacy/pre-DVC history), the ``<path>.dvc`` pointer,
      and ``dvc.lock`` transitions for pipeline outputs.
    - ``dvc-zip``: the ``<path>.dvc`` pointer and ``dvc.lock``.
    - ``None`` (unknown): check everything — preserves the legacy behaviour.

    The ``dvc.lock`` scan only counts commits where *this* path's md5
    actually changed, and YAML parses are cached by blob SHA across all
    file-history requests.

    When ``storage`` is ``None`` the function infers it cheaply from the
    working tree before falling back to the full search:

    1. ``git ls-files <path>`` — file is git-tracked → ``"git"``
    2. ``<path>.dvc`` pointer file exists in the index → ``"dvc"``
    3. Neither → scan everything (legacy/unknown).

    Parameters
    ----------
    repo : git.Repo
        GitPython Repo object.
    path : str
        Repo-relative file path to look up.
    max_count : int
        Maximum number of commits to return.
    storage : str, optional
        One of ``"git"``, ``"dvc"``, ``"dvc-zip"``. Used to skip lookups
        that can't possibly produce results for this artifact.

    Returns
    -------
    list[dict]
        Commit dicts sorted newest-first.
    """
    if storage is None:
        # Check git index cheaply before touching dvc.lock
        try:
            if repo.git.ls_files(path):
                storage = "git"
            elif repo.git.ls_files(f"{path}.dvc"):
                storage = "dvc"
        except Exception:
            pass  # leave storage=None, fall back to full search
    head_sha = repo.head.commit.hexsha
    cache_key = (repo.working_dir, path, max_count, storage, head_sha)
    if cache_key in _FILE_HISTORY_CACHE:
        logger.info(f"Cache hit for file history: {path}")
        _FILE_HISTORY_CACHE.move_to_end(cache_key)
        return _FILE_HISTORY_CACHE[cache_key]
    check_file = storage in (None, "git", "dvc")
    check_dvc_pointer = storage in (None, "dvc", "dvc-zip")
    check_dvc_lock = storage in (None, "dvc", "dvc-zip")
    seen: set[str] = set()
    commits: list[dict] = []
    direct_paths: list[str] = []
    if check_file:
        direct_paths.append(path)
    if check_dvc_pointer:
        direct_paths.append(f"{path}.dvc")
    for direct_path in direct_paths:
        for c in _get_commits_for_paths(repo, max_count, [direct_path]):
            if c["hash"] not in seen:
                seen.add(c["hash"])
                commits.append(c)
    if check_dvc_lock:
        # Walk a few multiples of ``max_count`` so we still surface
        # transitions even when most dvc.lock commits don't touch this path,
        # but cap the absolute count to keep the YAML-parse loop bounded on
        # repos with very chatty dvc.lock histories.
        dvc_lock_walk = min(max_count * 4, 400)
        lock_commits = _get_commits_for_paths(
            repo, dvc_lock_walk, ["dvc.lock"]
        )
        # Resolve each commit's dvc.lock to a blob SHA up front (headers
        # only, no content), so revisions already in the parse cache from an
        # earlier request cost nothing to transfer.
        specs = [f"{c['hash']}:dvc.lock" for c in lock_commits]
        spec_shas = _batch_check_blobs(repo, specs)
        # Parse revisions lazily, newest first and in batches, so a request
        # that only needs the newest few transitions doesn't parse the whole
        # walk. Each parse is the expensive part, so this is what bounds the
        # cost by what's actually returned.
        md5_at: dict[int, str | None] = {}
        batch_size = 32

        def _md5_at(i: int) -> str | None:
            """``path``'s md5 in dvc.lock at ``lock_commits[i]``, or None."""
            if i in md5_at:
                return md5_at[i]
            # Fetch a window starting at i, skipping revisions we can already
            # answer from the cross-request parse cache.
            window = range(i, min(i + batch_size, len(lock_commits)))
            pending = []
            for j in window:
                if j in md5_at:
                    continue
                sha = spec_shas.get(f"{lock_commits[j]['hash']}:dvc.lock")
                if sha is None:
                    md5_at[j] = None
                    continue
                cached_outs = _peek_dvc_lock_outs(sha)
                if cached_outs is not None:
                    md5_at[j] = cached_outs.get(path) or None
                else:
                    pending.append((j, sha))
            if pending:
                # Two commits in the window can point at the same dvc.lock
                # blob (merges, reverts); read each distinct one once.
                blobs = _batch_read_blobs(
                    repo, list(dict.fromkeys(s for _, s in pending))
                )
                for j, sha in pending:
                    entry = blobs.get(sha)
                    if entry is None:
                        md5_at[j] = None
                        continue
                    outs = _parse_dvc_lock_outs(sha, lambda b=entry[1]: b)
                    md5_at[j] = outs.get(path) or None
            return md5_at.get(i)

        # Walk newest -> oldest. A commit is a transition when its md5 differs
        # from the nearest *older* revision that records one at all (None when
        # there is none, i.e. the path first appears here) -- the same rule
        # the previous oldest-first walk applied, but able to stop early.
        lock_hits: list[dict[str, Any]] = []
        for i in range(len(lock_commits)):
            current_hash = _md5_at(i)
            if not current_hash:
                continue
            prev_hash: str | None = None
            for j in range(i + 1, len(lock_commits)):
                older = _md5_at(j)
                if older:
                    prev_hash = older
                    break
            if current_hash != prev_hash:
                c = lock_commits[i]
                if c["hash"] not in seen:
                    seen.add(c["hash"])
                    lock_hits.append(c)
                    if len(lock_hits) >= max_count:
                        break
        commits.extend(lock_hits)
    commits.sort(key=lambda c: c["committed_date"], reverse=True)
    result = commits[:max_count]
    _FILE_HISTORY_CACHE[cache_key] = result
    if len(_FILE_HISTORY_CACHE) > _FILE_HISTORY_CACHE_MAX:
        _FILE_HISTORY_CACHE.popitem(last=False)
    return result


def get_commit_history(
    repo: git.Repo, max_count: int = 100, ref: str | None = None
) -> list[dict]:
    """Get detailed commit history for a repository.

    Parameters
    ----------
    repo : git.Repo
        GitPython Repo object.
    max_count : int
        Maximum number of commits to return.
    ref : str, optional
        Branch, tag, or commit to start from (defaults to HEAD).

    Returns
    -------
    list[dict]
        Commit dicts with hash, message, author, date, etc.
    """
    commits = []
    start = ref if ref else "HEAD"
    # If the ref doesn't exist locally, try the remote tracking branch
    candidates = [start]
    if ref:
        candidates.append(f"origin/{ref}")
    for candidate in candidates:
        try:
            for commit in repo.iter_commits(candidate, max_count=max_count):
                commits.append(
                    {
                        "hash": commit.hexsha,
                        "short_hash": commit.hexsha[:7],
                        "message": commit.message,
                        "author": commit.author.name,
                        "author_email": commit.author.email,
                        "timestamp": commit.committed_datetime.isoformat(),
                        "committed_date": commit.committed_date,
                        "parent_hashes": [
                            p.hexsha[:7] for p in commit.parents
                        ],
                        "summary": (
                            commit.message
                            if isinstance(commit.message, str)
                            else bytes(commit.message).decode()
                        ).split("\n")[0],
                    }
                )
            break
        except Exception as e:
            logger.warning(
                f"Failed to get commit history for {candidate}: {e}"
            )
    return commits


class RepoTree(ABC):
    """Read-only, path-based view over a set of files in a repository.

    ``WorkingTree`` and ``GitTree`` are the two concrete implementations.
    Adding a third (e.g., a bare-repo or remote-object-store backend) only
    requires subclassing here--callers need not change.
    """

    @abstractmethod
    def exists(self, path: str) -> bool: ...

    @abstractmethod
    def is_file(self, path: str) -> bool: ...

    @abstractmethod
    def is_dir(self, path: str | None) -> bool: ...

    @abstractmethod
    def is_symlink(self, path: str) -> bool: ...

    @abstractmethod
    def is_safe_symlink(self, path: str) -> bool:
        """True if the symlink at *path* resolves within this tree."""
        ...

    @abstractmethod
    def read_bytes(self, path: str) -> bytes: ...

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(path).decode(encoding)

    @abstractmethod
    def size(self, path: str) -> int: ...

    @abstractmethod
    def listdir(self, path: str | None) -> list[str]:
        """Immediate child names (not full paths) under *path*; None = root."""
        ...


class WorkingTree(RepoTree):
    """RepoTree backed by a live filesystem checkout.

    Unlike ``GitTree``, this reaches the filesystem, and paths arrive here
    from ``calkit.yaml`` and from request URLs. Every project's checkout
    sits beside every other one under ``CLONE_ROOT``, so a path that walks
    out of this repo walks into someone else's.
    """

    def __init__(self, root: str) -> None:
        self._root = root
        self._root_norm = os.path.normpath(root)
        # Kept apart from the normalized form: CLONE_ROOT may itself be a
        # symlink, so a resolved path needs a resolved root to compare to.
        try:
            self._root_real = os.path.realpath(root)
        except (OSError, ValueError):
            self._root_real = self._root_norm

    @staticmethod
    def _within(root: str, candidate: str) -> bool:
        return candidate == root or candidate.startswith(root + os.sep)

    @staticmethod
    def _is_repo_internal(path: str) -> bool:
        """Whether ``path`` names anything under a ``.git`` directory."""
        return ".git" in path.replace(os.sep, "/").split("/")

    def _abs(self, path: str | None) -> str | None:
        """Absolute path for ``path``, or ``None`` if it leaves the checkout.

        Lexical, so it costs no syscalls in the directory listings that call
        it once per entry; symlinks are ``is_safe_symlink``'s job.
        """
        if not path:
            return self._root
        # `.git` is the one thing this tree can see that ``GitTree`` cannot,
        # and it is repo plumbing rather than project content: the remote
        # URL, and whatever a legacy clone embedded in it.
        if self._is_repo_internal(path):
            logger.warning(f"Refusing to read repo internals: {path!r}")
            return None
        full = os.path.join(self._root, path)
        if not self._within(self._root_norm, os.path.normpath(full)):
            logger.warning(f"Refusing path outside {self._root}: {path!r}")
            return None
        return full

    def exists(self, path: str) -> bool:
        fpath = self._abs(path)
        return fpath is not None and os.path.exists(fpath)

    def is_file(self, path: str) -> bool:
        fpath = self._abs(path)
        return fpath is not None and os.path.isfile(fpath)

    def is_dir(self, path: str | None) -> bool:
        fpath = self._abs(path)
        return fpath is not None and os.path.isdir(fpath)

    def is_symlink(self, path: str) -> bool:
        fpath = self._abs(path)
        return fpath is not None and os.path.islink(fpath)

    def is_safe_symlink(self, path: str) -> bool:
        fpath = self._abs(path)
        if fpath is None:
            return False
        try:
            resolved = os.path.realpath(fpath)
            if not self._within(self._root_real, resolved):
                return False
            # Checked again on the resolved path: a symlink to `.git` is
            # inside the checkout, so containment alone lets it through.
            return not self._is_repo_internal(
                os.path.relpath(resolved, self._root_real)
            )
        except (OSError, ValueError):
            return False

    def read_bytes(self, path: str) -> bytes:
        fpath = self._abs(path)
        # Content is what leaves the machine, so this one also pays for a
        # resolved check: `..` isn't the only way out of the tree.
        if fpath is None or not self.is_safe_symlink(path):
            raise HTTPException(404)
        with open(fpath, "rb") as f:
            return f.read()

    def size(self, path: str) -> int:
        fpath = self._abs(path)
        if fpath is None:
            raise HTTPException(404)
        return os.path.getsize(fpath)

    def listdir(self, path: str | None) -> list[str]:
        fpath = self._abs(path)
        if fpath is None:
            raise HTTPException(404)
        return os.listdir(fpath)


_ODB_LOCK_ATTR = "_calkit_odb_lock"
_ODB_LOCK_GUARD = threading.Lock()


def odb_lock(repo: git.Repo) -> threading.RLock:
    """Return the lock serializing object-database reads for ``repo``.

    GitPython funnels every object read through a single persistent
    ``git cat-file --batch`` subprocess hanging off the repo's ``Git``
    instance, and ``Git.stream_object_data`` documents itself as not
    thread-safe. Concurrent readers interleave on that one pipe and either
    raise ("SHA ... could not be resolved") or deadlock on it outright, so
    any caller fanning tree reads across threads has to serialize them.

    Scoped to the ``Repo`` *instance*, not the repo directory: ``get_repo``
    builds a fresh ``Repo`` (and thus a fresh subprocess) per request, so
    keying on the directory would serialize unrelated requests for nothing.
    """
    with _ODB_LOCK_GUARD:
        lock = getattr(repo, _ODB_LOCK_ATTR, None)
        if lock is None:
            lock = threading.RLock()
            setattr(repo, _ODB_LOCK_ATTR, lock)
        return lock


class GitTree(RepoTree):
    """RepoTree that reads directly from git's object database.

    No working-tree checkout required--file content streams straight from
    blob objects. Suitable for browsing any historical ref without touching
    the filesystem beyond the git object store.

    Every method holds the repo's ``odb_lock`` for the duration of its git
    reads, which makes this class safe to share across a thread pool. The
    lock covers only the git access; callers that overlap slow object-storage
    work around these calls still get to run that part concurrently.
    """

    def __init__(self, repo: git.Repo, ref: str) -> None:
        self._lock = odb_lock(repo)
        with self._lock:
            self._git_tree = _resolve_commit(repo, ref).tree

    def _get(self, path: str) -> git.Blob | git.Tree:
        # Caller must hold self._lock: resolving a path walks intermediate
        # tree objects, each of which is an object-database read.
        try:
            return self._git_tree[path]  # type: ignore[return-value]
        except KeyError:
            raise KeyError(path)

    def exists(self, path: str) -> bool:
        with self._lock:
            try:
                self._get(path)
                return True
            except KeyError:
                return False

    def is_file(self, path: str) -> bool:
        with self._lock:
            try:
                e = self._get(path)
                return isinstance(e, git.Blob) and e.mode != _SYMLINK_MODE
            except KeyError:
                return False

    def is_dir(self, path: str | None) -> bool:
        if not path:
            return True  # root is always a tree
        with self._lock:
            try:
                return isinstance(self._get(path), git.Tree)
            except KeyError:
                return False

    def is_symlink(self, path: str) -> bool:
        with self._lock:
            try:
                e = self._get(path)
                return isinstance(e, git.Blob) and e.mode == _SYMLINK_MODE
            except KeyError:
                return False

    def is_safe_symlink(self, path: str) -> bool:
        with self._lock:
            try:
                e = self._get(path)
                if not isinstance(e, git.Blob) or e.mode != _SYMLINK_MODE:
                    return False
                target = e.data_stream.read().decode()
            except Exception:
                return False
        parent = posixpath.dirname(path)
        resolved = posixpath.normpath(posixpath.join(parent, target))
        return not resolved.startswith("..") and not posixpath.isabs(resolved)

    def read_bytes(self, path: str) -> bytes:
        with self._lock:
            return self._get(path).data_stream.read()

    def size(self, path: str) -> int:
        with self._lock:
            return self._get(path).size

    def listdir(self, path: str | None) -> list[str]:
        with self._lock:
            t = self._git_tree if not path else self._get(path)
            if not isinstance(t, git.Tree):
                raise NotADirectoryError(path)
            return [posixpath.basename(item.path) for item in t]


def _resolve_commit(repo: git.Repo, ref: str) -> git.Commit:
    """Resolve a branch, tag, or commit hash to a Commit object.

    A ref that's missing is the one case worth going to the network for.
    Clones are cached with a TTL, so anything pushed since the last fetch
    -- a new branch, or the head commit of a pull request -- reads as
    missing until that expires, even though it exists on GitHub.
    """

    def resolve() -> git.Commit | None:
        for candidate in (ref, f"origin/{ref}"):
            try:
                return repo.commit(candidate)
            except Exception:
                continue
        return None

    commit = resolve()
    if commit is not None:
        return commit
    # Anything that isn't a plain ref name is not worth handing to git,
    # if only to keep a leading dash from being read as an option
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", ref):
        try:
            # By SHA as well as by name: GitHub serves a commit that's
            # reachable from any ref, which covers a pull request head
            # that no local branch points at
            with _timed("fetch-ref", ref=ref):
                repo.git.fetch(
                    ["origin", ref],
                    kill_after_timeout=GIT_FETCH_TIMEOUT,
                )
        except GitCommandError as e:
            logger.info(f"Could not fetch ref '{ref}': {e}")
        else:
            commit = resolve()
            if commit is not None:
                return commit
    raise HTTPException(404, f"Git ref '{ref}' was not found")


def resolve_commit_sha(repo: git.Repo, ref: str | None) -> str | None:
    """Resolve *ref* (or HEAD when None) to a full commit SHA, or None.

    Used as a content token for caching: the SHA changes whenever any tracked
    file does. Never raises -- returns None when the ref can't be resolved.
    """
    try:
        if ref:
            return _resolve_commit(repo, ref).hexsha
        return repo.head.commit.hexsha
    except Exception:
        return None


def get_repo_tree_for_ref(repo: git.Repo, ref: str | None) -> RepoTree:
    """Return a ``RepoTree`` for *ref*.

    ``None`` returns a ``WorkingTree`` over the live checkout.  Any other
    value returns a ``GitTree`` that reads straight from the object database
    with no filesystem extraction.
    """
    if ref is None:
        return WorkingTree(str(repo.working_dir))
    if not ref or ref.startswith("-") or any(c in ref for c in " \t\n\r\x00"):
        raise HTTPException(400, f"Invalid Git ref: {ref!r}")
    return GitTree(repo, ref)
