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

import functools
import io
import json
import os
import platform
import re
import struct
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable
from typing import Any, BinaryIO

import calkit
from calkit.core import get_calkit_cmd

HOST_NAME = "io.calkit.native"
CHROME_EXTENSION_IDS = ["idhdomgapfolnpffanajdckdaojencal"]
FIREFOX_EXTENSION_IDS = ["browser-ext@calkit.io"]
# How many of a checkout's files its status lists, so it fits in a message
MAX_LISTED_FILES = 50
# The most of a run's log sent at once, how much of what a job prints its
# record keeps, and how much of that shows while it runs
MAX_LOG_CHARS = 200_000
OUTPUT_LINES_KEPT = 40
LIVE_OUTPUT_LINES = 8
# How often a running job's record is brought up to date
JOB_SAVE_SECONDS = 0.5
# The lines that say how far a job has got, as get_job_progress reads them
PROGRESS_LINE_RE = re.compile(
    r"Running stage|Stage '|Compiling DVC pipeline|Syncing .* with Overleaf"
    r"|Saving the project|Pipeline completed"
)
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
# How long opening a project waits to hear it failed
OPEN_TIMEOUT_SECONDS = 30
# Chrome won't take a bigger message from a host
MAX_MESSAGE_BYTES = 1024 * 1024
# How long the checkouts found for a project are trusted, since finding
# them means searching the home folder, kept on disk, since each process
# the browser starts would otherwise search again; not finding any is
# trusted for less, since it may be cloned any time
CHECKOUTS_TTL_SECONDS = 24 * 3600
NO_CHECKOUTS_TTL_SECONDS = 600
# How long after pulling from Overleaf a status is taken as up to date,
# e.g., for the same panel loading twice
PULL_FRESH_SECONDS = 10
# How often an Overleaf project no checkout here syncs with is looked for
# again, since that searches the home folder too
LOOKUP_RESCAN_SECONDS = 600
# How long a pipeline's status is reused for the provenance of figures
PIPELINE_REUSE_SECONDS = 10
# A file bigger than this is stored with DVC rather than in Git, as the
# hub stores an upload
FILE_GIT_MAX_BYTES = 1_000_000
# What a job, e.g., a pipeline run, can do, as the command it runs in the
# project's checkout, so nothing else can be run through one
JOB_KINDS = (
    "run",
    "sync",
    "save",
    "clone",
    "create",
    "install-editor",
    "detect",
)
# Those that change a checkout, so only one at a time works on each
CHECKOUT_JOB_KINDS = ("run", "sync", "save")
# A job that hasn't started by then never will, e.g., its process died first
JOB_START_SECONDS = 60
# Reading a script for a stage, as the hub allows it
DETECT_JOB_SECONDS = 120
# A GitHub owner or repo name, so neither is read as an option or a URL
PROJECT_PART_RE = re.compile(r"^(?!\.+$)[A-Za-z0-9_.][A-Za-z0-9_.-]*$")
# The requests answered alongside others, since they don't change the
# working directory or start anything that has to be one at a time, e.g.,
# opening a project, which can wait a while to hear it failed
CONCURRENT_REQUEST_TYPES = (
    "ping",
    "projects.find",
    "project.open",
    "checkouts.get",
    "overleaf.lookup",
    "publication.pdf",
    "publication.synctex",
    "publication.source",
    "project.originSuggestions",
    "project.printedNumbers",
    "folder.choose",
    "job.get",
    "job.log",
    "jobs.list",
)
# How many of a project's finished jobs are kept
MAX_JOBS_KEPT = 20
# How much of a PDF goes in each message, which base64 makes a third
# bigger, keeping it well under the browser's limit
PDF_CHUNK_BYTES = 600_000
# A results file bigger than this isn't read for a value, as on the hub
MAX_VALUE_FILE_BYTES = 10 * 1024 * 1024
# The most of a LaTeX file read for the extension, which no paper's comes near
SOURCE_MAX_BYTES = 1_000_000
OVERLEAF_AUTH_MISSING = (
    "Calkit on this machine has no Overleaf credentials that work; connect "
    "Overleaf to Calkit, which saves them for every machine you use"
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


def split_project(project: Any) -> tuple[str, str]:
    """A project's owner and name, from ``owner/name``."""
    owner, _, name = (
        project.partition("/") if isinstance(project, str) else ("", "", "")
    )
    if not PROJECT_PART_RE.match(owner) or not PROJECT_PART_RE.match(name):
        raise ValueError("A project is given as 'owner/name'")
    return owner, name


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
    - ``project.figures``, ``project.pipeline``, and ``project.provenance``:
      a checkout's figures, pipeline, and where a path in it, or a value in
      a results file, came from, shaped as the hub's are.
    - ``publication.pdf``: part of the PDF a folder synced with Overleaf
      builds to, from ``offset``, with how fresh it is, so it can be shown
      in place of Overleaf's.
    - ``publication.source``: a LaTeX file in a folder synced with
      Overleaf, as it is here, to map a line SyncTeX gives for a PDF built
      here to the same line in Overleaf's copy.
    - ``project.originSuggestions``: what likely makes a file with no
      origin, e.g., a notebook that writes it, for someone to confirm.
    - ``folder.choose``: a folder chosen in this machine's own dialog,
      e.g., one with an analysis to clone a project into, and whether it
      has anything in it.
    - ``job.start``, ``job.get``, and ``jobs.list``: run something that
      takes a while, i.e., a pipeline run, an Overleaf sync, or a clone, in
      a process of its own, which outlives the host, and check on it.
    """
    import contextlib

    import typer

    req_id = msg.get("id")
    # What Calkit's helpers print to stderr, so an error they raise after
    # saying why can be told; only for requests that take turns, since it's
    # for the whole process
    printed = io.StringIO()
    try:
        with (
            contextlib.nullcontext()
            if msg.get("type") in CONCURRENT_REQUEST_TYPES
            else contextlib.redirect_stderr(printed)
        ):
            result = get_result(msg)
    except OverleafAuthMissing as e:
        # As the hub says it, so the extension asks for credentials there
        return {"id": req_id, "ok": False, "error": str(e), "status": 401}
    except (typer.Exit, SystemExit):
        lines = [x for x in printed.getvalue().splitlines() if x.strip()]
        error = ANSI_ESCAPE_RE.sub("", lines[-1]) if lines else "It failed"
        return {
            "id": req_id,
            "ok": False,
            "error": error.removeprefix("Error: "),
        }
    except Exception as e:
        return {"id": req_id, "ok": False, "error": str(e)}
    return {"id": req_id, "ok": True, "result": result}


def get_result(msg: dict) -> Any:
    """What a request from the extension asks for, as ``get_reply`` lists."""
    kind = msg.get("type")
    if kind == "ping":
        result: Any = {"version": calkit.__version__} | get_editor_info()
    elif kind == "projects.find":
        owner, name = split_project(msg.get("project"))
        found = calkit.get_project_checkouts(
            name, owner=owner, search_protected=False
        )
        result = {"paths": sorted(found)}
    elif kind == "project.open":
        owner, name = split_project(msg.get("project"))
        cmd = get_calkit_cmd() + ["open", "project"]
        cmd += [f"{owner}/{name}", "--with", get_editor_info()["editor"]]
        # The checkout everything else here uses, e.g., a worktree
        # chosen for it, rather than one the command finds
        paths = get_checkout_paths(owner, name)
        if paths:
            cmd += ["--checkout", paths[0]]
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
            proc = start_detached(
                cmd,
                cwd=calkit.get_user_home(),
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=get_login_shell_env(),
                text=True,
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
                    f"{owner}/{name} isn't on this machine; clone it "
                    f"with 'calkit clone {owner}/{name}'"
                )
            raise ValueError(error)
        result = {}
    elif kind == "project.status":
        owner, name = split_project(msg.get("project"))
        result = {
            "checkouts": [
                get_checkout_status(p)
                for p in sorted(get_checkout_paths(owner, name))
            ]
        }
    elif kind == "checkouts.get":
        owner, name = split_project(msg.get("project"))
        paths = get_checkout_paths(owner, name)
        result = {"paths": paths, "path": paths[0] if paths else None}
    elif kind == "checkouts.choose":
        owner, name = split_project(msg.get("project"))
        path = msg.get("path")
        # E.g., a worktree made since they were last looked for
        if path not in get_checkout_paths(owner, name) and (
            path not in get_checkout_paths(owner, name, refresh=True)
        ):
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
            raise ValueError(f"{owner}/{name} isn't on this machine")
        result = get_overleaf_sync_statuses(
            paths[0],
            overleaf_project_id=msg.get("overleaf_project_id"),
            path=msg.get("path"),
            pull=msg.get("pull", True) is not False,
            overleaf_files=msg.get("overleaf_files"),
            overleaf_texts=msg.get("overleaf_texts"),
        )
    elif kind == "project.figures":
        owner, name = split_project(msg.get("project"))
        paths = get_checkout_paths(owner, name)
        if not paths:
            raise ValueError(f"{owner}/{name} isn't on this machine")
        result = get_figures(paths[0])
    elif kind == "project.contentPaths":
        owner, name = split_project(msg.get("project"))
        paths = get_checkout_paths(owner, name)
        if not paths:
            raise ValueError(f"{owner}/{name} isn't on this machine")
        result = get_content_paths(paths[0])
    elif kind == "project.stageFromScriptOrNotebook":
        owner, name = split_project(msg.get("project"))
        paths = get_checkout_paths(owner, name)
        if not paths:
            raise ValueError(f"{owner}/{name} isn't on this machine")
        result = add_stage_from_script(paths[0], msg)
    elif kind == "project.moveExternalData":
        owner, name = split_project(msg.get("project"))
        paths = get_checkout_paths(owner, name)
        if not paths:
            raise ValueError(f"{owner}/{name} isn't on this machine")
        result = move_external_data(paths[0], msg)
    elif kind in ("project.recordOrigin", "project.addExportStage"):
        owner, name = split_project(msg.get("project"))
        paths = get_checkout_paths(owner, name)
        if not paths:
            raise ValueError(f"{owner}/{name} isn't on this machine")
        if kind == "project.recordOrigin":
            result = record_origin(paths[0], msg)
        else:
            result = add_export_stage(paths[0], msg)
    elif kind == "project.pipeline":
        owner, name = split_project(msg.get("project"))
        paths = get_checkout_paths(owner, name)
        if not paths:
            raise ValueError(f"{owner}/{name} isn't on this machine")
        result = get_pipeline(paths[0])
    elif kind == "project.provenance":
        owner, name = split_project(msg.get("project"))
        paths = get_checkout_paths(owner, name)
        if not paths:
            raise ValueError(f"{owner}/{name} isn't on this machine")
        key = msg.get("key")
        if key is not None and not isinstance(key, str):
            raise ValueError("A key must be a string")
        result = get_provenance(paths[0], msg.get("path"), key)
    elif kind == "project.originSuggestions":
        from calkit.provenance import get_origin_suggestions

        owner, name = split_project(msg.get("project"))
        paths = get_checkout_paths(owner, name)
        if not paths:
            raise ValueError(f"{owner}/{name} isn't on this machine")
        path = get_project_path(paths[0], msg.get("path"), "file")
        result = get_origin_suggestions(
            path, get_content_paths(paths[0]), wdir=paths[0]
        )
    elif kind == "project.printedNumbers":
        owner, name = split_project(msg.get("project"))
        paths = get_checkout_paths(owner, name)
        if not paths:
            raise ValueError(f"{owner}/{name} isn't on this machine")
        result = get_printed_numbers(paths[0])
    elif kind == "project.addCellOutput":
        from calkit.notebooks import add_cell_output

        owner, name = split_project(msg.get("project"))
        paths = get_checkout_paths(owner, name)
        if not paths:
            raise ValueError(f"{owner}/{name} isn't on this machine")
        notebook = get_project_path(paths[0], msg.get("notebook"), "notebook")
        result = add_cell_output(
            notebook,
            {
                "kind": "value",
                "cell_id": msg.get("cell_id"),
                "variable_name": msg.get("variable_name"),
            },
            stage=msg.get("stage"),
            wdir=paths[0],
        )
    elif kind in ("publication.pdf", "publication.synctex"):
        owner, name = split_project(msg.get("project"))
        paths = get_checkout_paths(owner, name)
        if not paths:
            raise ValueError(f"{owner}/{name} isn't on this machine")
        offset = msg.get("offset", 0)
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("An offset must be a whole number")
        result = get_pdf_chunk(
            paths[0],
            str(msg.get("folder")),
            offset,
            synctex=kind == "publication.synctex",
        )
    elif kind == "publication.source":
        owner, name = split_project(msg.get("project"))
        paths = get_checkout_paths(owner, name)
        if not paths:
            raise ValueError(f"{owner}/{name} isn't on this machine")
        result = get_source_text(
            paths[0], str(msg.get("folder")), str(msg.get("path"))
        )
    elif kind == "folder.choose":
        result = choose_folder(str(msg.get("prompt") or "Select a folder"))
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
    return result


def start_detached(cmd: list[str], **kwargs: Any) -> subprocess.Popen:
    """Start a process that outlives the host, which the browser stops once
    the extension's done with it, and, on Windows, the job object the
    browser starts the host in, where that job allows it.
    """
    if sys.platform != "win32":
        return subprocess.Popen(cmd, start_new_session=True, **kwargs)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(
            cmd,
            creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB,
            **kwargs,
        )
    except OSError:
        return subprocess.Popen(cmd, creationflags=flags, **kwargs)


def check_clone_location(location: str) -> None:
    """Refuse a place to clone to that isn't a folder of the user's own,
    i.e., outside the home folder, or in a hidden or app's folder there,
    e.g., ``~/.config/git``, where what's cloned could be run as config.
    """
    home = os.path.realpath(calkit.get_user_home())
    path = os.path.realpath(location)
    rel = os.path.relpath(path, home)
    parts = rel.split(os.sep)
    if (
        rel == "."
        or parts[0] == ".."
        or any(part.startswith(".") for part in parts)
        or parts[0] in ("Library", "AppData")
    ):
        raise ValueError(
            f"Can't clone to {location}; choose a folder in your home folder"
            ", e.g., ~/calkit"
        )


def choose_folder(prompt: str) -> dict:
    """Ask for a folder in this machine's own dialog, starting in the home
    folder, giving its ``path``, or None if none was chosen, and whether
    it's ``empty``.
    """
    import subprocess
    import sys

    home = calkit.get_user_home()
    env = os.environ | {"CALKIT_PROMPT": prompt, "CALKIT_HOME": home}
    if sys.platform == "darwin":
        # In front of the browser, rather than behind it
        cmd = [
            "osascript",
            "-e",
            "activate",
            "-e",
            "POSIX path of (choose folder with prompt (system attribute "
            '"CALKIT_PROMPT") default location POSIX file (system attribute '
            '"CALKIT_HOME"))',
        ]
    elif sys.platform == "win32":
        cmd = [
            "powershell",
            "-NoProfile",
            "-STA",
            "-Command",
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$d.Description = $env:CALKIT_PROMPT; "
            "$d.SelectedPath = $env:CALKIT_HOME; "
            "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }",
        ]
    else:
        cmd = [
            "zenity",
            "--file-selection",
            "--directory",
            f"--title={prompt}",
            f"--filename={home}/",
        ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    except FileNotFoundError:
        raise ValueError("This machine has no folder dialog; type the path")
    path = res.stdout.strip() if res.returncode == 0 else ""
    if not path:
        return {"path": None, "empty": True}
    path = os.path.normpath(path)
    return {"path": path, "empty": not os.listdir(path)}


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
        found = shutil.which(cmd[0], path=search_path)
        if found is None and editor == "vscode":
            found = install.find("code")
        return found

    search_path: str | None = (get_login_shell_env() or os.environ).get("PATH")
    # The machine's, not a project's another request is working in
    settings = read_config(project_env=False)
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


@functools.cache
def get_login_shell_env() -> dict[str, str] | None:
    """The environment to run Calkit or an editor in, with the login
    shell's PATH, since a browser started from the Dock, e.g., has only the
    system's folders on its PATH, asked for once while the host runs.
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


def get_checkouts_found_path() -> str:
    return os.path.join(get_host_dir(), "checkouts-found.json")


def get_checkouts_found() -> dict[str, list]:
    """When each project's checkouts here were last looked for, by home
    folder, which is where they're searched for, and owner and name, and
    what was found.
    """
    try:
        with open(get_checkouts_found_path()) as f:
            found = json.load(f)
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def set_checkouts_found(key: str, entry: list | None) -> None:
    """Record what was found for one project's checkouts, or forget it
    with ``None``, leaving what other processes found for others.
    """
    from filelock import FileLock

    os.makedirs(get_host_dir(), exist_ok=True)
    path = get_checkouts_found_path()
    with FileLock(path + ".lock", timeout=60):
        found = get_checkouts_found()
        if entry is None:
            found.pop(key, None)
        else:
            found[key] = entry
        calkit.write_json(path, found)


def get_checkouts_key(owner: str, name: str) -> str:
    return f"{calkit.get_user_home()}:{owner}/{name}"


def get_checkout_paths(
    owner: str, name: str, refresh: bool = False
) -> list[str]:
    """A project's checkouts here, the one to use first: the one chosen
    last, else one in ~/calkit, as ``calkit open project`` picks, searched
    for again if ``refresh``.
    """
    import time

    key = get_checkouts_key(owner, name)
    found = get_checkouts_found()
    try:
        found_at, paths = float(found[key][0]), list(found[key][1])
    except (KeyError, TypeError, ValueError, IndexError):
        found_at, paths = 0.0, []
    ttl = CHECKOUTS_TTL_SECONDS if paths else NO_CHECKOUTS_TTL_SECONDS
    if (
        refresh
        or time.time() - found_at > ttl
        or not all(
            os.path.isfile(os.path.join(p, "calkit.yaml")) for p in paths
        )
    ):
        paths = sorted(
            calkit.get_project_checkouts(
                name, owner=owner, search_protected=False
            )
        )
        set_checkouts_found(key, [time.time(), paths])
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

    from filelock import FileLock

    index_path = get_overleaf_index_path()
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    # One lookup at a time updates it, so neither's changes are lost
    with FileLock(index_path + ".lock", timeout=60):
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
        if (
            not links
            and time.time() - index["scanned"] > LOOKUP_RESCAN_SECONDS
        ):
            for path in calkit.find_project_dirs(search_protected=False):
                path = os.path.realpath(path)
                if path not in index["checkouts"]:
                    index["checkouts"][path] = read_checkout(path)
            index["scanned"] = time.time()
            changed = True
            links = get_links(index)
        if changed:
            calkit.write_json(index_path, index)
    return links


# The Overleaf credentials that last worked, while the host runs, since
# reading them can take a while, e.g., from the system keyring, and when
# each copy of an Overleaf project here was last pulled
_overleaf_auth: Any = None
_overleaf_pulled_at: dict[str, float] = {}


def get_overleaf_sync_statuses(
    wdir: str,
    overleaf_project_id: str | None = None,
    path: str | None = None,
    pull: bool = True,
    overleaf_files: dict[str, str] | None = None,
    overleaf_texts: dict[str, str] | None = None,
) -> list[dict]:
    """What a sync of each folder of a checkout synced with Overleaf would
    do, after pulling from Overleaf, as the hub's status reports it,
    optionally only for one ``path`` or Overleaf project.

    Without ``pull``, a folder's copy of Overleaf from the last pull or sync
    is used, if there is one, which takes a fraction of the time, so
    something can be shown while Overleaf is asked. It's used with ``pull``
    too if this pulled it only ``PULL_FRESH_SECONDS`` ago.

    With ``overleaf_files``, the Git hashes of the Overleaf project's files
    by path, from its editor, and ``overleaf_texts``, its documents, a copy
    that has those files counts as pulled, and one that differs only in
    documents is updated from them, without asking Overleaf.

    Overleaf credentials come from Calkit's config, or else the hub, as for
    ``calkit overleaf sync``.
    """
    import contextlib
    import time
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

    global _overleaf_auth

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
                clone_path = calkit.overleaf.get_project_dir(project_id)
                pulled_at = _overleaf_pulled_at.get(
                    os.path.abspath(clone_path)
                )
                fresh = (
                    pulled_at is not None
                    and time.time() - pulled_at < PULL_FRESH_SECONDS
                )
                pulled = (pull and not fresh) or not os.path.isdir(
                    os.path.join(clone_path, ".git")
                )
                with calkit.overleaf.lock(project_id, lambda _: None):
                    if (
                        pulled
                        and overleaf_files is not None
                        and os.path.isdir(os.path.join(clone_path, ".git"))
                    ):
                        overleaf_repo = calkit.git.get_repo(clone_path)
                        if calkit.overleaf.pull_from_editor(
                            overleaf_repo, overleaf_files, overleaf_texts or {}
                        ):
                            pulled = False
                            fresh = True
                            _overleaf_pulled_at[
                                os.path.abspath(clone_path)
                            ] = time.time()
                        overleaf_repo.close()
                    if pulled:
                        if _overleaf_auth is None:
                            _overleaf_auth = _get_overleaf_auth()
                        overleaf_repo, _overleaf_auth = (
                            _get_pulled_overleaf_repo(
                                project_id, _overleaf_auth
                            )
                        )
                        _overleaf_pulled_at[os.path.abspath(clone_path)] = (
                            time.time()
                        )
                    else:
                        overleaf_repo = calkit.git.get_repo(clone_path)
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
                        "pulled": pulled or (pull and fresh),
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
    import posixpath
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
        if stage.get("kind") != "latex" or not isinstance(target, str):
            continue
        # Paths are relative to the stage's working directory, and the PDF
        # goes in its output folder if it has one, as LatexStage.pdf_path
        # says
        stage_wdir = stage.get("wdir") or "."
        if not is_in_folder(posixpath.normpath(f"{stage_wdir}/{target}")):
            continue
        output_dir = stage.get("output_dir")
        built = (
            f"{output_dir}/{PurePosixPath(target).stem}.pdf"
            if output_dir
            else target.removesuffix(".tex") + ".pdf"
        )
        return posixpath.normpath(f"{stage_wdir}/{built}")
    return None


def get_source_text(wdir: str, folder: str, path: str) -> dict:
    """A LaTeX file in a folder synced with Overleaf, by its path there, as
    it is in this checkout.
    """
    import posixpath

    rel_path = posixpath.normpath(posixpath.join(folder, path))
    full_path = os.path.join(wdir, rel_path)
    if not os.path.realpath(full_path).startswith(
        os.path.join(os.path.realpath(os.path.join(wdir, folder)), "")
    ):
        raise ValueError(f"{path} isn't in {folder}")
    if not rel_path.lower().endswith((".tex", ".sty", ".cls", ".bib")):
        raise ValueError(f"{path} isn't a LaTeX file")
    if not os.path.isfile(full_path):
        raise ValueError(f"{rel_path} isn't on this machine")
    if os.path.getsize(full_path) > SOURCE_MAX_BYTES:
        raise ValueError(f"{rel_path} is too big to read")
    with open(full_path, encoding="utf-8", errors="replace") as f:
        return {"path": rel_path, "text": f.read()}


def get_pdf_chunk(
    wdir: str, folder: str, offset: int, synctex: bool = False
) -> dict:
    """Part of the PDF a folder synced with Overleaf builds to, as base64
    ``data``, from ``offset``, with its ``size``, when it was built, the
    commit that saved it, if any, whether it's changed since, and whether
    anything else in the folder has, i.e., it's older than its source.

    With ``synctex``, it's the build's compressed SyncTeX file instead,
    which says where in the source each place in the PDF came from, with
    only when it was built.
    """
    import base64

    import calkit.git

    path = get_pdf_path(wdir, folder)
    if path is None:
        raise ValueError(f"No PDF is built from {folder}")
    if synctex:
        path = os.path.splitext(path)[0] + ".synctex.gz"
    full_path = os.path.join(wdir, path)
    if not os.path.realpath(full_path).startswith(
        os.path.join(os.path.realpath(wdir), "")
    ):
        raise ValueError(f"{path} isn't in the project")
    if not os.path.isfile(full_path):
        raise ValueError(
            f"{path} hasn't been built on this machine; run the pipeline"
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
    if synctex:
        return chunk | {"built": stat.st_mtime}
    # How fresh it is, only with the first part
    if offset == 0:
        repo = calkit.git.get_repo(wdir)
        commit_sha = repo.git.log("-1", "--format=%H", "--", path) or None
        changed = bool(repo.git.status("--porcelain", "--", path).strip())
        # Only what Git would keep counts, so what the build leaves, e.g.,
        # SyncTeX data written just after the PDF, doesn't
        # Unquoted, e.g., for names that aren't ASCII
        sources = [
            p
            for p in repo.git.ls_files(
                "-z", "-co", "--exclude-standard", "--", folder
            ).split("\0")
            if p
        ]
        edited_since = any(
            os.path.getmtime(os.path.join(wdir, source_path)) > stat.st_mtime
            for source_path in sources
            if not source_path.endswith((".pdf", ".log", ".aux", ".fls"))
            and os.path.relpath(source_path, folder).split(os.sep)[0]
            != "_calkit"
            and os.path.isfile(os.path.join(wdir, source_path))
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


def get_run_log_path(wdir: str, started: str) -> str | None:
    """The log ``calkit run`` writes in a project's ``.calkit/local/logs``
    for the run started at or after ``started``, if it's begun one.
    """
    from datetime import datetime

    logs_dir = os.path.join(wdir, ".calkit", "local", "logs")
    if not os.path.isdir(logs_dir):
        return None
    # Each is named for the time, in UTC, its run started
    since = datetime.fromisoformat(started).strftime("%Y-%m-%dT%H-%M-%S")
    names = [
        n
        for n in os.listdir(logs_dir)
        if n.endswith(".log") and n[: len(since)] >= since
    ]
    return os.path.join(logs_dir, max(names)) if names else None


def get_job_log(job_id: str) -> str:
    """A job's log, without terminal colors: for a run, the one Calkit keeps
    in the project, up to its last ``MAX_LOG_CHARS``, so it fits in a
    message, then what came after, e.g., saving and syncing, and otherwise
    the end of what it printed.
    """
    from calkit.cli.main.core import STAGE_OUTPUT_END, STAGE_OUTPUT_START

    job_path = get_job_path(job_id)
    if not os.path.isfile(job_path):
        raise ValueError(f"No job {job_id!r}")
    with open(job_path) as f:
        job = json.load(f)
    output_lines = (job.get("output") or "").splitlines()
    log_path = job.get("log_path")
    if not log_path or not os.path.isfile(log_path):
        return "\n".join(output_lines)
    with open(log_path, "rb") as f:
        f.seek(max(0, os.path.getsize(log_path) - MAX_LOG_CHARS))
        text = ANSI_ESCAPE_RE.sub("", f.read().decode(errors="replace"))
    lines = [
        x
        for x in text.splitlines()
        if x not in (STAGE_OUTPUT_START, STAGE_OUTPUT_END)
    ]
    done_at = next(
        (
            i
            for i in reversed(range(len(output_lines)))
            if output_lines[i].startswith("Pipeline completed")
        ),
        None,
    )
    if done_at is not None:
        lines += output_lines[done_at:]
    return "\n".join(lines)


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
    from datetime import datetime, timezone

    job_path = get_job_path(job_id)
    if not os.path.isfile(job_path):
        raise ValueError(f"No job {job_id!r}")
    with open(job_path) as f:
        job: dict = json.load(f)
    # One whose process died without saying so, e.g., at a restart, or
    # before it could start
    if job["status"] == "running" and not is_running(job.get("pid")):
        job["status"] = "failed"
        job["error"] = "It stopped without finishing"
    elif (
        job["status"] == "queued"
        and (
            datetime.now(timezone.utc) - datetime.fromisoformat(job["created"])
        ).total_seconds()
        > JOB_START_SECONDS
    ):
        job["status"] = "failed"
        job["error"] = "It never started"
    # The last of what it's printed, while it runs
    if job["status"] == "running" and job.get("output"):
        lines = job["output"].splitlines()
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
    folder with Overleaf, saving everything, as ``calkit save -a`` does,
    cloning it to a ``location``, or creating it on a
    ``hub`` from a folder here at ``location``, with an Overleaf project
    imported into it, returning its record.

    A job runs ``cmd``, then each of ``then`` in turn, stopping at the
    first that fails.
    """
    import uuid
    from datetime import datetime, timezone

    kind = msg.get("kind")
    if kind not in JOB_KINDS:
        raise ValueError(f"Unknown kind of job {kind!r}")
    owner, name = split_project(msg.get("project"))
    calkit_cmd = get_calkit_cmd()
    if kind == "install-editor":
        # VS Code, the only editor Calkit installs, for opening the project
        wdir = calkit.get_user_home()
        cmd = calkit_cmd + ["install", "code", "--yes"]
    elif kind == "create":
        # A folder here, e.g., the analysis a paper on Overleaf is written
        # from, made a project on the hub, signing in first if need be,
        # with the paper imported into it, and everything saved, so it's
        # all in version control and backed up from the start
        location = msg.get("location")
        if not isinstance(location, str) or not location:
            raise ValueError("A folder is needed")
        location = os.path.abspath(os.path.expanduser(location))
        check_clone_location(location)
        if not os.path.isdir(location):
            raise ValueError(f"{location} isn't a folder")
        if os.path.exists(os.path.join(location, ".git")):
            raise ValueError(f"{location} is already a Git repo")
        hub = msg.get("hub")
        title = msg.get("title")
        overleaf_url = msg.get("overleafProjectUrl")
        path = msg.get("path")
        doc_kind = msg.get("docKind")
        if not isinstance(hub, str) or not re.fullmatch(
            r"https?://[\w.:-]+/?", hub
        ):
            raise ValueError("A hub URL is needed")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("A title is needed")
        if not isinstance(overleaf_url, str) or not re.fullmatch(
            r"https://www\.overleaf\.com/project/[0-9a-f]+", overleaf_url
        ):
            raise ValueError("An Overleaf project URL is needed")
        if not isinstance(path, str) or not re.fullmatch(
            r"[\w-]+(/[\w-]+)*", path
        ):
            raise ValueError("A folder for the document is needed")
        if not isinstance(doc_kind, str) or not re.fullmatch(
            r"[a-z-]+", doc_kind
        ):
            raise ValueError("A kind of document is needed")
        wdir = location
        cmd = calkit_cmd + ["hub", "login", "--hub", hub]
        then = [
            calkit_cmd
            + ["new", "project", ".", "--hub", hub, "--name", name]
            + ["--title", title.strip()]
            + (["--public"] if msg.get("isPublic") else []),
            calkit_cmd
            + ["overleaf", "import", overleaf_url, path, "--kind", doc_kind],
            calkit_cmd + ["save", "-a", "-m", "Add files from this machine"],
        ]
    elif kind == "clone":
        location = msg.get("location") or os.path.join(
            calkit.get_user_home(), "calkit", name
        )
        if not isinstance(location, str):
            raise ValueError("A location must be a string")
        location = os.path.abspath(os.path.expanduser(location))
        check_clone_location(location)
        if os.path.exists(location) and os.listdir(location):
            raise ValueError(f"{location} is already there and isn't empty")
        wdir = os.path.dirname(location)
        os.makedirs(wdir, exist_ok=True)
        cmd = calkit_cmd + ["clone", f"{owner}/{name}", location]
    else:
        paths = get_checkout_paths(owner, name)
        if not paths:
            raise ValueError(f"{owner}/{name} isn't on this machine")
        wdir = paths[0]
        if kind == "run":
            # Saved and synced with Overleaf after unless asked not to
            cmd = calkit_cmd + ["run"]
            if msg.get("sync", True):
                cmd += ["--save", "--overleaf"]
        elif kind == "save":
            # Everything, as 'calkit save -a' sorts it: big files to DVC,
            # junk ignored
            cmd = calkit_cmd + ["save", "-a", "-m", "Save from Overleaf"]
        elif kind == "detect":
            # What a stage made from a script would be, which can take a
            # while to read, e.g., a notebook
            script_path = get_script_path(wdir, msg.get("scriptPath"))
            cmd = calkit_cmd + ["xr", "--dry-run", "--json", script_path]
        else:
            folder = msg.get("path")
            if not isinstance(folder, str):
                raise ValueError("A folder synced with Overleaf is needed")
            cmd = calkit_cmd + ["overleaf", "sync", folder]
        # One at a time, as on the hub, since each commits
        for job in list_jobs() if kind in CHECKOUT_JOB_KINDS else []:
            if (
                job["kind"] in CHECKOUT_JOB_KINDS
                and job["wdir"] == wdir
                and job["status"] in ("queued", "running")
            ):
                raise ValueError(
                    {
                        "run": "The pipeline is already running here",
                        "sync": "It's already syncing with Overleaf here",
                        "save": "It's already saving here",
                    }[job["kind"]]
                )
    job_id = uuid.uuid4().hex
    repo_info: dict[str, Any] = {"git_rev": None, "branch": None}
    if kind not in ("clone", "create", "install-editor"):
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
        "location": location if kind in ("clone", "create") else None,
        # For a detect, when it was read, so a change since is noticed
        "script_path": cmd[-1] if kind == "detect" else None,
        "script_stat": (
            get_file_stat(os.path.join(wdir, cmd[-1]))
            if kind == "detect"
            else None
        ),
        "cmd": cmd,
        "then": then if kind == "create" else [],
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
    try:
        start_detached(
            get_calkit_cmd("calkit.browser_link") + ["job", job_id],
            cwd=calkit.get_user_home(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=get_login_shell_env(),
        )
    except OSError as e:
        # Otherwise it'd look queued forever, holding up the next run
        job |= {
            "status": "failed",
            "finished": datetime.now(timezone.utc).isoformat(),
            "error": f"Couldn't start it: {e}",
        }
        with open(get_job_path(job_id), "w") as f:
            json.dump(job, f)
        raise
    # Only the oldest finished ones are dropped
    finished = [
        j for j in list_jobs() if j["status"] not in ("queued", "running")
    ]
    for old in finished[MAX_JOBS_KEPT:]:
        os.remove(get_job_path(old["id"]))
    return job


def run_job(job_id: str) -> None:
    """Run a job started with ``start_job``, recording how it went."""
    import collections
    import threading
    import time
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
    # What it prints, read as it goes: the end of it, and the lines that say
    # how far it's got, are kept in its record, since a run's whole log is
    # in the project
    n_stages = (
        get_n_pipeline_stages(job["wdir"]) if job["kind"] == "run" else None
    )
    tail: collections.deque[str] = collections.deque(maxlen=OUTPUT_LINES_KEPT)
    progress_lines: list[str] = []
    # A detect's result is all it prints
    printed: list[str] = []
    lock = threading.Lock()

    def read_output(stream: Any) -> None:
        for line in stream:
            if job["kind"] == "detect":
                printed.append(line)
            line = ANSI_ESCAPE_RE.sub("", line).rstrip()
            if not line.strip():
                continue
            with lock:
                tail.append(line)
                if PROGRESS_LINE_RE.search(line):
                    progress_lines.append(line)

    def update(job: dict) -> None:
        with lock:
            job |= {
                "output": "\n".join(tail),
                "progress": get_job_progress(
                    "\n".join(progress_lines), n_stages
                ),
            }
        if job["kind"] == "run" and not job.get("log_path"):
            job["log_path"] = get_run_log_path(job["wdir"], job["started"])

    try:
        started = time.monotonic()
        for cmd in [job["cmd"], *job.get("then", [])]:
            proc = subprocess.Popen(
                cmd,
                cwd=job["wdir"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=os.environ | {"PYTHONUNBUFFERED": "1"},
                text=True,
                errors="replace",
            )
            reader = threading.Thread(target=read_output, args=(proc.stdout,))
            reader.start()
            while True:
                try:
                    returncode = proc.wait(timeout=JOB_SAVE_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    if (
                        job["kind"] == "detect"
                        and time.monotonic() - started > DETECT_JOB_SECONDS
                    ):
                        proc.kill()
                        tail.append(
                            f"Error: Reading '{job['script_path']}' took "
                            "too long"
                        )
                    update(job)
                    save(job)
            reader.join()
            if returncode != 0:
                break
    except OSError as e:
        tail.append(str(e))
        returncode = 1
    update(job)
    lines = list(tail)
    job.pop("progress")
    job |= {
        "returncode": returncode,
        "finished": datetime.now(timezone.utc).isoformat(),
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
        if job["kind"] in ("clone", "create"):
            project = job["project"]
            # As the hub named a new one, which is only known now
            if job["kind"] == "create":
                ck_info = calkit.load_calkit_info(wdir=job["location"])
                if ck_info.get("owner") and ck_info.get("name"):
                    project = f"{ck_info['owner']}/{ck_info['name']}"
            job["result"] = {"path": job["location"], "project": project}
            calkit.record_project_path(job["location"])
            # So it's found, rather than none being, until that's looked
            # into again
            set_checkouts_found(
                get_checkouts_key(*project.split("/", 1)), None
            )
        elif job["kind"] == "detect":
            import calkit.pipeline.detect

            try:
                job["result"] = (
                    calkit.pipeline.detect.get_detection_from_output(
                        "".join(printed)
                    )
                )
            except ValueError:
                job |= {
                    "status": "failed",
                    "error": f"Can't read '{job['script_path']}'",
                }
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
    # TeX Live takes up to a minute to set up from nothing, so it's done now
    # rather than in the first run, which waits on it otherwise
    if job["kind"] == "clone" and job["status"] == "succeeded":
        try:
            envs = calkit.load_calkit_info(wdir=job["location"]).get(
                "environments", {}
            )
        except Exception:
            envs = {}
        for name, env in (envs or {}).items():
            if env.get("kind") == "texlive":
                subprocess.run(
                    get_calkit_cmd() + ["check", "env", "--name", name],
                    cwd=job["location"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )


def get_figures(wdir: str) -> dict:
    """A checkout's figures as the hub lists them, paths and titles only:
    those declared, detected, and made by a stage or with a recorded
    origin, as ``calkit list figures`` finds them.
    """
    import calkit.pipeline

    items = [
        {
            "path": figure["path"],
            "title": figure.get("title")
            or os.path.splitext(os.path.basename(figure["path"]))[0],
        }
        for figure in calkit.pipeline.list_artifacts("figures", wdir=wdir)
        if isinstance(figure.get("path"), str)
    ]
    return {"items": items, "total": len(items)}


def get_stage_status(stale: list, has_run: bool) -> dict:
    """A stage's status, as the hub gives it, from DVC's stale entries for
    it, i.e., one per iteration that's out of date.
    """
    if not has_run:
        state = "not-run"
    elif not stale:
        state = "up-to-date"
    elif all(s.always_run for s in stale):
        state = "always-run"
    else:
        state = "stale"
    return {
        "status": state,
        "modified_command": any(s.modified_command for s in stale),
        "modified_inputs": list(
            dict.fromkeys(p for s in stale for p in s.modified_inputs)
        ),
        "modified_outputs": list(
            dict.fromkeys(p for s in stale for p in s.modified_outputs)
        ),
        "missing_outputs": list(
            dict.fromkeys(p for s in stale for p in s.stale_outputs)
        ),
    }


def get_printed_numbers(wdir: str) -> list[dict]:
    """Numbers the pipeline's notebooks printed, by notebook and cell, from
    their saved outputs, or the copy the pipeline ran if they're saved
    without, which a number typed into a document may have been copied from.
    """
    import calkit.notebooks

    ck_info = calkit.load_calkit_info(wdir=wdir, read_only=True)
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    found = []
    for name, stage in stages.items():
        # A parameterized notebook's values are cited by file, not notebook
        if (
            not isinstance(stage, dict)
            or stage.get("kind") != "jupyter-notebook"
            or stage.get("parameters")
            or not isinstance(stage.get("notebook_path"), str)
        ):
            continue
        notebook = calkit.notebooks.get_stage_notebook_path(stage)
        executed = calkit.notebooks.get_executed_notebook_path(
            stage["notebook_path"], "notebook"
        )
        for path in (
            notebook,
            os.path.join(stage.get("wdir") or "", executed),
        ):
            fpath = os.path.join(wdir, path)
            try:
                if os.path.getsize(fpath) > MAX_VALUE_FILE_BYTES * 5:
                    continue
                with open(fpath, encoding="utf-8") as f:
                    printed = calkit.notebooks.find_printed_numbers(
                        json.load(f)
                    )
            except (OSError, ValueError):
                continue
            if printed:
                found += [
                    {"notebook": notebook, "stage": name} | p for p in printed
                ]
                break
    return found


def get_content_paths(wdir: str) -> list[str]:
    """Every file in a checkout someone might pick, as the hub lists a
    project's: what Git tracks, and what the pipeline makes with DVC, by its
    own path rather than its ``.dvc`` file, with files not yet saved, e.g.,
    a script just written, since here they're there to pick.
    """
    import calkit.dvc
    import calkit.git

    lock_outs = {
        out["path"]
        for stage in calkit.dvc.read_lock_stages(wdir=wdir).values()
        if isinstance(stage, dict)
        for out in stage.get("outs") or []
        if isinstance(out, dict)
        and isinstance(out.get("path"), str)
        and not str(out.get("md5", "")).endswith(".dir")
    }
    repo = calkit.git.get_repo(wdir)
    # Unquoted, e.g., for names that aren't ASCII
    listed = repo.git.ls_files("-z", "-co", "--exclude-standard").split("\0")
    paths = set(lock_outs)
    for path in listed:
        if not path or path.startswith(".dvc/"):
            continue
        paths.add(path.removesuffix(".dvc"))
    return sorted(paths)


def get_project_path(wdir: str, value: Any, what: str) -> str:
    """A path the extension gave, relative to a checkout, refusing one
    that isn't in it, e.g., through a symlink.
    """
    import posixpath

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"A {what} path is required")
    # One given in full, e.g., from a file picker, is made relative
    path = posixpath.normpath(
        os.path.relpath(
            os.path.join(wdir, value.strip()), os.path.abspath(wdir)
        ).replace("\\", "/")
    )
    real = os.path.realpath(os.path.join(wdir, path))
    if path.startswith("../") or not real.startswith(
        os.path.join(os.path.realpath(wdir), "")
    ):
        raise ValueError(f"'{value}' isn't in the project")
    return path


def is_dvc_tracked(wdir: str, path: str) -> bool:
    """Whether a path in a checkout has its own .dvc file or a folder's,
    whether or not it's pulled.
    """
    parts = path.split("/")
    return any(
        os.path.isfile(os.path.join(wdir, *parts[:n]) + ".dvc")
        for n in range(1, len(parts) + 1)
    )


def get_changed_paths(repo: Any) -> set[str]:
    """Paths in a checkout that aren't committed, untracked ones too."""
    # Unquoted, e.g., for names that aren't ASCII
    entries = iter(repo.git.status("--porcelain", "-z", "-uall").split("\0"))
    paths = set()
    for entry in entries:
        if len(entry) > 3:
            paths.add(entry[3:])
        # A rename or copy is followed by where it came from
        if entry[:1] in ("R", "C"):
            paths.add(next(entries, ""))
    return paths - {""}


def commit_change(
    wdir: str,
    ck_info: dict,
    write: Callable[[], list[str]],
    message: str,
    checked: Iterable[str] = (),
    also_commit: Iterable[str] = (),
    compile_pipeline: bool = True,
) -> None:
    """Change a checkout as the hub would its clone, and commit only that,
    since anything else changed here is someone's work in progress.

    ``write`` writes any files, returning their paths, and may add to
    ``ck_info``, which is written as calkit.yaml after it, and the pipeline
    compiled into dvc.yaml, which is committed too, unless
    ``compile_pipeline`` is false. Refused if calkit.yaml or ``checked``
    have unsaved changes, which would be swept up or overwritten, but not
    dvc.yaml, which is only ever compiled from calkit.yaml, e.g., by
    checking the pipeline's status; ``also_commit`` are committed even so,
    e.g., a new script. If any of it fails, files it changed are put back and files
    that appeared while it ran are deleted. Nothing's pushed; a run and
    sync does that.
    """
    import calkit.git
    import calkit.pipeline

    repo = calkit.git.get_repo(wdir)
    changed_before = get_changed_paths(repo)
    for path in ["calkit.yaml", *checked]:
        if path in changed_before:
            raise ValueError(
                f"{path} has changes that aren't saved; save or discard "
                "them first"
            )
    try:
        written = write()
        with open(
            os.path.join(wdir, "calkit.yaml"), "w", encoding="utf-8"
        ) as f:
            calkit.ryaml.dump(ck_info, f)
        if compile_pipeline:
            calkit.pipeline.to_dvc(ck_info=ck_info, wdir=wdir, write=True)
        commit_paths = sorted(
            (get_changed_paths(repo) - changed_before)
            | set(written)
            | {"calkit.yaml"}
            | (
                {"dvc.yaml"}
                if compile_pipeline
                and os.path.isfile(os.path.join(wdir, "dvc.yaml"))
                else set()
            )
            | (set(also_commit) & changed_before)
        )
        repo.git.add("--", *commit_paths)
        # Already as asked, e.g., when saved before
        if repo.git.diff("--cached", "--name-only", "--", *commit_paths):
            repo.git.commit("-m", message, "--", *commit_paths)
    except Exception:
        # Put back what was written, so it isn't left half done, and a try
        # again isn't refused for unsaved changes to it
        undo = sorted(get_changed_paths(repo) - changed_before)
        if undo:
            repo.git.reset("-q", "--", *undo)
            tracked = [
                p
                for p in repo.git.ls_files("-z", "--", *undo).split("\0")
                if p
            ]
            if tracked:
                repo.git.checkout("--", *tracked)
            for path in set(undo) - set(tracked):
                if os.path.isfile(os.path.join(wdir, path)):
                    os.remove(os.path.join(wdir, path))
        raise


def get_script_path(wdir: str, value: Any) -> str:
    """A script in a checkout that a stage can be made from."""
    import calkit.pipeline.detect

    script_path = get_project_path(wdir, value, "script")
    if not script_path.lower().endswith(calkit.pipeline.detect.SCRIPT_EXTS):
        raise ValueError(calkit.pipeline.detect.SCRIPT_EXTS_MESSAGE)
    if not os.path.isfile(os.path.join(wdir, script_path)):
        raise ValueError(f"'{script_path}' isn't in the project")
    return script_path


def get_file_stat(path: str) -> list[float]:
    """A file's size and modification time, to tell it's changed."""
    stat = os.stat(path)
    return [stat.st_size, stat.st_mtime]


def get_detection(wdir: str, script_path: str, job_id: Any) -> dict:
    """What ``calkit xr --dry-run`` finds in a script: from a detect job
    run for it, unless it's changed since, else read now.

    The job is this host's own record, so what's planned from it can't be
    made up by whoever asks.
    """
    import calkit.pipeline.detect

    # Read in this process from the checkout, as the pipeline's status is;
    # what's answered at the same time uses full paths
    if job_id is None:
        prev_wdir = os.getcwd()
        try:
            os.chdir(wdir)
            return calkit.pipeline.detect.detect_stage(
                [script_path], calkit.load_calkit_info()
            ).model_dump()
        finally:
            os.chdir(prev_wdir)
    job = get_job(str(job_id))
    if (
        job["kind"] != "detect"
        or job["wdir"] != wdir
        or (job["script_path"] != script_path)
    ):
        raise ValueError(f"Job {job_id} didn't read '{script_path}'")
    if job["status"] != "succeeded":
        raise ValueError(job.get("error") or f"Job {job_id} hasn't finished")
    if job["script_stat"] != get_file_stat(os.path.join(wdir, script_path)):
        raise ValueError(f"'{script_path}' changed since it was read")
    detected: dict = job["result"]
    return detected


def add_stage_from_script(wdir: str, msg: dict) -> dict:
    """Make a stage from a script already in a checkout, as the hub does
    for one in its clone, read rather than run, as ``calkit xr --dry-run``
    reads it.

    Without ``save``, nothing is written, so what it would be can be shown
    first. With it, the stage, its environment, and each document changed
    to show what it makes from where it's made are committed, and only
    those, since anything else changed here is someone's work in progress.
    Nothing's pushed; a run and sync does that. With ``detectJob``, what
    the script does is what that detect job found, rather than read now.
    """
    import calkit.git
    import calkit.pipeline
    import calkit.pipeline.detect

    script_path = get_script_path(wdir, msg.get("scriptPath"))
    # Uploads go through the hub, which reads them in a checkout of their
    # own; here the script and its data are already on this machine
    if msg.get("content") is not None:
        raise ValueError(
            "Put the script in the project's folder on this machine, then "
            "find it in the project"
        )
    if msg.get("data"):
        raise ValueError(
            "Move the data the script reads into the project's folder, and "
            "change the script to read it from there"
        )
    shows = msg.get("shows")
    produces = msg.get("produces")
    repo = calkit.git.get_repo(wdir)
    # Elsewhere, e.g., in CI, a stage couldn't run a script Git leaves out
    if repo.ignored(script_path):
        raise ValueError(
            f"'{script_path}' is ignored by Git, so the stage couldn't run "
            "anywhere else; stop ignoring it first"
        )
    ck_info = calkit.load_calkit_info(wdir=wdir)
    plan = calkit.pipeline.detect.get_stage_from_script_plan(
        script_path,
        get_detection(wdir, script_path, msg.get("detectJob")),
        ck_info,
        wdir=wdir,
        shows=get_project_path(wdir, shows, "shown") if shows else None,
        produces=(
            get_project_path(wdir, produces, "output") if produces else None
        ),
        is_dvc_output=lambda path: is_dvc_tracked(wdir, path),
    )
    result = {
        key: value
        for key, value in plan.items()
        if key not in ("stage", "env", "included")
    } | {
        "rewritten": [],
        "included_in": sorted(plan["included"]),
        "git_repo_url": ck_info.get("git_repo_url") or "",
        "saved": False,
    }
    if not msg.get("save"):
        return result
    commit_change(
        wdir,
        ck_info,
        lambda: calkit.pipeline.write_stage_from_script(
            plan, ck_info, wdir=wdir
        ),
        f"Add stage {plan['stage_name']} for {script_path}",
        checked=plan["included"],
        also_commit=[script_path],
    )
    result["saved"] = True
    return result


def move_external_data(wdir: str, msg: dict) -> dict:
    """Copy data a script reads from outside the project into it, point
    the script at the copy, and commit both, so its stage can run anywhere.

    The original is left where it was, since something else may read it.
    """
    import posixpath
    import shutil

    import calkit.detect

    script_path = get_project_path(wdir, msg.get("scriptPath"), "script")
    external = msg.get("external")
    if not isinstance(external, str) or not external.strip():
        raise ValueError("Say which data to move")
    dest = get_project_path(wdir, msg.get("dest"), "data")
    # What a script names is relative to where it runs: a notebook's folder,
    # or else the project
    run_dir = (
        posixpath.dirname(script_path)
        if script_path.lower().endswith(".ipynb")
        else "."
    )
    source = os.path.normpath(
        os.path.join(wdir, run_dir, os.path.expanduser(external))
    )
    if not os.path.exists(source):
        raise ValueError(f"'{external}' isn't on this machine")
    full_dest = os.path.join(wdir, dest)
    if os.path.lexists(full_dest) or is_dvc_tracked(wdir, dest):
        raise ValueError(
            f"'{dest}' is already in the project; pick another place for it"
        )
    full_script = os.path.join(wdir, script_path)
    with open(full_script, encoding="utf-8", newline="") as f:
        original = f.read()
    text, found = calkit.detect.rewrite_paths(
        original, {external: posixpath.relpath(dest, run_dir)}
    )
    if not found:
        raise ValueError(
            f"Couldn't find '{external}' written out in {script_path}; "
            "change it there by hand"
        )
    os.makedirs(os.path.dirname(full_dest) or wdir, exist_ok=True)
    if os.path.isdir(source):
        shutil.copytree(source, full_dest)
    else:
        shutil.copy2(source, full_dest)
    with open(full_script, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    # Git or DVC, by what it is, as 'calkit add' decides
    res = subprocess.run(
        get_calkit_cmd()
        + [
            "add",
            dest,
            script_path,
            "-m",
            f"Move {external} into the project as {dest}",
        ],
        cwd=wdir,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        if os.path.isdir(full_dest):
            shutil.rmtree(full_dest)
        elif os.path.exists(full_dest):
            os.remove(full_dest)
        with open(full_script, "w", encoding="utf-8", newline="") as f:
            f.write(original)
        raise ValueError(
            (res.stderr or res.stdout).strip() or f"Couldn't add {dest}"
        )
    return {"path": dest, "script_path": script_path}


def record_origin(wdir: str, msg: dict) -> dict:
    """Record who made a file in a checkout or where it was imported from,
    as the hub records a misc artifact, committed here.
    """
    import calkit.dvc
    import calkit.provenance

    path = get_project_path(wdir, msg.get("path"), "file")
    created_by = msg.get("createdBy")
    imported_from = msg.get("importedFrom")
    if created_by is not None and not isinstance(created_by, list):
        raise ValueError("Who created it must be a list of people")
    if imported_from is not None and not isinstance(imported_from, dict):
        raise ValueError("Where it was imported from must be a mapping")
    ck_info = calkit.load_calkit_info(wdir=wdir)
    ck_info, entry = calkit.provenance.add_origin(
        ck_info, path, created_by=created_by, imported_from=imported_from
    )
    # Whether tracked by Git or DVC, or made by a stage and not pulled, it
    # has to be in the project to attribute
    lock_outs = [
        out["path"].rstrip("/")
        for stage in calkit.dvc.read_lock_stages(wdir=wdir).values()
        for out in (stage or {}).get("outs") or []
        if isinstance(out, dict) and isinstance(out.get("path"), str)
    ]
    if not (
        os.path.exists(os.path.join(wdir, path))
        or is_dvc_tracked(wdir, path)
        or any(path == o or path.startswith(o + "/") for o in lock_outs)
    ):
        raise ValueError(f"'{path}' isn't in the project")
    # Only calkit.yaml's artifacts change, which the pipeline doesn't read
    commit_change(
        wdir,
        ck_info,
        lambda: [],
        msg.get("message") or f"Record where {path} came from",
        compile_pipeline=False,
    )
    return entry


def add_export_stage(wdir: str, msg: dict) -> dict:
    """Add the stage that exports a figure from the file it's drawn in, as
    the hub does, committed here.

    An app that can do it as the pipeline runs does, unless another is
    named; otherwise it's a manual step. Without ``save`` set false, it's
    added; with it, only shown. A file the stage needs that isn't in Git
    yet, e.g., a Photoshop file, is committed with it, or stored with DVC
    if it's too big for Git.
    """
    import subprocess

    import calkit.export
    import calkit.git
    import calkit.pipeline
    import calkit.provenance

    source = get_project_path(wdir, msg.get("source"), "source")
    output = get_project_path(wdir, msg.get("output"), "output")
    app = msg.get("app") or None
    exporter = calkit.export.exporter_for(source, output, app=app)
    stage = calkit.export.export_stage(source, output, app=app)
    name = calkit.export.export_stage_name(output)
    out = {
        "name": name,
        "stage": stage,
        "exported_by": exporter.app if exporter else None,
        "saved": False,
    }
    if not msg.get("save", True):
        return out
    # Uploads go through the hub; here the files are already on this
    # machine
    files = []
    for file in msg.get("files") or []:
        if not isinstance(file, dict):
            raise ValueError("Each file must be a mapping")
        if file.get("content") is not None:
            raise ValueError(
                "Put the file in the project's folder on this machine, "
                "then find it in the project"
            )
        path = get_project_path(wdir, file.get("path"), "file")
        if not (
            os.path.isfile(os.path.join(wdir, path))
            or is_dvc_tracked(wdir, path)
        ):
            raise ValueError(f"'{path}' isn't in the project")
        if file.get("created_by_me") and not (
            calkit.provenance.can_be_created_by_person(path)
        ):
            raise ValueError(
                f"'{path}' is exported from something itself, so it can't "
                "be created by a person; add the file it's made from, e.g., "
                "a Photoshop file"
            )
        files.append((path, bool(file.get("created_by_me"))))
    repo = calkit.git.get_repo(wdir)
    ck_info = calkit.load_calkit_info(wdir=wdir)
    stage_name, stage = calkit.pipeline.get_stage_to_add(
        stage,
        ck_info,
        name=name,
        is_tracked=lambda p: bool(repo.git.ls_files("--", p).strip()),
    )
    # Slides are exported with PowerPoint or LibreOffice if either is
    # installed here, else in Calkit's LibreOffice image, as on the hub
    if stage.get("kind") == "pptx-export" and not stage.get("environment"):
        env_name, env = calkit.export.get_local_slide_environment(ck_info)
        stage["environment"] = env_name
        if env is not None:
            ck_info.setdefault("environments", {})[env_name] = env
    created = [path for path, by_me in files if by_me]
    if created:
        # Whoever commits here, as Git knows them
        with repo.config_reader() as config:
            email = config.get_value("user", "email", "")
            person_name = config.get_value("user", "name", "")
        if not email:
            raise ValueError(
                "Git doesn't know your email address, to record who made "
                f"{created[0]}; set it with 'git config --global user.email'"
            )
        person = {"email": str(email)}
        if person_name:
            person["name"] = str(person_name)
        ck_info = calkit.provenance.add_creator(ck_info, created, person)
    if not ck_info.get("pipeline"):
        ck_info["pipeline"] = {}
    if not ck_info["pipeline"].get("stages"):
        ck_info["pipeline"]["stages"] = {}
    ck_info["pipeline"]["stages"][stage_name] = stage
    untracked = [
        path
        for path, _ in files
        if not repo.git.ls_files("--", path).strip()
        and not is_dvc_tracked(wdir, path)
    ]
    too_big = [
        path
        for path in untracked
        if os.path.getsize(os.path.join(wdir, path)) > FILE_GIT_MAX_BYTES
    ]
    # Elsewhere, e.g., in CI, the stage couldn't read a file Git leaves out
    for path in untracked:
        if path not in too_big and repo.ignored(path):
            raise ValueError(
                f"'{path}' is ignored by Git, so the stage couldn't run "
                "anywhere else; stop ignoring it first"
            )

    def write() -> list[str]:
        # Too big for Git, so stored with DVC, as the hub stores an upload;
        # in its own process, since DVC prints, and this one's output is
        # the extension's
        for path in too_big:
            res = subprocess.run(
                calkit.get_calkit_cmd() + ["dvc", "add", path],
                cwd=wdir,
                capture_output=True,
                text=True,
            )
            if res.returncode != 0:
                raise ValueError(
                    f"DVC couldn't store {path}: "
                    + (res.stderr or res.stdout).strip()
                )
        return [path + ".dvc" for path in too_big]

    commit_change(
        wdir,
        ck_info,
        write,
        f"Export {output} from {source}"
        + (f" with {exporter.app}" if exporter else " manually"),
        also_commit=[p for p in untracked if p not in too_big],
    )
    return out | {"name": stage_name, "stage": stage, "saved": True}


def get_pipeline(wdir: str) -> dict:
    """A checkout's pipeline as the hub summarizes one: the stages in
    calkit.yaml's order, each one's status here, and the compiled DVC
    stages, with what each runs, reads, and makes.

    Environments aren't checked, since that can build them, which a look
    at the pipeline shouldn't do.
    """
    import calkit.dvc
    import calkit.pipeline

    ck_info = calkit.load_calkit_info(wdir=wdir, read_only=True)
    ck_stages = list((ck_info.get("pipeline") or {}).get("stages") or {})
    prev_wdir = os.getcwd()
    try:
        os.chdir(wdir)
        status = calkit.pipeline.get_status(
            ck_info=ck_info,
            check_environments=False,
            clean_notebooks=True,
            compile_to_dvc=True,
            quiet_environment_checks=True,
        )
        dvc_stages = calkit.dvc.read_pipeline().get("stages", {})
        lock_stages = calkit.dvc.read_lock_stages()
        frozen_bases = calkit.pipeline.frozen_tainted_stage_names(
            ck_info=ck_info, wdir="."
        )
    finally:
        os.chdir(prev_wdir)
    stage_statuses = {}
    # One run per iteration is recorded as 'name@item', so each is counted
    # toward its stage
    locked_bases = {n.split("@")[0] for n in lock_stages}
    for name in ck_stages:
        stale = [
            s
            for key, s in status.stale_stages.items()
            if key.split("@")[0] == name
        ]
        stage_statuses[name] = get_stage_status(
            stale, has_run=name in locked_bases
        )
    # Keyed as the hub keys them, i.e., by each current entry in dvc.lock,
    # with stages never run under their own names
    live_lock_stages = calkit.pipeline.get_live_lock_stages(
        lock_stages,
        {n: s for n, s in dvc_stages.items() if isinstance(s, dict)},
    )
    lock_stage_statuses = {
        name: get_stage_status([], has_run=False)
        for name in dvc_stages
        if not name.startswith("_") and name not in locked_bases
    }
    for name in live_lock_stages:
        stale_stage = status.stale_stages.get(name)
        lock_stage_statuses[name] = get_stage_status(
            [stale_stage] if stale_stage is not None else [], has_run=True
        )
    return {
        "ck_stages": ck_stages,
        "stage_statuses": stage_statuses,
        "lock_stage_statuses": lock_stage_statuses,
        "frozen": sorted(
            n for n in live_lock_stages if n.split("@")[0] in frozen_bases
        ),
        "status": "stale" if status.is_stale else "up-to-date",
        "error": "; ".join(status.errors) or None,
        "dvc_stages": {
            name: stage
            for name, stage in dvc_stages.items()
            if isinstance(stage, dict)
        },
    }


# Each checkout's pipeline, as last read for provenance, with when and the
# modification times of the files it was read from
_recent_pipelines: dict[str, tuple[float, list[float], dict]] = {}


def get_recent_pipeline(wdir: str) -> dict:
    """``get_pipeline``'s answer, reused for ``PIPELINE_REUSE_SECONDS``
    while calkit.yaml, dvc.yaml, and dvc.lock are unchanged, since a
    figure's provenance is asked for once for each file it could be, and
    each check of the pipeline's status takes a while.
    """
    import time

    stamp = [
        os.path.getmtime(p) if os.path.isfile(p) else 0.0
        for p in (
            os.path.join(wdir, name)
            for name in ("calkit.yaml", "dvc.yaml", "dvc.lock")
        )
    ]
    recent = _recent_pipelines.get(wdir)
    if (
        recent is not None
        and time.time() - recent[0] < PIPELINE_REUSE_SECONDS
        and recent[1] == stamp
    ):
        return recent[2]
    pipeline = get_pipeline(wdir)
    _recent_pipelines[wdir] = (time.time(), stamp, pipeline)
    return pipeline


def get_provenance(wdir: str, path: Any, key: str | None = None) -> dict:
    """Where a path in a checkout, or one value in a results file, came
    from, as the hub's provenance says it, from the checkout as it is,
    including what isn't saved yet.
    """
    import posixpath

    import calkit.dvc
    import calkit.provenance

    def get_full_path(p: str) -> str | None:
        # None for one a symlink takes outside the project
        full_path = os.path.join(wdir, *p.split("/"))
        real_path = os.path.realpath(full_path)
        if real_path != root and not real_path.startswith(root + os.sep):
            return None
        return full_path

    def read_bytes(p: str) -> bytes:
        full_path = get_full_path(p)
        if full_path is None:
            raise ValueError(f"{p} isn't in the project")
        if os.path.getsize(full_path) > MAX_VALUE_FILE_BYTES:
            raise ValueError(f"{p} is too big to read")
        with open(full_path, "rb") as f:
            return f.read()

    def listdir(p: str) -> list[str]:
        full_path = get_full_path(p)
        return os.listdir(full_path) if full_path is not None else []

    def is_file(p: str) -> bool:
        full_path = get_full_path(p)
        return full_path is not None and os.path.isfile(full_path)

    def is_dir(p: str) -> bool:
        full_path = get_full_path(p)
        return full_path is not None and os.path.isdir(full_path)

    def get_dir_relpaths(md5: str) -> set[str] | None:
        # What a folder output holds, from its manifest in the DVC cache, if
        # it's there
        manifest_path = os.path.join(
            wdir, ".dvc", "cache", "files", "md5", md5[:2], md5[2:]
        )
        try:
            with open(manifest_path) as f:
                entries = json.load(f)
            return {e["relpath"] for e in entries}
        except Exception:
            return None

    def is_dvc_output(p: str) -> bool:
        # E.g., a file in a folder a stage makes that isn't pulled here
        for out in lock_outs:
            out_path = out["path"].rstrip("/")
            if not p.startswith(out_path + "/"):
                continue
            md5 = out.get("md5") or out.get("hash") or ""
            relpaths = get_dir_relpaths(md5) if md5.endswith(".dir") else None
            if relpaths is None or p[len(out_path) + 1 :] in relpaths:
                return True
        return False

    if not isinstance(path, str):
        raise ValueError("A path must be a string")
    path = posixpath.normpath(path.strip().replace("\\", "/"))
    if (
        path in (".", "..")
        or path.startswith(("/", "../"))
        or re.match(r"^[A-Za-z]:", path)
    ):
        raise ValueError(f"{path} isn't a path in the project")
    root = os.path.realpath(wdir)
    pipeline = get_recent_pipeline(wdir)
    dvc_lock = {"stages": calkit.dvc.read_lock_stages(wdir=wdir)}
    lock_outs = [
        out
        for stage in dvc_lock["stages"].values()
        for out in (stage or {}).get("outs") or []
        if isinstance(out, dict) and isinstance(out.get("path"), str)
    ]
    return calkit.provenance.get_path_provenance(
        path,
        key=key,
        ck_info=calkit.load_calkit_info(wdir=wdir, read_only=True),
        dvc_yaml={"stages": pipeline["dvc_stages"]},
        dvc_lock=dvc_lock,
        stage_statuses=pipeline["lock_stage_statuses"],
        frozen=set(pipeline["frozen"]),
        is_file=is_file,
        is_dir=is_dir,
        listdir=listdir,
        read_bytes=read_bytes,
        is_dvc_output=is_dvc_output,
    )


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
    """Answer the browser's requests until it disconnects, each in a thread
    of its own, so a quick one, e.g., checking on a job, isn't held up by a
    slow one, though those not in ``CONCURRENT_REQUEST_TYPES``, some of
    which change the working directory, take turns.
    """
    import threading

    write_lock = threading.Lock()
    turn_lock = threading.Lock()

    def warm_up() -> None:
        # What the slower requests need, imported while the first ones are
        # answered, rather than once they're asked
        import calkit.cli.overleaf  # noqa: F401
        import calkit.dvc  # noqa: F401
        import calkit.overleaf  # noqa: F401
        import calkit.pipeline  # noqa: F401

    def answer(msg: dict) -> None:
        if msg.get("type") in CONCURRENT_REQUEST_TYPES:
            reply = get_reply(msg)
        else:
            with turn_lock:
                reply = get_reply(msg)
        with write_lock:
            try:
                write_message(stdout, reply)
            except ValueError as e:
                write_message(
                    stdout, {"id": msg.get("id"), "ok": False, "error": str(e)}
                )

    threading.Thread(target=warm_up, daemon=True).start()
    answering: list[threading.Thread] = []
    while True:
        try:
            msg = read_message(stdin)
        except ValueError as e:
            with write_lock:
                write_message(
                    stdout, {"id": None, "ok": False, "error": str(e)}
                )
            continue
        if msg is None:
            break
        thread = threading.Thread(target=answer, args=(msg,), daemon=True)
        thread.start()
        answering = [t for t in answering if t.is_alive()] + [thread]
    # What was asked is finished, e.g., a job started, even with no one left
    # to tell
    for thread in answering:
        thread.join()


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


def main() -> None:
    """Run a job the host started, or else answer the browser, which names
    the extension connecting.
    """
    if sys.argv[1:2] == ["job"]:
        run_job(sys.argv[2])
        return
    # The browser's messages get stdout to themselves, since anything else
    # printed there, e.g., by a helper or a process started here, would
    # break them
    protocol_fd = os.dup(sys.stdout.fileno())
    sys.stdout.flush()
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    # Windows would otherwise turn a newline in a message into two bytes
    if sys.platform == "win32":
        import msvcrt

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(protocol_fd, os.O_BINARY)
    with os.fdopen(protocol_fd, "wb") as protocol_out:
        serve(sys.stdin.buffer, protocol_out)


if __name__ == "__main__":
    main()
