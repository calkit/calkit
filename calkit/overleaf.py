"""Functionality for working with Overleaf."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import warnings
from contextlib import contextmanager
from copy import deepcopy
from functools import cached_property
from os import PathLike
from pathlib import Path
from typing import Any, Callable, Iterator

import git

import calkit

PRIVATE_KEYS = ["project_id", "last_sync_commit"]


def get_git_remote_url(project_id: str, token: str) -> str:
    """Form the Git remote URL for an Overleaf project.

    If running against a test environment, this will use a local directory.
    """
    if calkit.config.get_env() == "test":
        return (
            Path(tempfile.gettempdir()) / "overleaf" / project_id
        ).as_posix()
    return f"https://git:{token}@git.overleaf.com/{project_id}"


# Git config options that force authentication to use only the token embedded
# in the Overleaf remote URL, never a credential saved in the operating
# system's credential store (macOS Keychain, Windows Credential Manager, etc.).
# An expired token can linger in that store and shadow a freshly set one, which
# otherwise makes it impossible to recover a project after a token expires.
_CREDENTIAL_CLONE_OPTIONS = [
    "-c credential.helper=",
    "-c credential.interactive=false",
]


def _disable_credential_store(repo: git.Repo) -> None:
    """Configure a cloned Overleaf repo so git authenticates only with the
    token embedded in its remote URL, ignoring the OS credential store.

    Setting an empty ``credential.helper`` in the repo's local config resets
    the list of helpers inherited from the system and global config, so no
    stale token can be read from (or written to) the credential store.
    """
    repo.git.config("credential.helper", "")
    repo.git.config("credential.interactive", "false")


def rmtree(path: str) -> None:
    """Remove a directory, including Git's read-only object files, which
    Windows won't delete otherwise.
    """

    def make_writable(func: Callable, p: str, _: Any) -> None:
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=make_writable)
    else:
        shutil.rmtree(path, onerror=make_writable)


def get_project_dir(project_id: str) -> str:
    """Return the local directory into which an Overleaf project is cloned,
    relative to the Calkit project working directory.
    """
    return os.path.join(".calkit", "overleaf", project_id)


class AuthError(RuntimeError):
    """Overleaf rejected the token, e.g., because it expired or was revoked."""


class ChangedOnOverleafError(RuntimeError):
    """Files changed on Overleaf between downloading and replacing them."""


# Added to the error when Overleaf rejects the token
AUTH_FAILED_ADVICE = (
    "Your Overleaf token may have expired or been revoked. Generate a new one "
    "under 'Git Integration' at https://www.overleaf.com/user/settings and "
    "set it with 'calkit config set overleaf_token'."
)


def _git_error(e: git.GitCommandError, action: str) -> RuntimeError:
    """Turn a failed clone or fetch from Overleaf into an error that shows
    Git's message, without the token, and advice for authentication failures.
    """
    import re

    # Never show the token embedded in the remote URL
    details = re.sub(r"://[^/@\s]+@", "://", str(e.stderr)).strip()
    msg = f"Failed to {action} from Overleaf:\n{details}"
    auth_errors = [
        "authentication failed",
        "could not read username",
        "returned error: 401",
        "returned error: 403",
    ]
    if any(err in details.lower() for err in auth_errors):
        return AuthError(msg + "\n" + AUTH_FAILED_ADVICE)
    return RuntimeError(msg)


def clone(project_id: str, token: str) -> git.Repo:
    """Clone an Overleaf project, authenticating only with ``token``."""
    try:
        repo = git.Repo.clone_from(
            get_git_remote_url(project_id=project_id, token=token),
            get_project_dir(project_id),
            multi_options=_CREDENTIAL_CLONE_OPTIONS,
            allow_unsafe_options=True,
        )
    except git.GitCommandError as e:
        raise _git_error(e, "clone")
    _disable_credential_store(repo)
    return repo


@contextmanager
def lock(
    project_id: str, print_info: Callable[[str], None] = print
) -> Iterator[None]:
    """Hold an exclusive lock on the local clone of an Overleaf project.

    Syncs reset the clone and copy files into it, so two at once could wipe
    each other's files or record Overleaf edits as synced without pulling
    them. The OS releases the lock if its process dies, so it can't go stale.
    """
    from filelock import FileLock, Timeout

    lock_path = get_project_dir(project_id) + ".lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    file_lock = FileLock(lock_path)
    try:
        file_lock.acquire(timeout=0)
    except Timeout:
        print_info("Waiting for another Overleaf sync of this project")
        file_lock.acquire()
    try:
        yield
    finally:
        file_lock.release()


def get_repo(project_id: str, token: str) -> git.Repo:
    """Return the Overleaf repo for ``project_id``, cloning it if it does not
    yet exist.

    When the repo already exists, its remote URL is refreshed so a freshly set
    token takes effect, and credential handling is reset so a stale token from
    the OS credential store is never used.
    """
    dest = get_project_dir(project_id)
    # Re-clone a cache missing its own .git, since opening it would find the
    # main project repo in a parent directory instead
    if os.path.isdir(dest) and not os.path.exists(os.path.join(dest, ".git")):
        rmtree(dest)
    # A mirror kept by session sync has no remote to pull from
    if os.path.isdir(dest):
        with git.Repo(dest) as existing:
            is_mirror_dir = not existing.remotes
        if is_mirror_dir:
            rmtree(dest)
    if not os.path.isdir(dest):
        return clone(project_id, token)
    repo = git.Repo(dest)
    repo.git.remote(
        "set-url",
        "origin",
        get_git_remote_url(project_id=project_id, token=token),
    )
    _disable_credential_store(repo)
    return repo


def pull(repo: git.Repo) -> None:
    """Update the local clone of an Overleaf project to match Overleaf.

    The clone is only a cache, so anything left in it by an interrupted or
    failed sync, e.g., a commit whose push was rejected, is discarded rather
    than merged, since merging can fail and block every later pull.
    """
    try:
        repo.git.fetch("origin")
    except git.GitCommandError as e:
        raise _git_error(e, "pull")
    repo.git.reset("--hard", "@{upstream}")
    repo.git.clean("-fdx")
    # Left if the clone was synced with a session while its token didn't
    # work, and would make it look like a mirror
    if is_mirror(repo):
        repo.git.update_ref("-d", MIRROR_REF)


OVERLEAF_URL = "https://www.overleaf.com"
SESSION_COOKIE = "overleaf_session2"
# Where a session-synced mirror records the commit matching Overleaf's files,
# like a remote-tracking branch does for a Git integration clone
MIRROR_REF = "refs/calkit/overleaf"
# What a sync names the project commit recording it, given the synced folder
SYNC_COMMIT_MESSAGE = "Sync {} with Overleaf project"

SESSION_HELP = (
    "Copy the value of the 'overleaf_session2' cookie from a browser signed "
    "in to overleaf.com: open developer tools, then go to Application > "
    "Cookies (Chrome, Edge) or Storage > Cookies (Firefox)."
)

SESSION_REJECTED_ADVICE = (
    "Your Overleaf session may have expired, e.g., by signing out of "
    "overleaf.com, or you may not have edit access to this project. "
    "Sign in again with 'calkit overleaf login', or reconnect from the "
    "Calkit browser extension on overleaf.com."
)


class WebClient:
    """Access Overleaf projects with a browser session, the same way the
    editor does, so syncing doesn't require Git integration, which is an
    Overleaf Premium feature.

    Follows https://github.com/moritzgloeckl/overleaf-sync, updated for
    Overleaf's current realtime API.
    """

    def __init__(self, session: str, url: str = OVERLEAF_URL) -> None:
        import requests

        self.url = url.rstrip("/")
        self.http = requests.Session()
        self.http.headers["User-Agent"] = f"calkit/{calkit.__version__}"
        self.session = session.strip().removeprefix(f"{SESSION_COOKIE}=")
        self.http.cookies.set(SESSION_COOKIE, self.session)

    def _check(self, resp: Any, action: str) -> None:
        # A missing or expired session redirects to the login page
        if resp.status_code in (401, 403) or "/login" in resp.url:
            raise AuthError(
                f"Overleaf rejected the session when trying to {action}.\n"
                + SESSION_REJECTED_ADVICE
            )
        if not resp.ok:
            raise RuntimeError(
                f"Failed to {action} on Overleaf (HTTP {resp.status_code})"
            )

    @cached_property
    def csrf_token(self) -> str:
        """The token Overleaf requires on requests that change a project,
        which also checks the session is signed in.
        """
        import re

        resp = self.http.get(f"{self.url}/project", timeout=60)
        self._check(resp, "sign in")
        match = re.search(
            r'<meta\s+name="ol-csrfToken"\s+content="([^"]+)"', resp.text
        )
        if match is None:
            raise AuthError(
                "Overleaf didn't recognize the session.\n"
                + SESSION_REJECTED_ADVICE
            )
        return match.group(1)

    def download(self, project_id: str) -> bytes:
        """Download a project's files as a zip archive."""
        resp = self.http.get(
            f"{self.url}/project/{project_id}/download/zip", timeout=300
        )
        self._check(resp, "download the project")
        if not resp.content.startswith(b"PK"):
            raise AuthError(
                "Overleaf didn't send the project's files.\n"
                + SESSION_REJECTED_ADVICE
            )
        content: bytes = resp.content
        return content

    def get_root_folder(self, project_id: str) -> dict:
        """Get the project's file tree, which has the IDs needed to upload
        and delete files.

        Overleaf only sends it to an editor connecting over its socket.io
        (v0.9) realtime API, which is spoken here over long polling, so
        nothing beyond ``requests`` is needed.
        """
        import time

        def get(url: str) -> Any:
            params = {
                "projectId": project_id,
                "t": str(int(time.time() * 1e3)),
            }
            resp = self.http.get(url, params=params, timeout=60)
            self._check(resp, "open the project")
            return resp

        base = f"{self.url}/socket.io/1"
        sid = get(base + "/").text.split(":")[0]
        poll_url = f"{base}/xhr-polling/{sid}"
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                text = get(poll_url).text
                # Several messages in one response are each framed by their
                # length between U+FFFD markers
                if text.startswith("\ufffd"):
                    msgs = text.split("\ufffd")[2::2]
                else:
                    msgs = [text]
                for msg in msgs:
                    if msg.startswith("2:"):
                        # Heartbeats need answering to stay connected
                        self.http.post(poll_url, data="2::", timeout=60)
                    elif msg.startswith(("0:", "7:")):
                        raise RuntimeError(
                            "Overleaf closed the connection to the project: "
                            + msg
                        )
                    elif msg.startswith("5:"):
                        event = json.loads(msg.split(":", 3)[3])
                        if event.get("name") == "joinProjectResponse":
                            project = event["args"][0]["project"]
                            root: dict = project["rootFolder"][0]
                            return root
                        if event.get("name") == "connectionRejected":
                            raise AuthError(
                                "Overleaf refused to open the project: "
                                f"{event.get('args')}\n"
                                + SESSION_REJECTED_ADVICE
                            )
            raise RuntimeError("Timed out waiting for Overleaf's file list")
        finally:
            try:
                self.http.post(poll_url, data="0::", timeout=10)
            except Exception:
                pass

    def upload(
        self, project_id: str, root_folder_id: str, path: str, content: bytes
    ) -> None:
        """Create or replace a file, creating any folders it's in."""
        name = path.split("/")[-1]
        form = {"name": name}
        if "/" in path:
            form["relativePath"] = path
        resp = self.http.post(
            f"{self.url}/project/{project_id}/upload",
            params={"folder_id": root_folder_id},
            data=form,
            files={"qqfile": (name, content, "application/octet-stream")},
            headers={"X-CSRF-Token": self.csrf_token},
            timeout=300,
        )
        self._check(resp, f"upload {path}")
        body = resp.json()
        if not body.get("success"):
            raise RuntimeError(
                f"Overleaf rejected {path}: {body.get('error', body)}"
            )

    def delete(
        self, project_id: str, entity_type: str, entity_id: str
    ) -> None:
        """Delete a doc, file, or folder by ID."""
        resp = self.http.delete(
            f"{self.url}/project/{project_id}/{entity_type}/{entity_id}",
            headers={"X-CSRF-Token": self.csrf_token},
            timeout=60,
        )
        self._check(resp, "delete a file")


def get_mirror(project_id: str, dest: str | None = None) -> git.Repo:
    """Return the local Git mirror of an Overleaf project synced with a
    session, creating it if necessary, by default in ``get_project_dir``.

    Calkit writes this repo's history itself, one commit per change seen on
    Overleaf, so the sync works the same as with a Git integration clone,
    which serves as a mirror just as well if one is already there.
    """
    if dest is None:
        dest = get_project_dir(project_id)
    # Opening a directory without its own .git would find the main project
    # repo in a parent directory instead
    if os.path.isdir(dest) and not os.path.exists(os.path.join(dest, ".git")):
        rmtree(dest)
    if not os.path.isdir(dest):
        return git.Repo.init(dest)
    return git.Repo(dest)


def pull_mirror(repo: git.Repo, client: WebClient, project_id: str) -> None:
    """Commit Overleaf's current files to the mirror if they've changed.

    Anything left by a sync that failed partway is discarded first, as with
    ``pull``.
    """
    import io
    import zipfile

    archive = zipfile.ZipFile(io.BytesIO(client.download(project_id)))
    if repo.head.is_valid():
        repo.git.reset("--hard", MIRROR_REF if is_mirror(repo) else "HEAD")
        repo.git.rm("-r", "-q", "--cached", "--ignore-unmatch", ".")
    repo.git.clean("-fdx")
    root = Path(str(repo.working_dir)).resolve()
    for entry in archive.infolist():
        dest = (root / entry.filename).resolve()
        # Never write outside the mirror or into its .git
        if entry.is_dir() or root not in dest.parents:
            continue
        if dest.relative_to(root).parts[0] == ".git":
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(archive.read(entry))
    # Everything is tracked, even what an Overleaf .gitignore would exclude,
    # as the Git integration does
    repo.git.add("-A", "-f")
    if not repo.head.is_valid() or repo.git.diff("--staged"):
        repo.git.commit("--allow-empty", "-m", "Update on Overleaf.")
    # Rewritten as a checkout would write them, so line endings on disk match
    # the project's, e.g., with core.autocrlf on Windows
    repo.git.read_tree("HEAD")
    repo.git.checkout_index("-a", "-f", "-u")
    repo.git.update_ref(MIRROR_REF, "HEAD")


def is_mirror(repo: git.Repo) -> bool:
    """Whether a repo is kept up to date by ``pull_mirror``."""
    try:
        repo.git.rev_parse("--verify", "--quiet", MIRROR_REF)
        return True
    except git.GitCommandError:
        return False


def push_mirror(repo: git.Repo, client: WebClient, project_id: str) -> None:
    """Send what's been committed to the mirror since it last matched
    Overleaf.

    Overleaf can't be told to write a file only if it's unchanged, so this
    first checks that nobody has edited the files about to be replaced or
    deleted since they were downloaded, raising if so, as ``git push`` would.
    """
    import io
    import zipfile

    changes = repo.git.diff(
        "--name-status", "--no-renames", "-z", MIRROR_REF, "HEAD"
    ).split("\0")
    if changes == [""]:
        return
    archive = zipfile.ZipFile(io.BytesIO(client.download(project_id)))
    names = {e.filename for e in archive.infolist() if not e.is_dir()}
    synced = repo.commit(MIRROR_REF).tree
    edited = []
    for path in changes[1::2]:
        try:
            before: str | None = (synced / path).hexsha
        except KeyError:
            before = None
        now = None
        if path in names:
            # Hashed as 'git add' stored it, so line ending conversion
            # doesn't look like an edit
            now = (
                subprocess.run(
                    ["git", "hash-object", "--stdin", "--path", path],
                    input=archive.read(path),
                    cwd=repo.working_dir,
                    capture_output=True,
                    check=True,
                )
                .stdout.decode()
                .strip()
            )
        if now != before:
            edited.append(path)
    if edited:
        raise ChangedOnOverleafError(
            "These files changed on Overleaf during the sync, so nothing was "
            f"sent: {', '.join(edited)}. Sync again to merge those changes."
        )
    root = client.get_root_folder(project_id)
    head = repo.head.commit.tree
    for status, path in zip(changes[::2], changes[1::2]):
        if status == "D":
            entity = _find_entity(root, path)
            if entity is not None:
                client.delete(project_id, *entity)
            continue
        # What was committed, as 'git push' would send, so line endings are
        # normalized the same way
        content = (head / path).data_stream.read()
        client.upload(project_id, root["_id"], path, content)
    repo.git.update_ref(MIRROR_REF, "HEAD")


def _find_entity(folder: dict, path: str) -> tuple[str, str] | None:
    """Find the type and ID of a doc or file in an Overleaf file tree."""
    *dirs, name = path.split("/")
    for d in dirs:
        sub = [f for f in folder.get("folders", []) if f["name"] == d]
        if not sub:
            return None
        folder = sub[0]
    for kind, key in (("doc", "docs"), ("file", "fileRefs")):
        for entity in folder.get(key, []):
            if entity["name"] == name:
                return kind, entity["_id"]
    return None


def ensure_sync_base(
    repo: git.Repo,
    main_repo: git.Repo,
    path_in_project: str,
    last_sync_commit: str | None,
    print_info: Callable[[str], None] = print,
    missing_ok: bool = False,
) -> str | None:
    """Make sure the Overleaf repo's history has the commit a sync is based
    on, returning the commit to use.

    A mirror's history is local, and a clone's comes from Overleaf, so a
    checkpoint recorded on another machine, or with the other kind of
    credentials, may be missing. What Overleaf held then is rebuilt from the
    project commit that recorded the checkpoint, when the synced folder
    matched it, and inserted beneath Overleaf's current files. A clone's
    branch then no longer follows Overleaf's, so ``sync`` puts its commit on
    top of Overleaf's before pushing.

    Files the sync sends to Overleaf that Git doesn't hold are added too:
    map-paths copies are rebuilt from their sources at that commit, and
    anything else, e.g., files stored with DVC, is taken as unchanged on
    Overleaf, so neither looks newly added there. Files the sync never sends,
    e.g., dot files, are left out unless Overleaf has them now, so they don't
    look deleted there.

    The rebuilt commit is kept under a ref, so it's only built once.

    Without a base, a sync would copy Overleaf's files over the project's,
    so if none can be found this raises, or, with ``missing_ok``, which is
    for read-only checks, returns None.
    """
    from gitdb import IStream  # type: ignore[import-untyped]

    def store(obj: Any) -> None:
        stream = IStream(str(obj.type).encode(), obj.size, obj.data_stream)
        repo.odb.store(stream)

    def blob_at(tree: git.Tree, path: str) -> git.Blob | None:
        try:
            obj = tree / path
        except KeyError:
            return None
        return obj if isinstance(obj, git.Blob) else None

    def in_history(rev: str) -> bool:
        try:
            repo.git.merge_base("--is-ancestor", rev, head.hexsha)
            return True
        except git.GitCommandError:
            return False

    def info_at(sha: str) -> dict:
        try:
            info = json.loads(main_repo.git.show(f"{sha}:{fpath}"))
        except (git.GitCommandError, ValueError):
            return {}
        return info.get(key) or {}

    def build_base() -> str:
        """Rebuild what Overleaf held at the last sync, raising
        ``LookupError`` if that can't be known.
        """
        # The commit where this folder's checkpoint was set, rather than the
        # latest one mentioning it, which may have moved on since
        recorded = None
        for sha in main_repo.git.log(
            "--format=%H", f"-S{last_sync_commit}", "--", fpath
        ).split():
            commit = main_repo.commit(sha)
            if info_at(sha).get(
                "last_sync_commit"
            ) == last_sync_commit and all(
                info_at(p.hexsha).get("last_sync_commit") != last_sync_commit
                for p in commit.parents
            ):
                recorded = commit
                break
        if recorded is None:
            raise LookupError(
                f"Could not find the last sync of {key} with Overleaf in the "
                "project history, so changes on each side can't be told apart"
            )
        # Only a commit Calkit made for the sync or import is known to hold
        # just what was on Overleaf, e.g., not one made by hand after syncing
        # with --no-commit
        subject = str(recorded.message).strip()
        project_id = info_at(recorded.hexsha).get("project_id")
        if subject != SYNC_COMMIT_MESSAGE.format(key) and not (
            subject.startswith(f"Import Overleaf project ID {project_id}")
        ):
            raise LookupError(
                f"The last sync of {key} with Overleaf was saved in commit "
                f"{recorded.hexsha[:7]}, which Calkit didn't make, so it may "
                "include changes that were never on Overleaf"
            )
        tree: Any = recorded.tree
        try:
            if prefix:
                tree = tree / prefix
        except KeyError:
            tree = None
        if not isinstance(tree, git.Tree):
            raise LookupError(
                f"The last sync of {key} with Overleaf was saved in commit "
                f"{recorded.hexsha[:7]}, which doesn't have that folder"
            )
        print_info("Rebuilding the last sync from project history")
        # Git objects are the same in any repo, so the folder's tree can be
        # copied over as is
        for obj in [tree, *tree.traverse()]:
            if isinstance(obj, (git.Blob, git.Tree)):
                store(obj)
        paths = OverleafSyncPaths(
            main_repo=main_repo,
            overleaf_repo=repo,
            path_in_project=path_in_project,
            sync_info_for_path={},
        )
        sources = paths.map_paths_sources
        # Files the sync never sends, e.g., dot files and the PDF, were only
        # on Overleaf if they're there now, or they'd look deleted there
        pushed = set(paths.files_to_copy_to_overleaf)
        dropped = [
            rel
            for rel in main_repo.git.ls_tree(
                "-r", "-z", "--name-only", tree.hexsha
            ).split("\0")
            if rel and rel not in pushed and blob_at(head.tree, rel) is None
        ]
        extra = {}
        for rel in sorted(paths.dvc_files | paths.mapped_files | set(sources)):
            if blob_at(tree, rel) is not None:
                continue
            blob = None
            if rel in sources:
                blob = blob_at(recorded.tree, sources[rel])
                if blob is not None:
                    store(blob)
            if blob is None:
                blob = blob_at(head.tree, rel)
            if blob is not None:
                extra[rel] = blob
        base_tree = tree.hexsha
        if extra or dropped:
            with tempfile.TemporaryDirectory() as tmp:
                env = {"GIT_INDEX_FILE": os.path.join(tmp, "index")}
                repo.git.read_tree(base_tree, env=env)
                if dropped:
                    repo.git.update_index(
                        "--force-remove", "--", *dropped, env=env
                    )
                for rel, blob in extra.items():
                    repo.git.update_index(
                        "--add",
                        "--cacheinfo",
                        f"{blob.mode:o},{blob.hexsha},{rel}",
                        env=env,
                    )
                base_tree = repo.git.write_tree(env=env)
        parents = [p for c in head.parents for p in ("-p", c.hexsha)]
        built: str = repo.git.commit_tree(
            base_tree, *parents, "-m", "Overleaf at last sync"
        )
        return built

    if not last_sync_commit:
        return last_sync_commit
    head = repo.head.commit
    if in_history(last_sync_commit):
        return last_sync_commit
    base_ref = f"refs/calkit/sync-base/{last_sync_commit}"
    try:
        base: str | None = repo.git.rev_parse("--verify", "--quiet", base_ref)
    except git.GitCommandError:
        base = None
    if base is not None and in_history(base):
        return base
    fpath = Path(get_sync_info_fpath()).as_posix()
    key = Path(path_in_project).as_posix()
    prefix = "" if key == "." else key.strip("/")
    if base is None:
        try:
            base = build_base()
        except LookupError as e:
            if missing_ok:
                print_info(f"Warning: {e}")
                return None
            raise RuntimeError(
                f"{e}. To start over, commit any changes, remove "
                f"'last_sync_commit' for this folder from {fpath}, and sync "
                "again; that copies Overleaf's files over the project's, so "
                "review the diff before committing."
            )
        repo.git.update_ref(base_ref, base)
    assert base is not None
    new_head = repo.git.commit_tree(
        head.tree.hexsha, "-p", base, "-m", head.message
    )
    repo.git.update_ref("HEAD", new_head)
    if is_mirror(repo):
        repo.git.update_ref(MIRROR_REF, new_head)
    return base


def project_id_to_url(project_id: str) -> str:
    return f"https://www.overleaf.com/project/{project_id}"


def project_id_from_url(url: str) -> str:
    return url.split("/")[-1]


def get_sync_info(
    wdir: str | PathLike | None = None,
    ck_info: dict | None = None,
    fix_legacy: bool = False,
    print_info: Callable[[str], None] | None = None,
) -> dict:
    """Load in a dictionary of Overleaf sync data, keyed by path relative to
    ``wdir`` (the project working directory).

    With ``fix_legacy``, settings that are no longer used are dropped from
    ``calkit.yaml``, and ``print_info`` is called to say so if given.
    """
    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    overleaf_info = {}
    # If we have any publications synced with Overleaf, get those and remove
    # from calkit.yaml if desired, since that's legacy behavior
    pubs = ck_info.get("publications", [])
    for pub in pubs:
        if "overleaf" in pub:
            pub_overleaf = pub.pop("overleaf")
            pub_wdir = pub_overleaf.get("wdir")
            if not pub_wdir:
                if "path" not in pub:
                    warnings.warn(f"Publication '{pub}' has no path")
                pub_wdir = os.path.dirname(pub["path"])
            overleaf_info[Path(pub_wdir).as_posix()] = pub_overleaf
    if wdir is None:
        wdir = ""
    info_path = get_sync_info_fpath(wdir=wdir)
    if os.path.isfile(info_path):
        with open(info_path) as f:
            ol_info_private = json.load(f)
        for k, v in ol_info_private.items():
            if k not in overleaf_info:
                overleaf_info[k] = {}
            for k1, v1 in v.items():
                overleaf_info[k][k1] = v1
    # Override with any values defined in calkit.yaml
    if "overleaf_sync" in ck_info:
        ol_info_ck = deepcopy(ck_info["overleaf_sync"])
        for k, v in ol_info_ck.items():
            if k not in overleaf_info:
                overleaf_info[k] = {}
            for k1, v1 in v.items():
                overleaf_info[k][k1] = v1
    # Iterate through and fix data if necessary
    for synced_dir, dirinfo in overleaf_info.items():
        if "url" in dirinfo:
            dirinfo["project_id"] = project_id_from_url(dirinfo["url"])
    if fix_legacy:
        overleaf_sync_for_ck_info = ck_info.get("overleaf_sync", {})
        dropped_sync_paths = []
        for synced_dir, info in overleaf_info.items():
            info_in_ck = overleaf_sync_for_ck_info.get(synced_dir, {})
            if "url" not in info_in_ck:
                info_in_ck["url"] = project_id_to_url(info["project_id"])
            # sync_paths no longer does anything, since every stored file is
            # synced both ways unless it's a push path or something the
            # pipeline produces, so it's dropped rather than carried forward
            if "sync_paths" in info_in_ck or "sync_paths" in info:
                dropped_sync_paths.append(synced_dir)
                info_in_ck.pop("sync_paths", None)
                info.pop("sync_paths", None)
            if "push_paths" in info:
                info_in_ck["push_paths"] = info["push_paths"]
            overleaf_sync_for_ck_info[synced_dir] = info_in_ck
        ck_info["overleaf_sync"] = overleaf_sync_for_ck_info
        if dropped_sync_paths and print_info is not None:
            print_info(
                "Removed 'sync_paths' from calkit.yaml for "
                f"{', '.join(dropped_sync_paths)}; "
                "it's no longer necessary, since all stored files are synced "
                "both ways unless they're push paths or pipeline outputs"
            )
        with open(os.path.join(wdir, "calkit.yaml"), "w") as f:
            calkit.ryaml.dump(ck_info, f)
        os.makedirs(os.path.join(wdir, ".calkit"), exist_ok=True)
        private_info = {}
        for synced_dir, info in overleaf_info.items():
            private_info[synced_dir] = {k: info.get(k) for k in PRIVATE_KEYS}
        with open(info_path, "w") as f:
            json.dump(private_info, f, indent=2)
    return overleaf_info


def get_sync_info_fpath(wdir: str | PathLike | None = None) -> str:
    if wdir is None:
        wdir = ""
    return os.path.join(wdir, ".calkit", "overleaf-sync.json")


def write_sync_info(
    synced_path: str, info: dict, wdir: str | PathLike | None = None
) -> str:
    """Write sync info for a given path, overwriting the data for that path."""
    # First read in the data
    if wdir is None:
        wdir = ""
    fpath = get_sync_info_fpath(wdir=wdir)
    if os.path.isfile(fpath):
        with open(fpath) as f:
            existing = json.load(f)
    else:
        existing = {}
    synced_path = Path(synced_path).as_posix()
    existing[synced_path] = {k: info.get(k) for k in PRIVATE_KEYS}
    # A project that has never used Calkit locally has no .calkit directory,
    # which is the normal case on the hub: it writes this into a fresh clone
    # while importing an Overleaf document as a publication
    os.makedirs(os.path.dirname(fpath) or ".", exist_ok=True)
    with open(fpath, "w") as f:
        json.dump(existing, f, indent=2)
    return fpath


def get_conflict_fpath(wdir: str | PathLike | None = None) -> str:
    if wdir is None:
        wdir = ""
    return os.path.join(str(wdir), ".calkit", "overleaf", "CONFLICT.json")


class OverleafSyncPaths:
    def __init__(
        self,
        main_repo: git.Repo,
        overleaf_repo: git.Repo,
        path_in_project: str,
        sync_info_for_path: dict,
        last_sync_commit: str | None = None,
    ) -> None:
        self.main_repo = main_repo
        self.overleaf_repo = overleaf_repo
        self.path_in_project = path_in_project
        self.sync_info_for_path = deepcopy(sync_info_for_path)
        self.push_paths_from_config = sync_info_for_path.get("push_paths", [])
        self.last_sync_commit = last_sync_commit

    @property
    def push_paths(self) -> list[str]:
        """These paths we only push to Overleaf.

        They are relative to ``{main_repo_dir}/{path_in_project}``.
        """
        return [
            Path(p).as_posix().rstrip("/") for p in self.push_paths_from_config
        ]

    @staticmethod
    def _path_matches(path_posix: str, patterns: list[str]) -> bool:
        """Whether ``path_posix`` equals or lives under any of ``patterns``.

        Patterns are treated as either files or directory prefixes.
        """
        for p in patterns:
            if path_posix == p or path_posix.startswith(p.rstrip("/") + "/"):
                return True
        return False

    def _rel_under_folder(self, paths: list[str]) -> set[str]:
        """Filter ``paths`` (relative to the main repo) to those under the
        synced folder, returning them relative to ``path_in_project``.
        """
        prefix = Path(self.path_in_project).as_posix().rstrip("/")
        prefix_slash = (prefix + "/") if prefix else ""
        res = set()
        for p in paths:
            pp = Path(p).as_posix()
            if prefix_slash:
                if not pp.startswith(prefix_slash):
                    continue
                pp = pp[len(prefix_slash) :]
            if pp:
                res.add(pp)
        return res

    @cached_property
    def stored_files(self) -> set[str]:
        """Files within the synced folder that are "stored", relative to
        ``path_in_project``.

        A file is stored if it is tracked by Git or cached by DVC (i.e., it
        has ``storage`` of ``git`` or ``dvc``). Only stored files are synced
        with Overleaf. Files that are ignored, untracked, or DVC pipeline
        outputs with no storage (``storage: null``) are treated as ignored
        and left out of the sync.
        """
        git_tracked = self._rel_under_folder(
            calkit.git.ls_files(self.main_repo)
        )
        return git_tracked | self.dvc_files

    @cached_property
    def all_pipeline_output_paths(self) -> set[str]:
        """All DVC pipeline output paths in the project, relative to the main
        repo, regardless of storage (including uncached ``storage: null``
        outputs).

        Kept repo-relative rather than folder-relative because a map-paths
        source usually lives outside the synced folder, and whether it is
        itself generated decides if an Overleaf edit can be sent back to it.
        """
        try:
            import calkit.dvc

            pipeline = calkit.dvc.read_pipeline(
                wdir=str(self.main_repo.working_dir)
            )
        except Exception as e:
            warnings.warn(f"Could not read pipeline: {e}")
            return set()
        out_paths = []
        for stage in pipeline.get("stages", {}).values():
            if isinstance(stage, dict):
                out_paths.extend(calkit.dvc.out_paths_from_stage(stage))
        return {Path(p).as_posix() for p in out_paths}

    @cached_property
    def pipeline_output_paths(self) -> set[str]:
        """All DVC pipeline output paths within the synced folder, regardless
        of storage (including uncached ``storage: null`` outputs), relative to
        ``path_in_project``.

        These may be individual files or directories. Any such path that is
        not stored is treated as ignored for syncing -- never pushed to,
        pulled from, or deleted from Overleaf -- since it is generated by the
        pipeline rather than authored.
        """
        return self._rel_under_folder(sorted(self.all_pipeline_output_paths))

    @cached_property
    def _pipeline_output_path_list(self) -> list[str]:
        """``pipeline_output_paths`` as a sorted list, computed once."""
        return sorted(self.pipeline_output_paths)

    def _is_pipeline_output(self, rel_posix: str) -> bool:
        """Whether a path is produced by the pipeline rather than authored."""
        return self._path_matches(rel_posix, self._pipeline_output_path_list)

    @cached_property
    def _map_paths_mappings(self) -> list:
        """Every mapping of every ``map-paths`` stage in the project.

        Built through the model so each mapping kind's destination is worked
        out the same way the pipeline works it out.
        """
        from calkit.models.pipeline import MapPathsStage

        try:
            ck_info = calkit.load_calkit_info(
                wdir=str(self.main_repo.working_dir)
            )
        except Exception as e:
            warnings.warn(f"Could not read Calkit pipeline: {e}")
            return []
        stages = (ck_info.get("pipeline") or {}).get("stages") or {}
        mappings: list = []
        for stage in stages.values():
            if not isinstance(stage, dict) or stage.get("kind") != "map-paths":
                continue
            try:
                parsed = MapPathsStage(**stage)
            except Exception as e:
                warnings.warn(f"Could not read map-paths stage: {e}")
                continue
            mappings.extend(parsed.paths)
        return mappings

    @cached_property
    def map_paths_outputs(self) -> set[str]:
        """Destinations of ``map-paths`` stages within the synced folder.

        A map-paths stage copies authored files into the document's folder --
        a shared ``references.bib`` or class file used by several papers.
        The copy is a pipeline output with no storage, so nothing else here
        treats it as syncable, but Overleaf needs it to compile the document.
        """
        return self._rel_under_folder(
            [p.out_path for p in self._map_paths_mappings]
        )

    @cached_property
    def map_paths_sources(self) -> dict[str, str]:
        """Map-paths copies in the synced folder, each pointing back at the
        file it was copied from.

        Keys are relative to ``path_in_project``, values relative to the main
        repo. This inverts what a map-paths stage does, so an edit made on
        Overleaf to one of these copies can be written back to the file the
        stage builds it from instead of being discarded -- the copy itself is
        regenerated on the next run, so an edit left there would be lost.

        A source is only included if it is authored: a source that is itself
        produced by another stage would have the edit overwritten just the
        same, so those are left out and reported as unrecoverable.
        """
        generated = self.all_pipeline_output_paths
        # Sources are only ever read here, so a directory mapping is inverted
        # by walking what the source actually contains
        main_dir = str(self.main_repo.working_dir)
        res: dict[str, str] = {}
        for mapping in self._map_paths_mappings:
            src = Path(mapping.src).as_posix()
            pairs: list[tuple[str, str]] = []
            if mapping.kind in ("file-to-file", "file-to-dir"):
                pairs.append((Path(mapping.out_path).as_posix(), src))
            else:
                # dir-to-dir-merge and dir-to-dir-replace: each file keeps its
                # path relative to the source directory
                src_abs = os.path.join(main_dir, src)
                dest = Path(mapping.out_path).as_posix()
                for dirpath, _, filenames in os.walk(src_abs):
                    for name in filenames:
                        rel = Path(
                            os.path.relpath(
                                os.path.join(dirpath, name), src_abs
                            )
                        ).as_posix()
                        pairs.append(
                            (f"{dest}/{rel}", f"{src}/{rel}"),
                        )
            for dest_path, src_path in pairs:
                if self._path_matches(src_path, sorted(generated)):
                    continue
                rel_dest = self._rel_under_folder([dest_path])
                for rel in rel_dest:
                    res[rel] = src_path
        return res

    @cached_property
    def mapped_files(self) -> set[str]:
        """Files on disk under a map-paths destination.

        Relative to ``path_in_project``. A destination may be a single file
        or a whole directory, so directories are walked.
        """
        root = os.path.join(self.main_repo.working_dir, self.path_in_project)
        res: set[str] = set()
        for dest in self.map_paths_outputs:
            abs_dest = os.path.join(root, dest)
            if os.path.isfile(abs_dest):
                res.add(dest)
            elif os.path.isdir(abs_dest):
                for dirpath, _, filenames in os.walk(abs_dest):
                    for name in filenames:
                        abs_file = os.path.join(dirpath, name)
                        res.add(
                            Path(os.path.relpath(abs_file, root)).as_posix()
                        )
        return res

    def _is_ignored_for_sync(self, rel_posix: str) -> bool:
        """Whether a path (relative to ``path_in_project``) should be treated
        as ignored, and therefore neither synced to/from nor deleted from
        Overleaf.

        A path is ignored if it is gitignored in the main repo, or if it is a
        DVC pipeline output with no storage (``storage: null``). Stored files
        (tracked by Git or cached by DVC) are never ignored, even if they live
        under a pipeline output directory.
        """
        if self.main_repo.ignored(
            os.path.join(self.path_in_project, rel_posix)
        ):
            return True
        if rel_posix in self.stored_files:
            return False
        # A pipeline output that is not stored has storage: null
        return self._is_pipeline_output(rel_posix)

    @cached_property
    def files_to_copy_from_overleaf(self) -> list[str]:
        """Return Overleaf files to copy into the main repo.

        We copy all files from Overleaf unless they are in push-only paths,
        are produced by the pipeline, or are ignored in the main repo. This
        method does not itself apply any special handling for files that were
        deleted locally since the last sync; such deletions are handled
        elsewhere in the sync logic.
        """
        all_ol_files = calkit.git.ls_files(self.overleaf_repo)
        res = []
        for fpath in all_ol_files:
            fpath_posix = Path(fpath).as_posix()
            # Skip anything ignored for syncing (gitignored or a storage: null
            # pipeline output)
            if self._is_ignored_for_sync(fpath_posix):
                continue
            # Skip anything the pipeline produces, even when it's stored in
            # Git. Pulling an edit into a generated file would look like it
            # worked and then be overwritten by the next run; the edit belongs
            # in whatever the stage builds it from.
            if self._is_pipeline_output(fpath_posix):
                continue
            # Skip files that are under any push-only path
            if self._path_matches(fpath_posix, self.push_paths):
                continue
            res.append(fpath_posix)
        return res

    @cached_property
    def files_to_copy_to_overleaf(self) -> list[str]:
        """Stored files to copy to Overleaf.

        We copy all stored files (tracked by Git or cached by DVC) within the
        synced folder, plus the copies a ``map-paths`` stage puts there,
        except for private (dot) files, the main PDF, and LaTeX aux/build
        artifacts. Other ignored, untracked, and ``storage: null`` files are
        never pushed.

        These files are all relative to the path in the project.
        """
        root = os.path.join(self.main_repo.working_dir, self.path_in_project)
        # Determine main PDF name (prefer main.tex if present at root)
        main_stem: str | None = None
        main_tex_path = os.path.join(root, "main.tex")
        if os.path.isfile(main_tex_path):
            main_stem = "main"
        elif os.path.isdir(root):
            # Fallback: if there is exactly one top-level .tex file, use it
            top_level_files = [
                f
                for f in os.listdir(root)
                if os.path.isfile(os.path.join(root, f))
            ]
            root_tex = [f for f in top_level_files if f.endswith(".tex")]
            if len(root_tex) == 1:
                main_stem = Path(root_tex[0]).stem
        main_pdf_rel = None
        if main_stem is not None:
            main_pdf_rel = Path(f"{main_stem}.pdf").as_posix()
        # Common LaTeX aux/build artifacts to exclude
        aux_suffixes = {
            ".aux",
            ".log",
            ".out",
            ".toc",
            ".bbl",
            ".blg",
            ".fls",
            ".fdb_latexmk",
            ".lof",
            ".lot",
            ".lol",
            ".nav",
            ".snm",
            ".vrb",
            ".dvi",
            ".xdv",
            ".auxlock",
        }
        # Multi-part extension handled via endswith
        aux_endswith = (".synctex.gz",)

        def has_hidden_component(rel_path: str) -> bool:
            parts = Path(rel_path).parts
            return any(p.startswith(".") for p in parts)

        results: list[str] = []
        # Map-paths copies are pushed alongside stored files: the content is
        # authored (in the source the stage copies from) and Overleaf can't
        # compile the document without it.
        for rel_posix in sorted(self.stored_files | self.mapped_files):
            # Skip hidden (dot) files and directories
            if has_hidden_component(rel_posix):
                continue
            # Skip main PDF specifically
            if main_pdf_rel is not None and rel_posix == main_pdf_rel:
                continue
            # Skip LaTeX aux/build artifacts
            if (
                rel_posix.endswith(aux_endswith)
                or Path(rel_posix).suffix in aux_suffixes
            ):
                continue
            # Only push files that are materialized on disk; stored files that
            # haven't been pulled (e.g., DVC-tracked but not fetched) are kept
            # on Overleaf but cannot be copied
            if not os.path.isfile(os.path.join(root, rel_posix)):
                continue
            results.append(rel_posix)
        return results

    @property
    def paths_to_use_for_git_patch(self) -> list[str]:
        """This should be anything in the Overleaf repo that isn't ignored
        or part of push paths in the main repo.
        """
        return self.files_to_copy_from_overleaf

    @cached_property
    def all_synced_files(self) -> list[str]:
        return list(
            set(
                self.files_to_copy_to_overleaf
                + self.files_to_copy_from_overleaf
            )
        )

    @cached_property
    def files_changed_on_overleaf(self) -> list[str]:
        """Files edited on Overleaf since the last sync."""
        if not self.last_sync_commit:
            return []
        try:
            changed = self.overleaf_repo.git.diff(
                "--name-only", f"{self.last_sync_commit}..HEAD"
            ).split("\n")
        except (git.BadName, git.GitCommandError, ValueError) as e:
            warnings.warn(f"Could not diff the Overleaf repo: {e}")
            return []
        return sorted({Path(f).as_posix() for f in changed if f})

    @cached_property
    def pipeline_outputs_changed_on_overleaf(self) -> list[str]:
        """Generated files someone edited on Overleaf since the last sync.

        These edits can't be pulled back -- the next pipeline run would
        overwrite them -- so they're worth saying out loud rather than
        dropping quietly.
        """
        return [
            f
            for f in self.files_changed_on_overleaf
            if self._is_pipeline_output(f)
        ]

    @cached_property
    def push_path_edits_on_overleaf(self) -> list[str]:
        """Authored push-only files someone edited on Overleaf since the last
        sync.

        A push path says the project is the source of truth for that file, so
        this sync is about to overwrite whatever was written there. Unlike a
        pipeline output, nothing regenerates it and no warning would make the
        content recoverable, so the sync stops instead. Pipeline outputs are
        left out here since they're reported on their own.
        """
        return [
            f
            for f in self.files_changed_on_overleaf
            if self._path_matches(f, self.push_paths)
            and not self._is_pipeline_output(f)
        ]

    @cached_property
    def files_in_overleaf_last_sync(self) -> set[str]:
        """Files that existed on Overleaf at the last sync commit."""
        files = set()
        if self.last_sync_commit:
            try:
                commit_obj = self.overleaf_repo.commit(self.last_sync_commit)
                files = set(
                    self.overleaf_repo.git.ls_tree(
                        "-r", "--name-only", commit_obj.hexsha
                    ).split("\n")
                )
                files.discard("")
            except (git.BadName, git.GitCommandError, ValueError) as e:
                warnings.warn(
                    f"Could not determine files at last Overleaf sync commit "
                    f"'{self.last_sync_commit}'; proceeding without stale file "
                    f"information. Underlying error: {e}"
                )
        return files

    @cached_property
    def newly_added_on_overleaf(self) -> set[str]:
        """Files that were added on Overleaf since the last sync."""
        return (
            set(self.files_to_copy_from_overleaf)
            - self.files_in_overleaf_last_sync
        )

    @cached_property
    def dvc_files(self) -> set[str]:
        """Files tracked by DVC within the Overleaf project folder.

        These paths are relative to the project directory (i.e., relative to
        the Overleaf repo root). Files tracked by DVC may not exist on disk if
        they haven't been pulled, but should still be kept on Overleaf rather
        than deleted.
        """
        try:
            import calkit.dvc

            dvc_paths = calkit.dvc.list_paths(
                wdir=str(self.main_repo.working_dir), recursive=True
            )
        except Exception as e:
            warnings.warn(f"Could not list DVC files: {e}")
            return set()
        prefix = Path(self.path_in_project).as_posix().rstrip("/") + "/"
        result = set()
        for p in dvc_paths:
            p_posix = Path(p).as_posix()
            if p_posix.startswith(prefix):
                result.add(p_posix[len(prefix) :])
        return result

    @cached_property
    def files_to_keep_on_overleaf(self) -> set[str]:
        """Files preserved on Overleaf, i.e., those that existed at the last
        sync and should not be deleted.

        A file from the last sync is kept if it is still stored locally
        (tracked by Git or cached by DVC), was newly added on Overleaf since
        the last sync, or is treated as ignored (gitignored or a
        ``storage: null`` pipeline output). Only files that were genuinely
        removed from the project are deleted from Overleaf.
        """
        keep = set()
        for f in self.files_in_overleaf_last_sync:
            if (
                f in self.stored_files
                or f in self.newly_added_on_overleaf
                or self._is_ignored_for_sync(f)
            ):
                keep.add(f)
        return keep

    @cached_property
    def stale_files_in_overleaf(self) -> list[str]:
        """Files that existed in the last sync but should be deleted.

        These are stored files that were genuinely removed from the project
        (not merely absent from disk or ignored).
        """
        return sorted(
            self.files_in_overleaf_last_sync - self.files_to_keep_on_overleaf
        )


def get_commits_since_last_sync(
    overleaf_repo: git.Repo, last_sync_commit: str | None
) -> list[git.Commit]:
    """Commits on Overleaf since the last sync that change files, so a
    download on top of a rebuilt last sync that matches it isn't counted.
    """
    if not last_sync_commit:
        return []
    return [
        c
        for c in overleaf_repo.iter_commits(rev=f"{last_sync_commit}..HEAD")
        if not c.parents or c.tree.hexsha != c.parents[0].tree.hexsha
    ]


FIGURE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".pdf",
    ".eps",
    ".ps",
    ".tif",
    ".tiff",
    ".webp",
}


def get_sync_status(
    main_repo: git.Repo,
    overleaf_repo: git.Repo,
    path_in_project: str,
    sync_info_for_path: dict | None = None,
    last_sync_commit: str | None = None,
    ck_info: dict | None = None,
) -> dict:
    """Compute the sync status between a project and an Overleaf project.

    This is the read-only counterpart to ``sync``: it reports what a sync
    would do without changing either repo's files, though a missing last
    sync is rebuilt in the Overleaf repo's history as ``ensure_sync_base``
    describes. Both repos should already be up-to-date (pulled), same as for
    ``sync``.

    The returned dictionary reports how many commits are waiting on
    Overleaf, which stored files differ from their Overleaf counterparts
    (and would therefore be pushed), and which previously-synced files
    would be deleted from Overleaf. Each file is flagged as a figure or
    not, so callers can surface out-of-date figures specifically.
    """
    path_in_project = Path(path_in_project).as_posix()
    if sync_info_for_path is None:
        sync_info_for_path = get_sync_info(wdir=main_repo.working_dir).get(
            path_in_project, {}
        )
    if last_sync_commit is None:
        last_sync_commit = sync_info_for_path.get("last_sync_commit")
    last_sync_commit = ensure_sync_base(
        overleaf_repo,
        main_repo=main_repo,
        path_in_project=path_in_project,
        last_sync_commit=last_sync_commit,
        print_info=lambda _: None,
        missing_ok=True,
    )
    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=main_repo.working_dir)
    # Declared figures are stored relative to the repo root, but sync works
    # relative to the synced folder, so translate them once up front
    prefix = path_in_project.rstrip("/")
    prefix_slash = (prefix + "/") if prefix else ""
    declared_figures = set()
    for fig in ck_info.get("figures") or []:
        fig_path = fig.get("path") if isinstance(fig, dict) else fig
        if not isinstance(fig_path, str):
            continue
        fig_posix = Path(fig_path).as_posix()
        if prefix_slash and not fig_posix.startswith(prefix_slash):
            continue
        declared_figures.add(fig_posix[len(prefix_slash) :])
    paths = OverleafSyncPaths(
        main_repo=main_repo,
        overleaf_repo=overleaf_repo,
        path_in_project=path_in_project,
        sync_info_for_path=sync_info_for_path,
        last_sync_commit=last_sync_commit,
    )
    main_dir = os.path.join(str(main_repo.working_dir), path_in_project)
    overleaf_dir = str(overleaf_repo.working_dir)

    def _is_figure(rel_posix: str) -> bool:
        if rel_posix in declared_figures:
            return True
        return Path(rel_posix).suffix.lower() in FIGURE_EXTENSIONS

    def _describe(rel_posix: str, state: str) -> dict:
        return dict(
            path=rel_posix,
            project_path=prefix_slash + rel_posix,
            state=state,
            figure=_is_figure(rel_posix),
        )

    files_to_push = []
    for rel_posix in paths.files_to_copy_to_overleaf:
        main_fpath = os.path.join(main_dir, rel_posix)
        overleaf_fpath = os.path.join(overleaf_dir, rel_posix)
        if not os.path.isfile(overleaf_fpath):
            files_to_push.append(_describe(rel_posix, "new"))
            continue
        # Compare sizes before contents so unchanged large figures, which
        # are the common case, don't get read on every status check
        if os.path.getsize(main_fpath) != os.path.getsize(overleaf_fpath):
            files_to_push.append(_describe(rel_posix, "modified"))
            continue
        with open(main_fpath, "rb") as f1, open(overleaf_fpath, "rb") as f2:
            if f1.read() != f2.read():
                files_to_push.append(_describe(rel_posix, "modified"))
    files_to_delete = [
        _describe(rel_posix, "deleted")
        for rel_posix in paths.stale_files_in_overleaf
    ]
    commits_from_overleaf = get_commits_since_last_sync(
        overleaf_repo=overleaf_repo, last_sync_commit=last_sync_commit
    )
    return dict(
        path_in_project=path_in_project,
        overleaf_project_id=sync_info_for_path.get("project_id"),
        last_sync_commit=last_sync_commit,
        project_commit=main_repo.head.commit.hexsha,
        overleaf_commit=overleaf_repo.head.commit.hexsha,
        commits_from_overleaf=len(commits_from_overleaf),
        files_to_push=files_to_push,
        files_to_delete=files_to_delete,
        in_sync=(
            not files_to_push
            and not files_to_delete
            and not commits_from_overleaf
        ),
    )


def sync(
    main_repo: git.Repo,
    overleaf_repo: git.Repo,
    path_in_project: str,
    sync_info_for_path: dict | None = None,
    last_sync_commit: str | None = None,
    no_commit: bool = False,
    print_info=print,
    verbose: bool = False,
    resolving_conflict: bool = False,
    push_only: bool = False,
    force: bool = False,
    push: Callable[[git.Repo], None] | None = None,
) -> dict:
    """Sync between the main project repo and Overleaf repo.

    Both must be up-to-date (pulled). The synced path in the main repo must
    also have no uncommitted changes, since incoming Overleaf edits are
    applied with ``git am``, which refuses to run against a dirty working
    tree (the calling CLI enforces this, optionally committing first with
    ``--auto-commit``).

    Only "stored" files in the main project -- those tracked by Git or cached
    by DVC -- are synced. They are synced bidirectionally, except for files
    under ``push_paths``, which are only pushed to Overleaf.

    Anything the pipeline produces is push-only, whichever way it's stored.
    Overleaf needs those files to compile the document, but an edit made to
    one there can't be pulled back: it would be overwritten by the next run,
    so it belongs in whatever the stage builds the file from. That includes
    the copies a ``map-paths`` stage puts in the document's folder (a shared
    ``references.bib``, say), which are pushed even though they're gitignored
    -- without them Overleaf can't compile.

    A map-paths copy is the one generated file whose edits have somewhere to
    go. When one is edited on Overleaf, the edit is written back to the file
    the stage copies it from, so the next run rebuilds the copy from it
    rather than discarding it. That doesn't apply when the source is itself
    generated by another stage; those edits are only reported.

    A push path declares the project the source of truth for those files, so
    if one has been edited on Overleaf since the last sync, this raises rather
    than overwriting it. Nothing regenerates such a file, so the edit would
    only exist in the Overleaf project's history. Pass ``force`` to overwrite
    them anyway.

    Other files that are ignored, untracked, or DVC pipeline outputs with no
    storage (``storage: null``, e.g., LaTeX build artifacts) are treated as
    ignored: never pushed to, pulled from, or deleted from Overleaf. A file is
    only deleted from Overleaf when a previously-synced stored file is
    genuinely removed from the project.

    When push_only is True, only push local files to Overleaf without pulling
    or applying changes from Overleaf to local. Useful for initializing a new
    Overleaf project from local files.

    ``push`` sends the Overleaf repo's new commit to Overleaf, by default with
    ``git push``; a session-synced mirror passes ``push_mirror`` instead.

    When no_commit is True, changes are still pulled from Overleaf and pushed
    to Overleaf, but no commit is created in the main project repo; the pulled
    changes are left staged instead. Overleaf changes are applied with
    ``git am``, which necessarily creates commits, so those commits are undone
    with a soft reset back to ``project_commit_before`` (which keeps their
    changes staged). See the ``--no-commit`` handling near the end of this
    function.
    """
    # Holds a mix of commits, paths, patches, and flags, so it's annotated
    # rather than inferred from whatever lands in it first.
    res: dict = {}
    # Normalize ``path_in_project`` as a posix path
    path_in_project = Path(path_in_project).as_posix()
    if sync_info_for_path is None:
        sync_info_for_path = get_sync_info(
            wdir=main_repo.working_dir, fix_legacy=True
        ).get(path_in_project, {})
    assert isinstance(sync_info_for_path, dict)
    if last_sync_commit is None:
        last_sync_commit = sync_info_for_path.get("last_sync_commit")
    checkpoint = last_sync_commit
    last_sync_commit = ensure_sync_base(
        overleaf_repo,
        main_repo=main_repo,
        path_in_project=path_in_project,
        last_sync_commit=last_sync_commit,
        print_info=print_info,
    )
    # A clone's rebuilt last sync isn't on Overleaf, so what's sent goes on
    # top of what is
    onto_upstream = last_sync_commit != checkpoint and not is_mirror(
        overleaf_repo
    )
    res["commits_since_last_sync"] = get_commits_since_last_sync(
        overleaf_repo=overleaf_repo, last_sync_commit=last_sync_commit
    )
    if res["commits_since_last_sync"]:
        print_info(
            f"There have been {len(res['commits_since_last_sync'])} changes "
            "on Overleaf since last sync"
        )
    res["project_commit_before"] = main_repo.head.commit.hexsha
    res["overleaf_commit_before"] = overleaf_repo.head.commit.hexsha
    path_in_project_abs = os.path.join(main_repo.working_dir, path_in_project)
    overleaf_project_dir_abs = overleaf_repo.working_dir
    conflict_fpath = get_conflict_fpath(wdir=main_repo.working_dir)
    # Determine which paths to sync and push
    overleaf_sync_data = deepcopy(sync_info_for_path)
    paths = OverleafSyncPaths(
        main_repo=main_repo,
        overleaf_repo=overleaf_repo,
        path_in_project=path_in_project,
        sync_info_for_path=sync_info_for_path,
        last_sync_commit=last_sync_commit,
    )
    paths_for_overleaf_patch = paths.paths_to_use_for_git_patch
    res["paths_for_overleaf_patch"] = paths_for_overleaf_patch
    # Stop before touching anything if someone has edited a file the project
    # is supposed to own. Nothing regenerates these, so overwriting one loses
    # the only copy outside the Overleaf project's own history.
    push_path_edits = paths.push_path_edits_on_overleaf
    res["push_path_edits_on_overleaf"] = push_path_edits
    if push_path_edits and not force:
        raise RuntimeError(
            "These files were changed on Overleaf but are push-only, so this "
            f"sync would overwrite them: {', '.join(push_path_edits)}. "
            "Copy the changes into the project if you want to keep them, or "
            "sync with --force to overwrite them."
        )
    # An edit made on Overleaf to a generated file is about to be overwritten
    # by this sync. A map-paths copy is the one case where the edit has
    # somewhere to go -- the file the stage copies from -- so it's sent there.
    # Anything else generated can only be reported.
    generated_edits = paths.pipeline_outputs_changed_on_overleaf
    res["pipeline_outputs_changed_on_overleaf"] = generated_edits
    map_paths_sources = paths.map_paths_sources
    edits_to_propagate = {
        dest: map_paths_sources[dest]
        for dest in generated_edits
        if dest in map_paths_sources
    }
    if push_only:
        edits_to_propagate = {}
    unrecoverable_edits = [
        dest for dest in generated_edits if dest not in edits_to_propagate
    ]
    if unrecoverable_edits and not push_only:
        print_info(
            "Warning: these files were changed on Overleaf but are generated "
            f"by the pipeline, so those changes will be overwritten: "
            f"{', '.join(unrecoverable_edits)}. Edit what the stage builds "
            "them from instead."
        )
    if push_only:
        # When push_only is True, skip pulling from Overleaf and applying
        # patches to local
        # Simply copy files to Overleaf
        print_info("Push-only sync; skipping pull from Overleaf")
        res["patch"] = None
    elif last_sync_commit and not paths_for_overleaf_patch:
        # Nothing on Overleaf is ours to pull. This needs its own branch
        # because an empty pathspec after `--` means "everything" to
        # format-patch, not "nothing", which would pull in exactly the files
        # we just decided to leave alone.
        res["patch"] = None
    elif last_sync_commit:
        # Compute a patch in the Overleaf project between HEAD and the last
        # sync
        patch = overleaf_repo.git.format_patch(
            [f"{last_sync_commit}..HEAD", "--stdout", "--"]
            + paths_for_overleaf_patch
        )
        # Replace any Overleaf commit messages to make them more meaningful
        patch = patch.replace(
            "Update on Overleaf.", f"Update {path_in_project} on Overleaf"
        )
        # Ensure the patch ends with a new line
        if patch and not patch.endswith("\n"):
            patch += "\n"
        if verbose:
            print_info(f"Git patch:\n{patch}")
        res["patch"] = patch
        if patch:
            print_info("Applying to project repo")
            process = subprocess.run(
                [
                    "git",
                    "am",
                    "--3way",
                    "--directory",
                    path_in_project,
                    "-",
                ],
                input=patch,
                text=True,
                encoding="utf-8",
                capture_output=True,
                cwd=main_repo.working_dir,
            )
            # Handle merge conflicts
            if process.returncode != 0 and (
                "merge conflict" in process.stdout.lower()
                or "merge conflict" in process.stderr.lower()
            ):
                msg = ""
                for line in process.stdout.split("\n"):
                    if "merge conflict" in line.lower():
                        msg += line + "\n"
                # Save a file to track this merge conflict, with a commit
                # the next pull keeps, since a rebuilt one isn't
                c = overleaf_repo.git.rev_parse(
                    "@{upstream}" if onto_upstream else "HEAD"
                )
                os.makedirs(os.path.dirname(conflict_fpath), exist_ok=True)
                with open(conflict_fpath, "w") as f:
                    json.dump(
                        {
                            "wdir": path_in_project,
                            "last_overleaf_commit": c,
                        },
                        f,
                    )
                raise RuntimeError(
                    f"{msg}Edit the file(s) and then call:\n\n"
                    "    calkit overleaf sync --resolve"
                )
            elif process.returncode != 0:
                main_repo.git.am("--abort")
                raise RuntimeError(
                    "Could not apply Git patch:\n"
                    f"{process.stdout}\n{process.stderr}"
                )
        elif resolving_conflict:
            # We have no patch since the last sync, but we need to update
            # our latest sync commit
            print_info("Merge conflict resolved")
        else:
            print_info("No changes to apply")
    else:
        # Simply copy in all files
        print_info(
            "No last sync commit defined; "
            "copying all files from Overleaf project"
        )
        res["patch"] = None
        files_to_copy_from_overleaf = paths.files_to_copy_from_overleaf
        res["files_to_copy_from_overleaf"] = files_to_copy_from_overleaf
        for sync_path in files_to_copy_from_overleaf:
            src = os.path.join(overleaf_project_dir_abs, sync_path)
            dst = os.path.join(path_in_project_abs, sync_path)
            if os.path.isdir(src):
                # Copy the directory and its contents
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.isfile(src):
                # Copy the file
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
            else:
                raise RuntimeError(
                    f"Source path {src} does not exist; "
                    "please check your Overleaf config"
                )
    # Send Overleaf's edits to map-paths copies back to the files they're
    # copied from. This happens after any patch has been applied, since
    # 'git am' refuses to run against a dirty working tree.
    propagated: dict[str, str] = {}
    diverged: dict[str, str] = {}
    for dest_rel, src_rel in sorted(edits_to_propagate.items()):
        overleaf_version = os.path.join(overleaf_project_dir_abs, dest_rel)
        if not os.path.isfile(overleaf_version):
            # Deleted on Overleaf; deleting the source it's shared from is
            # not this sync's call to make
            continue
        source_fpath = os.path.join(main_repo.working_dir, src_rel)
        copy_fpath = os.path.join(path_in_project_abs, dest_rel)
        # The copy is what the source produced the last time the stage ran,
        # so a source that still matches it hasn't changed since. One that
        # doesn't has edits of its own, which an overwrite would destroy.
        if os.path.isfile(source_fpath) and os.path.isfile(copy_fpath):
            with open(source_fpath, "rb") as f1, open(copy_fpath, "rb") as f2:
                if f1.read() != f2.read():
                    diverged[dest_rel] = src_rel
                    continue
        os.makedirs(os.path.dirname(source_fpath) or ".", exist_ok=True)
        shutil.copy2(overleaf_version, source_fpath)
        # The copy in the document's folder is updated too, so this sync
        # doesn't push the pre-edit version straight back to Overleaf. The
        # next run rewrites it from the source anyway.
        os.makedirs(os.path.dirname(copy_fpath) or ".", exist_ok=True)
        shutil.copy2(overleaf_version, copy_fpath)
        propagated[dest_rel] = src_rel
    res["map_paths_propagated"] = propagated
    res["map_paths_diverged"] = diverged
    if propagated:
        for dest_rel, src_rel in sorted(propagated.items()):
            print_info(
                f"Applying Overleaf's change to {dest_rel} to {src_rel}, "
                "which it's copied from"
            )
        print_info("Run the pipeline to rebuild from the updated source(s)")
    for dest_rel, src_rel in sorted(diverged.items()):
        print_info(
            f"Warning: {dest_rel} was changed on Overleaf, but {src_rel}, "
            "which it's copied from, has changes of its own; leaving both "
            "alone, so Overleaf keeps its version. Run the pipeline and sync "
            "again, or merge the two by hand."
        )
    # Copy our versions of sync and push paths into the Overleaf project,
    # except for copies whose source has diverged: pushing our version would
    # overwrite the Overleaf edit we just declined to pull, which is the loss
    # the warning above is there to prevent
    files_to_copy_to_overleaf = [
        p for p in paths.files_to_copy_to_overleaf if p not in diverged
    ]
    res["files_to_copy_to_overleaf"] = files_to_copy_to_overleaf
    if verbose:
        print_info(
            f"Copying the following files to Overleaf: "
            f"{files_to_copy_to_overleaf}"
        )
    for sync_push_path in files_to_copy_to_overleaf:
        src = os.path.join(path_in_project_abs, sync_push_path)
        dst = os.path.join(overleaf_project_dir_abs, sync_push_path)
        if os.path.isdir(src):
            # Remove destination directory if it exists
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            # Copy the directory and its contents
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif os.path.isfile(src):
            # Copy the file
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        else:
            raise RuntimeError(
                f"Source path {src} does not exist; "
                "please check your Overleaf config"
            )
    # Delete stale files from Overleaf (files that existed before but are
    # no longer locally or have been excluded from sync)
    res["newly_added_on_overleaf"] = sorted(paths.newly_added_on_overleaf)
    res["files_to_keep_on_overleaf"] = sorted(paths.files_to_keep_on_overleaf)
    res["stale_files_in_overleaf"] = paths.stale_files_in_overleaf
    for stale_path in paths.stale_files_in_overleaf:
        file_path = os.path.join(overleaf_project_dir_abs, stale_path)
        if os.path.isfile(file_path):
            os.remove(file_path)
    # Stage the changes in the Overleaf project
    res["committed_overleaf"] = False
    overleaf_repo.git.add(".")
    if overleaf_repo.git.diff("--staged"):
        print_info("Committing changes to Overleaf")
        commit_message = "Sync with Calkit project"
        overleaf_repo.git.commit("-m", commit_message)
        if onto_upstream:
            commit = overleaf_repo.git.commit_tree(
                overleaf_repo.head.commit.tree.hexsha,
                "-p",
                "@{upstream}",
                "-m",
                commit_message,
            )
            overleaf_repo.git.reset("--hard", commit)
        print_info("Pushing changes to Overleaf")
        if push is None:
            overleaf_repo.git.push()
        else:
            push(overleaf_repo)
        res["committed_overleaf"] = True
    elif onto_upstream:
        # Nothing was sent, so Overleaf already has this sync's files
        overleaf_repo.git.reset("--hard", "@{upstream}")
    # Update the last sync commit
    last_overleaf_commit = overleaf_repo.head.commit.hexsha
    res["overleaf_commit_after"] = last_overleaf_commit
    if res["committed_overleaf"]:
        print_info(f"Updating last sync commit as {last_overleaf_commit}")
    overleaf_sync_data["last_sync_commit"] = last_overleaf_commit
    # Write Overleaf sync data
    overleaf_sync_data_fpath = write_sync_info(
        synced_path=path_in_project,
        info=overleaf_sync_data,
        wdir=str(main_repo.working_dir),
    )
    main_repo.git.add("calkit.yaml")
    main_repo.git.add(overleaf_sync_data_fpath)
    if resolving_conflict and os.path.isfile(conflict_fpath):
        os.remove(conflict_fpath)
    # Auto-ignore any untracked build artifacts (e.g., LaTeX aux files like
    # .auxlock) in the synced folder so they don't get committed during sync
    gitignore_modified = False
    path_prefix = path_in_project.rstrip("/") + "/"
    auto_ignore_paths = {Path(p).as_posix() for p in calkit.AUTO_IGNORE_PATHS}
    for untracked in main_repo.untracked_files:
        untracked_posix = Path(untracked).as_posix()
        if not untracked_posix.startswith(path_prefix):
            continue
        if (
            any(
                untracked_posix.endswith(s)
                for s in calkit.AUTO_IGNORE_SUFFIXES
            )
            or any(
                untracked_posix.startswith(p)
                for p in calkit.AUTO_IGNORE_PREFIXES
            )
            or untracked_posix in auto_ignore_paths
        ):
            if calkit.git.ensure_path_is_ignored(main_repo, untracked_posix):
                print_info(f"Automatically ignoring {untracked_posix}")
                main_repo.git.add(".gitignore")
                gitignore_modified = True
    # Stage the changes in the project repo
    res["committed_project"] = False
    main_repo.git.add(path_in_project)
    paths_to_commit = [
        path_in_project,
        "calkit.yaml",
        overleaf_sync_data_fpath,
    ]
    # Map-paths sources typically live outside the synced folder, so they
    # need staging by name. One stored with DVC rather than Git can't be
    # staged at all, so it's left for the user to save.
    for src_rel in sorted(set(propagated.values())):
        if main_repo.ignored(src_rel):
            print_info(
                f"Not committing {src_rel} since it's ignored by Git; "
                "save it with 'calkit save' if it's stored with DVC"
            )
            continue
        main_repo.git.add(src_rel)
        if src_rel not in paths_to_commit:
            paths_to_commit.append(src_rel)
    if gitignore_modified:
        paths_to_commit.append(".gitignore")
    staged_diff = main_repo.git.diff(["--staged"] + paths_to_commit)
    if staged_diff and not no_commit:
        print_info("Committing changes to project repo")
        commit_message = SYNC_COMMIT_MESSAGE.format(path_in_project)
        main_repo.git.commit(*paths_to_commit, "-m", commit_message)
        res["committed_project"] = True
    elif no_commit and (
        main_repo.head.commit.hexsha != res["project_commit_before"]
    ):
        # Changes pulled from Overleaf are applied via 'git am', which creates
        # commits in the main repo. Since --no-commit was requested, undo
        # those commits while keeping their changes staged.
        print_info(
            "Resetting commits created while applying Overleaf changes "
            "(leaving them staged)"
        )
        main_repo.git.reset("--soft", res["project_commit_before"])
    res["project_commit_after"] = main_repo.head.commit.hexsha
    return res
