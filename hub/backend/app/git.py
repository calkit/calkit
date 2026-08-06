"""Functionality for working with Git."""

import atexit
import json
import os
import posixpath
import shutil
import stat
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from contextlib import contextmanager

import calkit
import git
from fastapi import HTTPException
from filelock import FileLock, Timeout
from git.exc import GitCommandError
from ruamel.yaml import YAMLError
from sqlmodel import Session, select

from app import github, users
from app.core import logger, ryaml
from app.models import GitRef, Project, User, UserProjectAccess

_SYMLINK_MODE = 0o120000

# Max seconds a single git network subprocess may run before being killed,
# so a stalled remote can't wedge a worker indefinitely. Clone gets a
# larger budget than fetch since initial clones of large repos are
# legitimately slower.
GIT_CLONE_TIMEOUT = 300
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


def get_repo(
    project: Project,
    user: User | None,
    session: Session,
    ttl: int | None = None,
    fresh=False,
    ref: str | None = None,
) -> git.Repo:
    """Ensure that the repo exists and is ready for operating upon for the user.

    Handles concurrency in case multiple API calls request the repo
    simultaneously. If TTL is None, the latest version is always fetched.
    """
    owner_name = project.owner_github_name
    project_name = project.name
    # Add the file to the repo(s) -- we may need to clone it.
    # Ref-based reads should not mutate this working tree checkout.
    if user is not None:
        # github_username is None for GitHub-less users; fall back to the
        # (always-present, unique) account name for a stable temp path.
        user_dir = user.github_username or user.account.name
        base_dir = f"/tmp/{user_dir}/{owner_name}/{project_name}"
    else:
        base_dir = f"/tmp/anonymous/{owner_name}/{project_name}"
    repo_dir = os.path.join(base_dir, "repo")
    updated_fpath = os.path.join(base_dir, "updated.txt")
    lock_fpath = os.path.join(base_dir, "updating.lock")
    lock = FileLock(lock_fpath, timeout=5)
    os.makedirs(base_dir, exist_ok=True)
    if os.path.isdir(repo_dir) and fresh:
        logger.info("Deleting repo directory to clone a fresh copy")
        shutil.rmtree(repo_dir, ignore_errors=True)
    # Clone the repo if it doesn't exist -- it will be in a "repo" dir
    access_token: str | None = None
    if user is not None:
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
    if not os.path.isdir(repo_dir):
        newly_cloned = True
        logger.info(f"Git cloning into {repo_dir}")
        try:
            with lock:
                try:
                    clone_cmd = ["git", "clone", git_plain_url, repo_dir]
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
                    # It's possible another process cloned this repo just as
                    # we were about to, so check again
                    if not os.path.isdir(repo_dir):
                        raise HTTPException(404, "Git repo not found")
                # Touch a file so we can compute a TTL
                subprocess.check_call(["touch", updated_fpath])
                repo = git.Repo(repo_dir)
        except Timeout:
            logger.warning("Git repo lock timed out")
    if os.path.isfile(updated_fpath):
        last_updated = os.path.getmtime(updated_fpath)
    else:
        last_updated = 0
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
                if not is_shallow:
                    logger.info("Git fetching")
                    if ref is None:
                        branch_name = repo.active_branch.name
                        with _timed(
                            "fetch", repo=repo_label, branch=branch_name
                        ):
                            repo.git.fetch(
                                ["origin", branch_name],
                                kill_after_timeout=GIT_FETCH_TIMEOUT,
                            )
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
    if user is not None and did_refresh:
        _configure_committer(repo, user, session=session)
    return repo


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


def get_ck_info_from_repo(repo: git.Repo, process_includes=False) -> dict:
    try:
        ck_info = calkit.load_calkit_info(
            wdir=repo.working_dir, process_includes=process_includes
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
    if ck_info is None:
        ck_info = {}
    return ck_info


def get_ck_info(
    project: Project,
    user: User | None,
    session: Session,
    ttl=None,
    process_includes=False,
    ref: str | None = None,
) -> dict:
    """Load the calkit.yaml file contents into a dictionary."""
    repo = get_repo(
        project=project,
        user=user,
        session=session,
        ttl=ttl,
        ref=ref,
    )
    return get_ck_info_from_repo(repo=repo, process_includes=process_includes)


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


def get_dvc_pipeline_from_repo(repo: git.Repo) -> dict:
    if os.path.isfile(os.path.join(repo.working_dir, "dvc.yaml")):
        with open(os.path.join(repo.working_dir, "dvc.yaml")) as f:
            return ryaml.load(f)
    else:
        return {}


def get_overleaf_repo(
    project: Project, user: User, session: Session, overleaf_project_id: str
) -> git.Repo:
    """Get a freshly pulled Overleaf repository for a user/project."""
    owner_name, project_name = project.owner_github_name, project.name
    base_dir = (
        f"/tmp/{user.github_username}/{owner_name}/"
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


def _parse_dvc_lock_outs(blob_sha: str, read_bytes) -> dict[str, str]:
    """Return {out_path: md5} for a dvc.lock blob, caching by blob SHA.

    ``read_bytes`` is a zero-arg callable returning the blob contents, only
    invoked on cache miss so batched callers don't pay the cost twice.
    """
    cached = _DVC_LOCK_PARSE_CACHE.get(blob_sha)
    if cached is not None:
        _DVC_LOCK_PARSE_CACHE.move_to_end(blob_sha)
        return cached
    try:
        data = ryaml.load(read_bytes()) or {}
    except Exception:
        data = {}
    outs: dict[str, str] = {}
    for stage in (data.get("stages") or {}).values():
        for out in stage.get("outs") or []:
            p = out.get("path")
            if not p:
                continue
            outs[p] = out.get("md5") or out.get("hash") or ""
    _DVC_LOCK_PARSE_CACHE[blob_sha] = outs
    if len(_DVC_LOCK_PARSE_CACHE) > _DVC_LOCK_PARSE_CACHE_MAX:
        _DVC_LOCK_PARSE_CACHE.popitem(last=False)
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
        specs = [f"{c['hash']}:dvc.lock" for c in lock_commits]
        blobs = _batch_read_blobs(repo, specs)
        # Walk oldest -> newest to detect md5 transitions for ``path``.
        prev_hash: str | None = None
        for c in reversed(lock_commits):
            entry = blobs.get(f"{c['hash']}:dvc.lock")
            if entry is None:
                continue
            blob_sha, content = entry
            outs = _parse_dvc_lock_outs(blob_sha, lambda b=content: b)
            current_hash = outs.get(path) if outs else None
            if current_hash and current_hash != prev_hash:
                if c["hash"] not in seen:
                    seen.add(c["hash"])
                    commits.append(c)
            if current_hash:
                prev_hash = current_hash
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
    """RepoTree backed by a live filesystem checkout."""

    def __init__(self, root: str) -> None:
        self._root = root

    def _abs(self, path: str | None) -> str:
        return self._root if not path else os.path.join(self._root, path)

    def exists(self, path: str) -> bool:
        return os.path.exists(self._abs(path))

    def is_file(self, path: str) -> bool:
        return os.path.isfile(self._abs(path))

    def is_dir(self, path: str | None) -> bool:
        return os.path.isdir(self._abs(path))

    def is_symlink(self, path: str) -> bool:
        return os.path.islink(self._abs(path))

    def is_safe_symlink(self, path: str) -> bool:
        try:
            resolved = os.path.realpath(self._abs(path))
            root_real = os.path.realpath(self._root)
            return (
                resolved.startswith(root_real + os.sep)
                or resolved == root_real
            )
        except (OSError, ValueError):
            return False

    def read_bytes(self, path: str) -> bytes:
        with open(self._abs(path), "rb") as f:
            return f.read()

    def size(self, path: str) -> int:
        return os.path.getsize(self._abs(path))

    def listdir(self, path: str | None) -> list[str]:
        return os.listdir(self._abs(path))


class GitTree(RepoTree):
    """RepoTree that reads directly from git's object database.

    No working-tree checkout required--file content streams straight from
    blob objects. Suitable for browsing any historical ref without touching
    the filesystem beyond the git object store.
    """

    def __init__(self, repo: git.Repo, ref: str) -> None:
        self._git_tree = _resolve_commit(repo, ref).tree

    def _get(self, path: str) -> git.Blob | git.Tree:
        try:
            return self._git_tree[path]  # type: ignore[return-value]
        except KeyError:
            raise KeyError(path)

    def exists(self, path: str) -> bool:
        try:
            self._get(path)
            return True
        except KeyError:
            return False

    def is_file(self, path: str) -> bool:
        try:
            e = self._get(path)
            return isinstance(e, git.Blob) and e.mode != _SYMLINK_MODE
        except KeyError:
            return False

    def is_dir(self, path: str | None) -> bool:
        if not path:
            return True  # root is always a tree
        try:
            return isinstance(self._get(path), git.Tree)
        except KeyError:
            return False

    def is_symlink(self, path: str) -> bool:
        try:
            e = self._get(path)
            return isinstance(e, git.Blob) and e.mode == _SYMLINK_MODE
        except KeyError:
            return False

    def is_safe_symlink(self, path: str) -> bool:
        try:
            e = self._get(path)
            if not isinstance(e, git.Blob) or e.mode != _SYMLINK_MODE:
                return False
            target = e.data_stream.read().decode()
            parent = posixpath.dirname(path)
            resolved = posixpath.normpath(posixpath.join(parent, target))
            return not resolved.startswith("..") and not posixpath.isabs(
                resolved
            )
        except Exception:
            return False

    def read_bytes(self, path: str) -> bytes:
        return self._get(path).data_stream.read()

    def size(self, path: str) -> int:
        return self._get(path).size

    def listdir(self, path: str | None) -> list[str]:
        t = self._git_tree if not path else self._get(path)
        if not isinstance(t, git.Tree):
            raise NotADirectoryError(path)
        return [posixpath.basename(item.path) for item in t]


def _resolve_commit(repo: git.Repo, ref: str) -> git.Commit:
    """Resolve a branch, tag, or commit hash to a Commit object."""
    for candidate in (ref, f"origin/{ref}"):
        try:
            return repo.commit(candidate)
        except Exception:
            continue
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
