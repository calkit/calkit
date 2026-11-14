"""Calkit's side of the browser extension: a native messaging host, which
the browser starts so the extension can work with projects on this machine
directly, rather than through a hub.

The browser runs the host when the extension connects, and talks to it over
its standard input and output, each message a JSON object preceded by its
length. Only the extensions the host's manifest names can start it, and it
listens on nothing, so no other program or web page can reach it.

Run as ``python -m calkit.browser_link``, which skips the CLI, since the browser
waits on it to start.
"""

from __future__ import annotations

import io
import json
import os
import platform
import re
import struct
import subprocess
import sys
import tempfile
from typing import Any, BinaryIO

import calkit

HOST_NAME = "io.calkit.native"
CHROME_EXTENSION_IDS = ["idhdomgapfolnpffanajdckdaojencal"]
FIREFOX_EXTENSION_IDS = ["browser-ext@calkit.io"]
# How many of a checkout's files its status lists, so it fits in a message
MAX_LISTED_FILES = 50
# The most of a job's log sent at once, and how much shows while it runs
MAX_LOG_CHARS = 200_000
LIVE_OUTPUT_LINES = 8
# How long opening a project waits to hear it failed
OPEN_TIMEOUT_SECONDS = 30
# Chrome won't take a bigger message from a host
MAX_MESSAGE_BYTES = 1024 * 1024
# How long the checkouts found for a project are trusted, since finding
# them means searching the home folder
CHECKOUTS_TTL_SECONDS = 60
# How often an Overleaf project no checkout here syncs with is looked for
# again, since that searches the home folder too
LOOKUP_RESCAN_SECONDS = 600
# What a job, e.g., a pipeline run, can do, as the command it runs in the
# project's checkout, so nothing else can be run through one
JOB_KINDS = ("run", "sync", "clone", "install-editor")
# How many of a project's finished jobs are kept
MAX_JOBS_KEPT = 20
# How much of a PDF goes in each message, which base64 makes a third
# bigger, keeping it well under the browser's limit
PDF_CHUNK_BYTES = 600_000
OVERLEAF_AUTH_MISSING = (
    "Calkit on this computer has no Overleaf credentials that work; connect "
    "Overleaf to Calkit, which saves them for every computer you use"
)
# Where each browser looks for hosts' manifests in the home folder, by
# platform; each is only written if the folder above it exists, i.e., the
# browser has been run
MANIFEST_DIRS = {
    "Darwin": {
        "chrome": "Library/Application Support/Google/Chrome",
        "chromium": "Library/Application Support/Chromium",
        "edge": "Library/Application Support/Microsoft Edge",
        "brave": "Library/Application Support/BraveSoftware/Brave-Browser",
        "firefox": "Library/Application Support/Mozilla",
    },
    "Linux": {
        "chrome": ".config/google-chrome",
        "chromium": ".config/chromium",
        "edge": ".config/microsoft-edge",
        "brave": ".config/BraveSoftware/Brave-Browser",
        "firefox": ".mozilla",
    },
}
# Windows finds a manifest through the registry instead, from a key under
# HKEY_CURRENT_USER, which Chromium and Brave read from Chrome's
WINDOWS_REGISTRY_KEYS = {
    "chrome": r"Software\Google\Chrome\NativeMessagingHosts",
    "edge": r"Software\Microsoft\Edge\NativeMessagingHosts",
    "firefox": r"Software\Mozilla\NativeMessagingHosts",
}


def read_message(stream: BinaryIO) -> dict | None:
    """Read a message from the browser, or None once it's gone."""
    header = stream.read(4)
    if len(header) < 4:
        return None
    (n_bytes,) = struct.unpack("=I", header)
    data = stream.read(n_bytes)
    if len(data) < n_bytes:
        return None
    msg = json.loads(data)
    if not isinstance(msg, dict):
        raise ValueError("A message must be a JSON object")
    return msg


def write_message(stream: BinaryIO, msg: dict) -> None:
    data = json.dumps(msg).encode("utf-8")
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError(f"A reply can't be over {MAX_MESSAGE_BYTES} bytes")
    stream.write(struct.pack("=I", len(data)) + data)
    stream.flush()


def get_reply(msg: dict) -> dict:
    """Answer a request from the extension.

    Requests have a ``type``, and an ``id`` the reply repeats, so several
    can be waited on at once:

    - ``ping``: Calkit's version, to tell the extension it's here, and
      the editor projects open in.
    - ``projects.find``: the folders a project, given as ``owner/name``,
      is checked out in.
    - ``project.open``: open a project in its editor, as
      ``calkit open project`` does, along with a file in it if ``path`` is
      given.
    - ``project.status``: what isn't saved or synced to Overleaf in each
      checkout of a project, as ``get_checkout_status`` says.
    - ``checkouts.get``: a project's checkouts, the one to use first, and
      ``checkouts.choose`` to remember which to use.
    - ``overleaf.lookup``: the projects here that sync a folder with an
      Overleaf project, shaped as the hub's lookup is.
    - ``overleaf.status``: what a sync of a project's checkout would do,
      after pulling from Overleaf, shaped as the hub's status is.
    - ``publication.pdf``: part of the PDF a folder synced with Overleaf
      builds to, from ``offset``, with how fresh it is, so it can be shown
      in place of Overleaf's.
    - ``job.start``, ``job.get``, and ``jobs.list``: run something that
      takes a while, i.e., a pipeline run, an Overleaf sync, or a clone, in
      a process of its own, which outlives the host, and check on it.
    """

    def split_project(project: Any) -> tuple[str, str]:
        owner, _, name = (
            project.partition("/")
            if isinstance(project, str)
            else ("", "", "")
        )
        if not owner or not name or "/" in name:
            raise ValueError("A project is given as 'owner/name'")
        return owner, name

    req_id = msg.get("id")
    kind = msg.get("type")
    try:
        if kind == "ping":
            result: Any = {"version": calkit.__version__} | get_editor_info()
        elif kind == "projects.find":
            owner, name = split_project(msg.get("project"))
            found = calkit.get_project_checkouts(name, owner=owner)
            result = {"paths": sorted(found)}
        elif kind == "project.open":
            owner, name = split_project(msg.get("project"))
            cmd = [sys.executable, "-m", "calkit", "open", "project"]
            cmd += [f"{owner}/{name}", "--with", get_editor_info()["editor"]]
            path = msg.get("path")
            if path is not None:
                if not isinstance(path, str):
                    raise ValueError("A path must be a string")
                cmd += ["--path", path]
            # Never cloning, which needs someone to say where. An editor
            # that keeps running, e.g., JupyterLab's server, has opened it
            # once it's still going a while later, and is left running in
            # its own session, past the host
            with tempfile.TemporaryFile("w+") as out:
                proc = subprocess.Popen(
                    cmd,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    env=get_login_shell_env(),
                    text=True,
                    start_new_session=True,
                )
                try:
                    returncode = proc.wait(timeout=OPEN_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    returncode = 0
                out.seek(0)
                lines = out.read().strip().splitlines()
            if returncode != 0:
                error = (
                    (lines[-1] if lines else "Failed to open it")
                    .removeprefix("Error: ")
                    .strip()
                )
                if "isn't on this machine" in error:
                    error = (
                        f"{owner}/{name} isn't on this computer; clone it "
                        f"with 'calkit clone {owner}/{name}'"
                    )
                raise ValueError(error)
            result = {}
        elif kind == "project.status":
            owner, name = split_project(msg.get("project"))
            found = calkit.get_project_checkouts(name, owner=owner)
            result = {
                "checkouts": [get_checkout_status(p) for p in sorted(found)]
            }
        elif kind == "checkouts.get":
            owner, name = split_project(msg.get("project"))
            paths = get_checkout_paths(owner, name)
            result = {"paths": paths, "path": paths[0] if paths else None}
        elif kind == "checkouts.choose":
            owner, name = split_project(msg.get("project"))
            path = msg.get("path")
            if path not in get_checkout_paths(owner, name):
                raise ValueError(f"{path} isn't a checkout of {owner}/{name}")
            remember_checkout(owner, name, path)
            result = {"paths": get_checkout_paths(owner, name), "path": path}
        elif kind == "overleaf.lookup":
            overleaf_project_id = msg.get("overleaf_project_id")
            if not isinstance(overleaf_project_id, str):
                raise ValueError("An Overleaf project ID is needed")
            links = get_overleaf_links(overleaf_project_id)
            result = {
                "links": links,
                "projects_scanned": len(links),
                "projects_remaining": 0,
            }
        elif kind == "overleaf.status":
            owner, name = split_project(msg.get("project"))
            paths = get_checkout_paths(owner, name)
            if not paths:
                raise ValueError(f"{owner}/{name} isn't on this computer")
            result = get_overleaf_sync_statuses(
                paths[0],
                overleaf_project_id=msg.get("overleaf_project_id"),
                path=msg.get("path"),
            )
        elif kind == "publication.pdf":
            owner, name = split_project(msg.get("project"))
            paths = get_checkout_paths(owner, name)
            if not paths:
                raise ValueError(f"{owner}/{name} isn't on this computer")
            offset = msg.get("offset", 0)
            if not isinstance(offset, int) or offset < 0:
                raise ValueError("An offset must be a whole number")
            result = get_pdf_chunk(paths[0], str(msg.get("folder")), offset)
        elif kind == "job.start":
            result = start_job(msg)
        elif kind == "job.get":
            result = get_job(str(msg.get("job_id")))
        elif kind == "job.log":
            result = {"log": get_job_log(str(msg.get("job_id")))}
        elif kind == "jobs.list":
            owner, name = split_project(msg.get("project"))
            result = [
                j
                for j in list_jobs()
                if j["project"] == f"{owner}/{name}"
                and j["kind"] == msg.get("kind", j["kind"])
            ]
        else:
            raise ValueError(f"Unknown request type {kind!r}")
    except OverleafAuthMissing as e:
        # As the hub says it, so the extension asks for credentials there
        return {"id": req_id, "ok": False, "error": str(e), "status": 401}
    except Exception as e:
        return {"id": req_id, "ok": False, "error": str(e)}
    return {"id": req_id, "ok": True, "result": result}


class OverleafAuthMissing(Exception):
    """Calkit here has no Overleaf credentials that work, and can't ask."""


def get_editor_info() -> dict[str, Any]:
    """The editor projects open in here, and whether it's installed: the one
    set in Calkit's config, or else the first installed of those built on VS
    Code, VS Code first, or VS Code, which can be installed.
    """
    import shutil

    from calkit import install
    from calkit.cli.open_ import EDITOR_COMMANDS, split_command
    from calkit.config import read as read_config

    def find(editor: str) -> str | None:
        cmd = split_command(EDITOR_COMMANDS.get(editor, editor))
        if not cmd:
            return None
        env = get_login_shell_env() or os.environ
        found = shutil.which(cmd[0], path=env.get("PATH"))
        if found is None and editor == "vscode":
            found = install.find("code")
        return found

    settings = read_config()
    if "default_editor" in settings.model_fields_set:
        editor = settings.default_editor
        return {"editor": editor, "editor_installed": find(editor) is not None}
    for editor in [
        "vscode",
        "cursor",
        "positron",
        "vscodium",
        "antigravity",
        "windsurf",
    ]:
        if find(editor) is not None:
            return {"editor": editor, "editor_installed": True}
    return {"editor": "vscode", "editor_installed": False}


def get_login_shell_env() -> dict[str, str] | None:
    """The environment to run Calkit or an editor in, with the login
    shell's PATH, since a browser started from the Dock, e.g., has only the
    system's folders on its PATH.
    """
    if os.name == "nt":
        return None
    from calkit.hub.link import login_shell_path

    login_path = login_shell_path()
    if not login_path:
        return None
    return os.environ | {
        "PATH": os.pathsep.join([login_path, os.environ.get("PATH", "")])
    }


def get_choices_path() -> str:
    return os.path.join(get_host_dir(), "checkouts.json")


def remember_checkout(owner: str, name: str, path: str) -> None:
    """Use ``path`` for a project from now on, e.g., one of its worktrees."""
    choices_path = get_choices_path()
    choices = {}
    if os.path.isfile(choices_path):
        with open(choices_path) as f:
            choices = json.load(f)
    choices[f"{owner}/{name}"] = path
    os.makedirs(os.path.dirname(choices_path), exist_ok=True)
    with open(choices_path, "w") as f:
        json.dump(choices, f, indent=2)
    _checkouts_found.pop(get_checkouts_key(owner, name), None)


# The checkouts found for each project, and when, while the host runs
_checkouts_found: dict[str, tuple[float, list[str]]] = {}


def get_checkouts_key(owner: str, name: str) -> str:
    # By home folder too, which is where they're searched for
    return f"{calkit.get_user_home()}:{owner}/{name}"


def get_checkout_paths(owner: str, name: str) -> list[str]:
    """A project's checkouts here, the one to use first: the one chosen
    last, else one in ~/calkit, as ``calkit open project`` picks.
    """
    import time

    key = get_checkouts_key(owner, name)
    found_at, paths = _checkouts_found.get(key, (0.0, []))
    if time.time() - found_at > CHECKOUTS_TTL_SECONDS or not all(
        os.path.isdir(p) for p in paths
    ):
        paths = sorted(calkit.get_project_checkouts(name, owner=owner))
        _checkouts_found[key] = (time.time(), paths)
    return sort_checkouts(owner, name, paths)


def sort_checkouts(owner: str, name: str, paths: list[str]) -> list[str]:
    """Checkouts of a project, the one to use first: the one chosen last,
    else one in ~/calkit, as ``calkit open project`` picks.
    """
    chosen = None
    if os.path.isfile(get_choices_path()):
        with open(get_choices_path()) as f:
            chosen = json.load(f).get(f"{owner}/{name}")
    calkit_dir = os.path.realpath(
        os.path.join(calkit.get_user_home(), "calkit")
    )

    def get_rank(path: str) -> int:
        if path == chosen:
            return 0
        return 1 if os.path.dirname(path) == calkit_dir else 2

    return sorted(paths, key=get_rank)


def get_overleaf_index_path() -> str:
    return os.path.join(get_host_dir(), "overleaf-index.json")


def get_overleaf_links(overleaf_project_id: str) -> list[dict]:
    """The folders of projects here that sync with an Overleaf project, as
    the hub's lookup gives them, with each checkout's ``local_path``.

    Each project's Overleaf folders are kept in an index, read again only
    when its ``calkit.yaml`` or sync record changes, so a known Overleaf
    project is found without searching the home folder.
    """
    import time
    from copy import deepcopy

    import calkit.git
    import calkit.overleaf

    def get_mtimes(path: str) -> list[float]:
        return [
            os.path.getmtime(p) if os.path.isfile(p) else 0.0
            for p in (
                os.path.join(path, "calkit.yaml"),
                calkit.overleaf.get_sync_info_fpath(wdir=path),
            )
        ]

    def read_checkout(path: str) -> dict | None:
        # A subproject without its own repo would look like its parent
        try:
            repo = calkit.git.get_repo(path)
            if os.path.realpath(str(repo.working_tree_dir)) != path:
                return None
            info = calkit.load_calkit_info(wdir=path, read_only=True)
            project = calkit.detect_project_name(wdir=path)
            sync_info = calkit.overleaf.get_sync_info(
                wdir=path, ck_info=deepcopy(info)
            )
            remote_url = repo.remote().url if repo.remotes else ""
        except Exception:
            # E.g., a calkit.yaml left with merge conflict markers, or one
            # that names no owner
            return None
        owner_name = calkit.get_owner_and_name_from_git_url(remote_url)
        github_repo_url = None
        if owner_name and "github.com" in remote_url:
            github_repo_url = "https://github.com/" + "/".join(owner_name)
        return {
            "mtimes": get_mtimes(path),
            "project": project,
            "title": info.get("title") or project.split("/", 1)[-1],
            "github_repo_url": github_repo_url,
            "folders": {
                folder: s.get("project_id")
                for folder, s in sync_info.items()
                if s.get("project_id")
            },
        }

    def get_links(index: dict) -> list[dict]:
        links = []
        for path, entry in index["checkouts"].items():
            if not entry:
                continue
            owner, name = entry["project"].split("/", 1)
            for folder, project_id in entry["folders"].items():
                if project_id != overleaf_project_id:
                    continue
                links.append(
                    {
                        "overleaf_project_id": project_id,
                        "path": folder,
                        "project_owner_name": owner,
                        "project_name": name,
                        "project_title": entry["title"],
                        # Whoever can't push finds out when saving, as
                        # they would from a terminal
                        "current_user_access": "write",
                        "github_repo_url": entry["github_repo_url"],
                        "local_path": path,
                    }
                )
        # One checkout of each project, e.g., of several worktrees, the
        # one to use first, as everywhere else
        by_project: dict[tuple[str, str], list[dict]] = {}
        for link in links:
            key = (link["project_owner_name"], link["project_name"])
            by_project.setdefault(key, []).append(link)
        firsts = []
        for (owner, name), project_links in by_project.items():
            [first, *_] = sort_checkouts(
                owner, name, [link["local_path"] for link in project_links]
            )
            firsts += [x for x in project_links if x["local_path"] == first]
        return firsts

    index_path = get_overleaf_index_path()
    index: dict[str, Any] = {"scanned": 0.0, "checkouts": {}}
    if os.path.isfile(index_path):
        try:
            with open(index_path) as f:
                index = json.load(f)
        except ValueError:
            pass
    changed = False
    # Those changed since they were read, or gone
    for path, entry in list(index["checkouts"].items()):
        if not os.path.isdir(path):
            del index["checkouts"][path]
            changed = True
        elif entry is None or entry["mtimes"] != get_mtimes(path):
            index["checkouts"][path] = read_checkout(path)
            changed = True
    links = get_links(index)
    if not links and time.time() - index["scanned"] > LOOKUP_RESCAN_SECONDS:
        for path in calkit.find_project_dirs():
            path = os.path.realpath(path)
            if path not in index["checkouts"]:
                index["checkouts"][path] = read_checkout(path)
        index["scanned"] = time.time()
        changed = True
        links = get_links(index)
    if changed:
        os.makedirs(os.path.dirname(index_path), exist_ok=True)
        with open(index_path, "w") as f:
            json.dump(index, f)
    return links


def get_overleaf_sync_statuses(
    wdir: str,
    overleaf_project_id: str | None = None,
    path: str | None = None,
) -> list[dict]:
    """What a sync of each folder of a checkout synced with Overleaf would
    do, after pulling from Overleaf, as the hub's status reports it,
    optionally only for one ``path`` or Overleaf project.

    Overleaf credentials come from Calkit's config, or else the hub, as for
    ``calkit overleaf sync``.
    """
    import contextlib
    from copy import deepcopy
    from pathlib import Path

    import typer

    import calkit.git
    import calkit.overleaf
    import calkit.pipeline
    from calkit.cli.overleaf import (
        _get_overleaf_auth,
        _get_pulled_overleaf_repo,
    )

    def to_status_file(file_info: dict) -> dict:
        return {
            "path": file_info["path"],
            "project_path": file_info["project_path"],
            "state": file_info["state"],
            "figure": file_info["figure"],
            "stage": calkit.pipeline.get_stage_for_output(
                file_info["project_path"], ck_info
            ),
            # Asking DVC would take seconds; the hub only knows what's
            # been pushed anyway
            "stage_status": None,
        }

    prev_wdir = os.getcwd()
    # What the CLI's helpers print would go into the browser's messages
    printed = io.StringIO()
    try:
        os.chdir(wdir)
        with (
            contextlib.redirect_stdout(printed),
            contextlib.redirect_stderr(printed),
        ):
            ck_info = calkit.load_calkit_info(read_only=True)
            sync_info = calkit.overleaf.get_sync_info(
                ck_info=deepcopy(ck_info)
            )
            if path is not None:
                path = Path(path).as_posix().rstrip("/")
                if path not in sync_info:
                    raise ValueError(f"{path} isn't synced with Overleaf")
            main_repo = calkit.git.get_repo()
            auth = None
            statuses = []
            for path_in_project, sync_info_for_path in sync_info.items():
                project_id = sync_info_for_path.get("project_id")
                if (path is not None and path_in_project != path) or (
                    overleaf_project_id is not None
                    and project_id != overleaf_project_id
                ):
                    continue
                if not project_id:
                    continue
                if auth is None:
                    auth = _get_overleaf_auth()
                with calkit.overleaf.lock(project_id, lambda _: None):
                    overleaf_repo, auth = _get_pulled_overleaf_repo(
                        project_id, auth
                    )
                    status = calkit.overleaf.get_sync_status(
                        main_repo=main_repo,
                        overleaf_repo=overleaf_repo,
                        path_in_project=path_in_project,
                        ck_info=ck_info,
                    )
                    overleaf_repo.close()
                statuses.append(
                    {
                        "path": status["path_in_project"],
                        "overleaf_project_id": status["overleaf_project_id"],
                        "overleaf_url": calkit.overleaf.project_id_to_url(
                            project_id
                        ),
                        "last_sync_commit": status["last_sync_commit"],
                        "project_commit": status["project_commit"],
                        "overleaf_commit": status["overleaf_commit"],
                        "commits_from_overleaf": status[
                            "commits_from_overleaf"
                        ],
                        "files_to_push": [
                            to_status_file(f) for f in status["files_to_push"]
                        ],
                        "files_to_delete": [
                            to_status_file(f)
                            for f in status["files_to_delete"]
                        ],
                        "in_sync": status["in_sync"],
                    }
                )
    except (typer.Exit, SystemExit):
        # A helper that would have asked for credentials says why it
        # couldn't instead
        lines = [x for x in printed.getvalue().splitlines() if x.strip()]
        error = lines[-1] if lines else "Overleaf couldn't be reached"
        error = re.sub(r"\x1b\[[0-9;]*m", "", error).removeprefix("Error: ")
        if re.search(r"overleaf_token|overleaf login", error):
            raise OverleafAuthMissing(OVERLEAF_AUTH_MISSING)
        raise ValueError(error)
    finally:
        os.chdir(prev_wdir)
    return statuses


def get_pdf_path(wdir: str, folder: str) -> str | None:
    """The PDF built from a folder synced with Overleaf, relative to the
    checkout: a publication's in it, or else its LaTeX stage's output.
    """
    from pathlib import PurePosixPath

    def is_in_folder(path: str) -> bool:
        return PurePosixPath(path).is_relative_to(folder)

    ck_info = calkit.load_calkit_info(wdir=wdir, read_only=True)
    for pub in ck_info.get("publications") or []:
        path = pub.get("path") if isinstance(pub, dict) else None
        if isinstance(path, str) and path.endswith(".pdf"):
            if is_in_folder(path):
                return path
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    for stage in stages.values():
        target = stage.get("target_path") if isinstance(stage, dict) else None
        if stage.get("kind") == "latex" and isinstance(target, str):
            if is_in_folder(target):
                return target.removesuffix(".tex") + ".pdf"
    return None


def get_pdf_chunk(wdir: str, folder: str, offset: int) -> dict:
    """Part of the PDF a folder synced with Overleaf builds to, as base64
    ``data``, from ``offset``, with its ``size``, when it was built, the
    commit that saved it, if any, whether it's changed since, and whether
    anything else in the folder has, i.e., it's older than its source.
    """
    import base64

    import calkit.git

    path = get_pdf_path(wdir, folder)
    if path is None:
        raise ValueError(f"No PDF is built from {folder}")
    full_path = os.path.join(wdir, path)
    if not os.path.isfile(full_path):
        raise ValueError(
            f"{path} hasn't been built on this computer; run the pipeline"
        )
    stat = os.stat(full_path)
    with open(full_path, "rb") as f:
        f.seek(offset)
        data = f.read(PDF_CHUNK_BYTES)
    chunk: dict[str, Any] = {
        "path": path,
        "size": stat.st_size,
        "offset": offset,
        "data": base64.b64encode(data).decode("ascii"),
    }
    # How fresh it is, only with the first part
    if offset == 0:
        repo = calkit.git.get_repo(wdir)
        commit_sha = repo.git.log("-1", "--format=%H", "--", path) or None
        changed = bool(repo.git.status("--porcelain", "--", path).strip())
        folder_path = os.path.join(wdir, folder)
        edited_since = any(
            os.path.getmtime(os.path.join(root, fname)) > stat.st_mtime
            for root, dirs, files in os.walk(folder_path)
            for fname in files
            if not fname.endswith((".pdf", ".log", ".aux", ".fls"))
            and not root.startswith(os.path.join(folder_path, "_calkit"))
        )
        chunk |= {
            "built": stat.st_mtime,
            "commit_sha": commit_sha,
            # Unknown for one Git doesn't track, e.g., stored with DVC
            "changed_since_commit": changed if commit_sha else None,
            "edited_since_built": edited_since,
        }
    return chunk


def get_jobs_dir() -> str:
    return os.path.join(get_host_dir(), "jobs")


def get_job_path(job_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError(f"No job {job_id!r}")
    return os.path.join(get_jobs_dir(), f"{job_id}.json")


def get_job_log_path(job_id: str) -> str:
    return get_job_path(job_id).removesuffix(".json") + ".log"


def get_job_log(job_id: str) -> str:
    """What a job has printed so far, without terminal colors, up to its
    last ``MAX_LOG_CHARS``, so it fits in a message.
    """
    log_path = get_job_log_path(job_id)
    if not os.path.isfile(log_path):
        return ""
    with open(log_path, "rb") as f:
        f.seek(max(0, os.path.getsize(log_path) - MAX_LOG_CHARS))
        text = f.read().decode(errors="replace")
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def get_n_pipeline_stages(wdir: str) -> int | None:
    """How many stages a run of the pipeline in ``wdir`` goes through, with
    each of a stage's iterations, e.g., from ``iterate_over``, counted, as
    DVC lists them as it runs.
    """
    import math

    dvc_yaml_path = os.path.join(wdir, "dvc.yaml")
    if not os.path.isfile(dvc_yaml_path):
        return None
    try:
        with open(dvc_yaml_path) as f:
            stages = calkit.ryaml.load(f).get("stages") or {}
    except Exception:
        return None
    n_stages = 0
    for stage in stages.values():
        if "matrix" in stage:
            n_stages += math.prod(len(v) for v in stage["matrix"].values())
        elif "foreach" in stage:
            n_stages += len(stage["foreach"])
        else:
            n_stages += 1
    return n_stages


def get_job_progress(log: str, n_stages: int | None) -> dict:
    """What a job is doing now, from what it's printed: getting ready,
    syncing with Overleaf, running a stage, or saving, and for stages, the
    one running and how many are done out of ``n_stages``.
    """
    phase = "starting"
    stage = None
    seen: list[str] = []
    for line in log.splitlines():
        line = line.strip()
        if match := re.match(r"(?:Running stage|Stage) '([^']+)'", line):
            name = match.group(1)
            if name not in seen:
                seen.append(name)
            running = line.startswith("Running stage")
            phase = "running"
            stage = name if running else None
        elif "Compiling DVC pipeline" in line:
            phase = "running"
        elif re.match(r"Syncing .* with Overleaf", line):
            phase = "syncing"
        elif line.startswith("Saving the project"):
            phase = "saving"
        elif line.startswith("Pipeline completed"):
            phase = "finishing"
            stage = None
    n_done = len(seen) - (1 if stage else 0)
    return {
        "phase": phase,
        "stage": stage,
        "n_done": n_done,
        # More than it said, e.g., from a subproject's pipeline
        "n_stages": max(n_stages, len(seen)) if n_stages else None,
    }


def get_job(job_id: str) -> dict:
    """A job's record, with how it ended, and the end of what it printed
    once it has.
    """
    job_path = get_job_path(job_id)
    if not os.path.isfile(job_path):
        raise ValueError(f"No job {job_id!r}")
    with open(job_path) as f:
        job: dict = json.load(f)
    # One whose process died without saying so, e.g., at a restart
    if job["status"] == "running" and not is_running(job.get("pid")):
        job["status"] = "failed"
        job["error"] = "It stopped without finishing"
    # What it's doing, and the last of what it printed, while it runs
    if job["status"] == "running":
        log = get_job_log(job_id)
        n_stages = (
            get_n_pipeline_stages(job["wdir"])
            if job["kind"] == "run"
            else None
        )
        job["progress"] = get_job_progress(log, n_stages)
        lines = [x.strip() for x in log.splitlines() if x.strip()]
        job["output"] = "\n".join(lines[-LIVE_OUTPUT_LINES:])
    return job


def is_running(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        res = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
        )
        return str(pid) in res.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def list_jobs() -> list[dict]:
    """Every job's record, newest first."""
    jobs_dir = get_jobs_dir()
    if not os.path.isdir(jobs_dir):
        return []
    jobs = []
    for fname in os.listdir(jobs_dir):
        if fname.endswith(".json"):
            try:
                jobs.append(get_job(fname.removesuffix(".json")))
            except ValueError:
                continue
    return sorted(jobs, key=lambda j: j["created"], reverse=True)


def start_job(msg: dict) -> dict:
    """Start a job for a project, in a process of its own: running its
    pipeline, then saving and syncing with Overleaf unless ``sync`` is
    false, as ``calkit run --save --overleaf`` does, syncing a
    folder with Overleaf, or cloning it to a ``location``, returning its
    record.
    """
    import uuid
    from datetime import datetime, timezone

    kind = msg.get("kind")
    if kind not in JOB_KINDS:
        raise ValueError(f"Unknown kind of job {kind!r}")
    project = msg.get("project")
    owner, _, name = str(project).partition("/")
    if not owner or not name or "/" in name:
        raise ValueError("A project is given as 'owner/name'")
    calkit_cmd = [sys.executable, "-m", "calkit"]
    if kind == "install-editor":
        # VS Code, the only editor Calkit installs, for opening the project
        wdir = calkit.get_user_home()
        cmd = calkit_cmd + ["install", "code", "--yes"]
    elif kind == "clone":
        location = msg.get("location") or os.path.join(
            calkit.get_user_home(), "calkit", name
        )
        if not isinstance(location, str):
            raise ValueError("A location must be a string")
        location = os.path.abspath(os.path.expanduser(location))
        if os.path.exists(location) and os.listdir(location):
            raise ValueError(f"{location} is already there and isn't empty")
        wdir = os.path.dirname(location)
        os.makedirs(wdir, exist_ok=True)
        cmd = calkit_cmd + ["clone", f"{owner}/{name}", location]
    else:
        paths = get_checkout_paths(owner, name)
        if not paths:
            raise ValueError(f"{owner}/{name} isn't on this computer")
        wdir = paths[0]
        if kind == "run":
            # One at a time, as on the hub
            for job in list_jobs():
                if (
                    job["kind"] == "run"
                    and job["wdir"] == wdir
                    and job["status"] in ("queued", "running")
                ):
                    raise ValueError("The pipeline is already running here")
            # Saved and synced with Overleaf after unless asked not to
            cmd = calkit_cmd + ["run"]
            if msg.get("sync", True):
                cmd += ["--save", "--overleaf"]
        else:
            folder = msg.get("path")
            if not isinstance(folder, str):
                raise ValueError("A folder synced with Overleaf is needed")
            cmd = calkit_cmd + ["overleaf", "sync", folder]
    job_id = uuid.uuid4().hex
    repo_info: dict[str, Any] = {"git_rev": None, "branch": None}
    if kind not in ("clone", "install-editor"):
        from calkit.git import get_repo

        repo = get_repo(wdir)
        repo_info["git_rev"] = repo.head.commit.hexsha
        repo_info["branch"] = (
            None if repo.head.is_detached else repo.active_branch.name
        )
    job = {
        "id": job_id,
        "kind": kind,
        "project": f"{owner}/{name}",
        "wdir": wdir,
        "location": cmd[-1] if kind == "clone" else None,
        "cmd": cmd,
        "status": "queued",
        "created": datetime.now(timezone.utc).isoformat(),
        "started": None,
        "finished": None,
        "pid": None,
        "returncode": None,
        "output": None,
        "error": None,
        "result": None,
    } | repo_info
    os.makedirs(get_jobs_dir(), exist_ok=True)
    with open(get_job_path(job_id), "w") as f:
        json.dump(job, f)
    # Outliving the host, which the browser stops once the extension's
    # done with it, and, on Windows, the job object the browser starts the
    # host in
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_BREAKAWAY_FROM_JOB
            | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(
        [sys.executable, "-m", "calkit.browser_link", "job", job_id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=get_login_shell_env(),
        **kwargs,
    )
    # Only the oldest finished ones are dropped
    finished = [
        j for j in list_jobs() if j["status"] not in ("queued", "running")
    ]
    for old in finished[MAX_JOBS_KEPT:]:
        os.remove(get_job_path(old["id"]))
    return job


def run_job(job_id: str) -> None:
    """Run a job started with ``start_job``, recording how it went."""
    from datetime import datetime, timezone

    import calkit.git

    def save(job: dict) -> None:
        tmp_path = get_job_path(job_id) + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(job, f)
        os.replace(tmp_path, get_job_path(job_id))

    def get_head(path: str) -> str | None:
        try:
            return calkit.git.get_repo(path).head.commit.hexsha
        except Exception:
            return None

    def get_overleaf_heads() -> dict[str, str | None]:
        import calkit.overleaf

        heads = {}
        for s in calkit.overleaf.get_sync_info(wdir=job["wdir"]).values():
            if s.get("project_id"):
                clone = os.path.join(
                    job["wdir"],
                    calkit.overleaf.get_project_dir(s["project_id"]),
                )
                heads[s["project_id"]] = get_head(clone)
        return heads

    with open(get_job_path(job_id)) as f:
        job = json.load(f)
    job |= {
        "status": "running",
        "pid": os.getpid(),
        "started": datetime.now(timezone.utc).isoformat(),
    }
    save(job)
    before = {}
    if job["kind"] == "sync":
        before = {"project": get_head(job["wdir"]), **get_overleaf_heads()}
    # Written as it goes, unbuffered, so how far it's got can be read while
    # it runs
    with open(get_job_log_path(job_id), "w") as out:
        try:
            returncode = subprocess.call(
                job["cmd"],
                cwd=job["wdir"],
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=os.environ | {"PYTHONUNBUFFERED": "1"},
                text=True,
            )
        except OSError as e:
            out.write(str(e))
            returncode = 1
    output = get_job_log(job_id)
    lines = [x.strip() for x in output.splitlines() if x.strip()]
    job |= {
        "returncode": returncode,
        "finished": datetime.now(timezone.utc).isoformat(),
        # The end, which says how it went, and fits in a message
        "output": "\n".join(lines[-40:]),
    }
    if returncode != 0:
        error = next(
            (x for x in reversed(lines) if x.startswith("Error: ")),
            lines[-1] if lines else "It failed",
        ).removeprefix("Error: ")
        job |= {"status": "failed", "error": error}
        if re.search(r"overleaf_token|overleaf login", error):
            job |= {
                "error": OVERLEAF_AUTH_MISSING,
                # As the hub says it, so the extension asks for credentials
                "error_status": 401,
            }
    else:
        job["status"] = "succeeded"
        if job["kind"] == "clone":
            job["result"] = {"path": job["location"]}
            calkit.record_project_path(job["location"])
        elif job["kind"] == "sync":
            after = {"project": get_head(job["wdir"]), **get_overleaf_heads()}
            overleaf_ids = [k for k in after if k != "project"]
            job["result"] = {
                "commits_from_overleaf": 0,
                "overleaf_commit": next(
                    (after[k] for k in overleaf_ids if after[k]), ""
                ),
                "project_commit": after["project"] or "",
                "committed_overleaf": any(
                    after[k] != before.get(k) for k in overleaf_ids
                ),
                "committed_project": after["project"] != before["project"],
            }
    save(job)


def get_checkout_status(wdir: str) -> dict:
    """What's in a checkout that isn't saved, i.e., committed and pushed,
    or synced to Overleaf, without reaching the network, so it's quick and
    works offline.

    Overleaf's side is as of the last sync, which pulled it, so files listed
    as to push are ones changed here since, not edits made on Overleaf.
    """
    from filelock import FileLock, Timeout

    import calkit.git
    import calkit.overleaf
    from calkit.hub.link import get_workspace_git_status

    git_status = get_workspace_git_status(wdir, fetch=False)
    git_info = git_status["git"]
    unsaved = sorted(
        set(git_info["changed_files"])
        | set(git_info["staged_files"])
        | set(git_info["untracked_files"])
    )
    overleaf = []
    main_repo = calkit.git.get_repo(wdir)
    for path_in_project, sync_info in calkit.overleaf.get_sync_info(
        wdir=wdir
    ).items():
        project_id = sync_info.get("project_id")
        if not project_id:
            continue
        clone_path = os.path.join(
            wdir, calkit.overleaf.get_project_dir(project_id)
        )
        folder: dict[str, Any] = {"path": path_in_project}
        # Without a sync from this checkout, e.g., when the hub syncs it,
        # there's nothing here to compare with
        if not os.path.isdir(os.path.join(clone_path, ".git")):
            overleaf.append(folder | {"never_synced": True})
            continue
        # A sync going on would change what it's compared with
        file_lock = FileLock(clone_path + ".lock")
        try:
            file_lock.acquire(timeout=0)
        except Timeout:
            overleaf.append(folder | {"syncing": True})
            continue
        prev_wdir = os.getcwd()
        try:
            os.chdir(wdir)
            sync_status = calkit.overleaf.get_sync_status(
                main_repo=main_repo,
                overleaf_repo=calkit.git.get_repo(clone_path),
                path_in_project=path_in_project,
            )
            to_push = [f["project_path"] for f in sync_status["files_to_push"]]
            folder |= {
                "files_to_push": to_push[:MAX_LISTED_FILES],
                "n_files_to_push": len(to_push),
                "n_files_to_delete": len(sync_status["files_to_delete"]),
            }
        except Exception as e:
            folder["error"] = str(e)
        finally:
            os.chdir(prev_wdir)
            file_lock.release()
        overleaf.append(folder)
    return {
        "path": wdir,
        "branch": git_info["branch"],
        "unsaved_files": unsaved[:MAX_LISTED_FILES],
        "n_unsaved_files": len(unsaved),
        "commits_ahead": git_status["commits_ahead"],
        "overleaf": overleaf,
    }


def serve(stdin: BinaryIO, stdout: BinaryIO) -> None:
    """Answer the browser's requests until it disconnects."""
    while True:
        try:
            msg = read_message(stdin)
        except ValueError as e:
            write_message(stdout, {"id": None, "ok": False, "error": str(e)})
            continue
        if msg is None:
            return
        write_message(stdout, get_reply(msg))


def get_host_dir() -> str:
    """Where the host's launcher and Windows manifest are kept."""
    return os.path.join(
        calkit.get_user_home(),
        ".calkit",
        f"browser-link{calkit.get_env_suffix()}",
    )


def get_launcher_path() -> str:
    name = "calkit-native-host" + (".bat" if os.name == "nt" else "")
    return os.path.join(get_host_dir(), name)


def get_launcher_text() -> str:
    """A script that starts the host with this Python, since a manifest
    names one program to run, and the browser may not have the PATH a
    terminal does.
    """
    if os.name == "nt":
        return f'@echo off\r\n"{sys.executable}" -m calkit.browser_link %*\r\n'
    return f'#!/bin/sh\nexec "{sys.executable}" -m calkit.browser_link "$@"\n'


def get_manifest(browser: str, extension_ids: list[str] = []) -> dict:
    """The host's manifest for a browser, naming the extensions that may
    start it, and any others given, e.g., an unpacked one in development.
    """
    manifest: dict[str, Any] = {
        "name": HOST_NAME,
        "description": "Calkit",
        "path": get_launcher_path(),
        "type": "stdio",
    }
    if browser == "firefox":
        manifest["allowed_extensions"] = FIREFOX_EXTENSION_IDS + [
            i for i in extension_ids if "@" in i
        ]
    else:
        manifest["allowed_origins"] = [
            f"chrome-extension://{i}/"
            for i in CHROME_EXTENSION_IDS
            + [i for i in extension_ids if "@" not in i]
        ]
    return manifest


def get_manifest_paths() -> dict[str, str]:
    """Where each browser that's been run here looks for the host's
    manifest, by browser, leaving out Windows, which uses the registry.
    """
    home = calkit.get_user_home()
    paths = {}
    for browser, base in MANIFEST_DIRS.get(platform.system(), {}).items():
        base_path = os.path.join(home, base)
        if not os.path.isdir(base_path):
            continue
        subdir = "NativeMessagingHosts"
        if browser == "firefox" and platform.system() == "Linux":
            subdir = "native-messaging-hosts"
        paths[browser] = os.path.join(base_path, subdir, f"{HOST_NAME}.json")
    return paths


def install_host(extension_ids: list[str] = []) -> list[str]:
    """Let the extension start the host, returning the browsers it can do
    so from.
    """
    os.makedirs(get_host_dir(), exist_ok=True)
    launcher_path = get_launcher_path()
    with open(launcher_path, "w", newline="") as f:
        f.write(get_launcher_text())
    if sys.platform != "win32":
        os.chmod(launcher_path, 0o755)
        browsers = []
        for browser, path in get_manifest_paths().items():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(get_manifest(browser, extension_ids), f, indent=2)
            browsers.append(browser)
        return browsers
    import winreg

    for browser, key in WINDOWS_REGISTRY_KEYS.items():
        path = os.path.join(get_host_dir(), f"{HOST_NAME}.{browser}.json")
        with open(path, "w") as f:
            json.dump(get_manifest(browser, extension_ids), f, indent=2)
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, f"{key}\\{HOST_NAME}"
        ) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, path)
    return list(WINDOWS_REGISTRY_KEYS)


def get_host_status() -> dict:
    """Whether the extension can start the host here: the launcher and the
    Python it runs, the browsers it's registered with, by browser, with the
    extensions each allows, or None, and whether it answers when started
    as a browser starts it, with its ``version`` or an ``error``.
    """

    def get_allowed_ids(manifest_path: str | None) -> list[str] | None:
        if not manifest_path:
            return None
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except (OSError, ValueError):
            return None
        if "allowed_extensions" in manifest:
            return list(manifest["allowed_extensions"])
        return [
            o.removeprefix("chrome-extension://").rstrip("/")
            for o in manifest.get("allowed_origins", [])
        ]

    launcher_path = get_launcher_path()
    status: dict[str, Any] = {
        "launcher_path": launcher_path,
        "python_path": None,
        "browsers": {},
        "version": None,
        "error": None,
    }
    if sys.platform == "win32":
        import winreg

        for browser, key in WINDOWS_REGISTRY_KEYS.items():
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, f"{key}\\{HOST_NAME}"
                ) as k:
                    manifest_path = winreg.QueryValue(k, None)
            except OSError:
                manifest_path = None
            status["browsers"][browser] = get_allowed_ids(manifest_path)
    else:
        for browser, path in get_manifest_paths().items():
            status["browsers"][browser] = get_allowed_ids(path)
    if not os.path.isfile(launcher_path):
        status["error"] = "Not installed"
        return status
    with open(launcher_path) as f:
        match = re.search(r'"([^"]+)" -m calkit', f.read())
    if match:
        status["python_path"] = match.group(1)
    # Started as Chrome starts it, naming the extension connecting
    ping = json.dumps({"type": "ping", "id": 1}).encode()
    try:
        res = subprocess.run(
            [launcher_path, f"chrome-extension://{CHROME_EXTENSION_IDS[0]}/"],
            input=struct.pack("=I", len(ping)) + ping,
            capture_output=True,
            timeout=60,
        )
        reply = read_message(io.BytesIO(res.stdout))
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        status["error"] = str(e)
        return status
    if reply is None or not reply.get("ok"):
        detail = res.stderr.decode(errors="replace").strip().splitlines()
        status["error"] = (
            detail[-1] if detail else "It started, but didn't answer"
        )
        return status
    status["version"] = reply["result"]["version"]
    return status


def uninstall_host() -> None:
    """Remove what lets the extension start the host."""
    import shutil

    if sys.platform == "win32":
        import winreg

        for key in WINDOWS_REGISTRY_KEYS.values():
            try:
                winreg.DeleteKey(
                    winreg.HKEY_CURRENT_USER, f"{key}\\{HOST_NAME}"
                )
            except FileNotFoundError:
                pass
    for path in get_manifest_paths().values():
        if os.path.isfile(path):
            os.remove(path)
    shutil.rmtree(get_host_dir(), ignore_errors=True)


if __name__ == "__main__":
    # Windows would otherwise turn a newline in a message into two bytes
    if sys.platform == "win32":
        import msvcrt

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    # A job the host started, rather than the browser, which names the
    # extension connecting
    if sys.argv[1:2] == ["job"]:
        run_job(sys.argv[2])
    else:
        serve(sys.stdin.buffer, sys.stdout.buffer)
