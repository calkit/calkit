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
# How long opening a project waits to hear it failed
OPEN_TIMEOUT_SECONDS = 30
# Chrome won't take a bigger message from a host
MAX_MESSAGE_BYTES = 1024 * 1024
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
            from calkit.config import read as read_config

            result: Any = {
                "version": calkit.__version__,
                "editor": read_config().default_editor,
            }
        elif kind == "projects.find":
            owner, name = split_project(msg.get("project"))
            found = calkit.get_project_checkouts(name, owner=owner)
            result = {"paths": sorted(found)}
        elif kind == "project.open":
            owner, name = split_project(msg.get("project"))
            cmd = [sys.executable, "-m", "calkit", "open", "project"]
            cmd.append(f"{owner}/{name}")
            path = msg.get("path")
            if path is not None:
                if not isinstance(path, str):
                    raise ValueError("A path must be a string")
                cmd += ["--path", path]
            # A browser started from the Dock, e.g., has only the system's
            # folders on its PATH, so not the editor's command
            env = None
            if os.name != "nt":
                from calkit.hub.link import login_shell_path

                login_path = login_shell_path()
                if login_path:
                    env = os.environ | {
                        "PATH": os.pathsep.join(
                            [login_path, os.environ.get("PATH", "")]
                        )
                    }
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
                    env=env,
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
        else:
            raise ValueError(f"Unknown request type {kind!r}")
    except Exception as e:
        return {"id": req_id, "ok": False, "error": str(e)}
    return {"id": req_id, "ok": True, "result": result}


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
        # Not synced from this checkout yet
        if not os.path.isdir(os.path.join(clone_path, ".git")):
            continue
        folder: dict[str, Any] = {"path": path_in_project}
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
    serve(sys.stdin.buffer, sys.stdout.buffer)
