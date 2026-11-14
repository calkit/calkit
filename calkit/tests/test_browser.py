"""Tests for ``calkit.browser``."""

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
from calkit.browser import (
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
    uninstall_host()
    assert not chrome_path.exists() and not firefox_path.exists()
    assert not os.path.exists(chrome["path"])
