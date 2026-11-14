"""Tests for ``calkit.browser_link``."""

import io
import json
import os
import platform
import struct
import subprocess
import sys

import pytest

import calkit
import calkit.config
from calkit.browser_link import (
    get_host_status,
    get_manifest,
    get_reply,
    install_host,
    read_message,
    serve,
    uninstall_host,
    write_message,
)


def make_project(path, owner, name):
    os.makedirs(path)
    with open(os.path.join(path, "calkit.yaml"), "w") as f:
        f.write(f"owner: {owner}\nname: {name}\n")
    subprocess.check_call(["git", "init", "-q"], cwd=path)


def test_messages():
    # Each is its length, then its JSON
    out = io.BytesIO()
    write_message(out, {"type": "ping", "id": 1})
    data = out.getvalue()
    (n_bytes,) = struct.unpack("=I", data[:4])
    assert json.loads(data[4:]) == {"type": "ping", "id": 1}
    assert n_bytes == len(data) - 4
    assert read_message(io.BytesIO(data)) == {"type": "ping", "id": 1}
    # The browser closing, even partway through one, ends it
    assert read_message(io.BytesIO(b"")) is None
    assert read_message(io.BytesIO(data[:-2])) is None
    with pytest.raises(ValueError):
        read_message(io.BytesIO(struct.pack("=I", 2) + b"[]"))
    with pytest.raises(ValueError):
        write_message(io.BytesIO(), {"big": "x" * 1024 * 1024})
    # Serving answers each in turn, until the input ends, carrying on past
    # one it can't read
    requests = b"".join(
        struct.pack("=I", len(m)) + m
        for m in [
            json.dumps({"type": "ping", "id": 1}).encode(),
            b"[]",
            json.dumps({"type": "nope", "id": 2}).encode(),
        ]
    )
    out = io.BytesIO()
    serve(io.BytesIO(requests), out)
    out.seek(0)
    replies = []
    while (msg := read_message(out)) is not None:
        replies.append(msg)
    assert replies == [
        {
            "id": 1,
            "ok": True,
            "result": {
                "version": calkit.__version__,
                "editor": calkit.config.read().default_editor,
            },
        },
        {"id": None, "ok": False, "error": "A message must be a JSON object"},
        {"id": 2, "ok": False, "error": "Unknown request type 'nope'"},
    ]


def test_get_reply(tmp_path, monkeypatch):
    home = tmp_path / "home"
    os.makedirs(home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("CALKIT_USER_HOME", str(home))
    # Found under the home folder, or wherever it was recorded
    near = home / "calkit" / "near"
    make_project(near, "me", "near")
    far = tmp_path / "x" / "y" / "z" / "far"
    make_project(far, "me", "far")
    calkit.record_project_path(str(far))
    for project, paths in [
        ("me/near", [os.path.realpath(near)]),
        ("me/far", [os.path.realpath(far)]),
        ("them/near", []),
    ]:
        reply = get_reply({"type": "projects.find", "project": project})
        assert reply == {"id": None, "ok": True, "result": {"paths": paths}}
    for project in ["near", "a/b/c", "/near", 5, None]:
        reply = get_reply({"type": "projects.find", "project": project})
        assert not reply["ok"] and "owner/name" in reply["error"]
    # Opening one runs 'calkit open project', which says what went wrong,
    # and never clones
    reply = get_reply({"type": "project.open", "project": "me/gone", "id": 3})
    assert reply["id"] == 3 and not reply["ok"]
    assert reply["error"] == (
        "me/gone isn't on this computer; clone it with 'calkit clone me/gone'"
    )
    reply = get_reply({"type": "project.open", "project": "me/far", "path": 1})
    assert reply["error"] == "A path must be a string"
    started = []

    class Popen:
        def __init__(self, cmd, stdout, env, **kwargs):
            started.append((cmd, env))
            stdout.write(output)

        def wait(self, timeout):
            if returncode is None:
                raise subprocess.TimeoutExpired("x", timeout)
            return returncode

    monkeypatch.setattr("subprocess.Popen", Popen)
    # The editor's command is looked for on the login shell's PATH, since a
    # browser started from the Dock, e.g., has only the system's
    monkeypatch.setattr(
        "calkit.hub.link.login_shell_path", lambda: "/login/bin"
    )
    # It's opened, or is still opening, e.g., JupyterLab's server, or says
    # why it couldn't be
    for returncode, output, ok in [
        (0, "Opening", True),
        (None, "", True),
        (1, "Opening\nError: a.ipynb isn't in /far\n", False),
    ]:
        started.clear()
        reply = get_reply(
            {"type": "project.open", "project": "me/far", "path": "a.ipynb"}
        )
        assert reply["ok"] == ok
        if not ok:
            assert reply["error"] == "a.ipynb isn't in /far"
        [(cmd, env)] = started
        assert cmd == [
            sys.executable,
            *["-m", "calkit", "open", "project", "me/far"],
            *["--path", "a.ipynb"],
        ]
        if os.name != "nt":
            assert env["PATH"].startswith("/login/bin" + os.pathsep)


def test_install_host(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("Windows registers hosts in the registry")
    home = tmp_path / "home"
    monkeypatch.setenv("CALKIT_USER_HOME", str(home))
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    # Only browsers that have been run here get a manifest
    os.makedirs(home / ".config" / "google-chrome")
    os.makedirs(home / ".mozilla")
    browsers = install_host(extension_ids=["abc", "dev@calkit.io"])
    assert sorted(browsers) == ["chrome", "firefox"]
    chrome_path = (
        home
        / ".config"
        / "google-chrome"
        / "NativeMessagingHosts"
        / "io.calkit.native.json"
    )
    firefox_path = (
        home / ".mozilla" / "native-messaging-hosts" / "io.calkit.native.json"
    )
    chrome = json.loads(chrome_path.read_text())
    assert chrome["allowed_origins"] == [
        "chrome-extension://idhdomgapfolnpffanajdckdaojencal/",
        "chrome-extension://abc/",
    ]
    firefox = json.loads(firefox_path.read_text())
    assert firefox["allowed_extensions"] == [
        "browser-ext@calkit.io",
        "dev@calkit.io",
    ]
    assert get_manifest("chrome")["path"] == chrome["path"]
    # The launcher starts the host with this Python, which answers
    assert os.access(chrome["path"], os.X_OK)
    msg = json.dumps({"type": "ping", "id": 7}).encode()
    res = subprocess.run(
        [chrome["path"], "chrome-extension://abc/"],
        input=struct.pack("=I", len(msg)) + msg,
        capture_output=True,
        timeout=60,
    )
    assert read_message(io.BytesIO(res.stdout)) == {
        "id": 7,
        "ok": True,
        "result": {
            "version": calkit.__version__,
            "editor": calkit.config.read().default_editor,
        },
    }
    # Its status says where it's registered, for which extensions, and that
    # it answers
    status = get_host_status()
    assert status == {
        "launcher_path": chrome["path"],
        "python_path": sys.executable,
        "browsers": {
            "chrome": ["idhdomgapfolnpffanajdckdaojencal", "abc"],
            "firefox": ["browser-ext@calkit.io", "dev@calkit.io"],
        },
        "version": calkit.__version__,
        "error": None,
    }
    # A launcher whose Python is gone, e.g., after reinstalling Calkit with
    # another, doesn't answer
    with open(chrome["path"], "w") as f:
        f.write('#!/bin/sh\nexec "/gone/python" -m calkit.browser_link\n')
    status = get_host_status()
    assert status["python_path"] == "/gone/python"
    assert status["version"] is None and status["error"]
    uninstall_host()
    assert not chrome_path.exists() and not firefox_path.exists()
    assert not os.path.exists(chrome["path"])
    status = get_host_status()
    assert status["error"] == "Not installed"
    assert status["browsers"] == {"chrome": None, "firefox": None}


def test_get_checkout_status(tmp_path):
    from filelock import FileLock

    from calkit.browser_link import get_checkout_status

    def git(*args, cwd):
        subprocess.check_call(
            ["git", "-c", "user.name=T", "-c", "user.email=t@example.com"]
            + list(args),
            cwd=cwd,
        )

    tex = "\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n"
    project = tmp_path / "project"
    os.makedirs(project / "paper")
    (project / "paper" / "main.tex").write_text(tex)
    (project / "calkit.yaml").write_text(
        "overleaf_sync:\n  paper:\n"
        "    url: https://www.overleaf.com/project/abc123\n"
    )
    (project / ".gitignore").write_text(".calkit/overleaf\n")
    git("init", "-q", "-b", "main", cwd=project)
    git("add", "-A", cwd=project)
    git("commit", "-qm", "Init", cwd=project)
    remote = tmp_path / "remote.git"
    git("init", "-q", "--bare", str(remote), cwd=tmp_path)
    git("remote", "add", "origin", str(remote), cwd=project)
    git("push", "-q", "-u", "origin", "main", cwd=project)
    # Overleaf, as the last sync left it, with the same document
    clone = project / ".calkit" / "overleaf" / "abc123"
    os.makedirs(clone)
    (clone / "main.tex").write_text(tex)
    git("init", "-q", cwd=clone)
    git("add", "-A", cwd=clone)
    git("commit", "-qm", "Init", cwd=clone)
    status = get_checkout_status(str(project))
    assert status == {
        "path": str(project),
        "branch": "main",
        "unsaved_files": [],
        "n_unsaved_files": 0,
        "commits_ahead": 0,
        "overleaf": [
            {
                "path": "paper",
                "files_to_push": [],
                "n_files_to_push": 0,
                "n_files_to_delete": 0,
            }
        ],
    }
    # A commit not pushed, a change not committed, which a sync would send
    # to Overleaf, and a new file, which it wouldn't until it's saved
    (project / "notes.md").write_text("Notes\n")
    git("add", "notes.md", cwd=project)
    git("commit", "-qm", "Notes", cwd=project)
    (project / "paper" / "main.tex").write_text(tex + "% More\n")
    (project / "paper" / "intro.tex").write_text("Intro\n")
    status = get_checkout_status(str(project))
    assert status["commits_ahead"] == 1
    assert status["unsaved_files"] == ["paper/intro.tex", "paper/main.tex"]
    assert status["n_unsaved_files"] == 2
    [folder] = status["overleaf"]
    assert folder["files_to_push"] == ["paper/main.tex"]
    assert folder["n_files_to_push"] == 1
    # While a sync holds the clone, it says so rather than waiting
    with FileLock(str(clone) + ".lock"):
        status = get_checkout_status(str(project))
    assert status["overleaf"] == [{"path": "paper", "syncing": True}]
    # The working directory is left as it was
    assert os.getcwd() != str(project)
