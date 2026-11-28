"""Tests for ``calkit.browser_link``."""

import io
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
from unittest.mock import Mock

import pytest

import calkit
import calkit.config
import calkit.git
import calkit.pipeline
import calkit.pipeline.detect
from calkit.browser_link import (
    get_editor_info,
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
    # Serving answers each, in whatever order they're done, until the input
    # ends, carrying on past one it can't read
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
    assert sorted(replies, key=lambda r: str(r["id"])) == [
        {
            "id": 1,
            "ok": True,
            "result": {"version": calkit.__version__} | get_editor_info(),
        },
        {"id": 2, "ok": False, "error": "Unknown request type 'nope'"},
        {"id": None, "ok": False, "error": "A message must be a JSON object"},
    ]
    # Nothing else printed, by Calkit or a process it starts, reaches the
    # browser's messages
    noisy = (
        "import os, calkit.browser_link as b; get_reply = b.get_reply; "
        "b.get_reply = lambda m: (print('noise'), os.system('echo more'), "
        "get_reply(m))[2]; b.main()"
    )
    ping = json.dumps({"type": "ping", "id": 1}).encode()
    res = subprocess.run(
        [sys.executable, "-c", noisy],
        input=struct.pack("=I", len(ping)) + ping,
        capture_output=True,
        timeout=60,
    )
    out = io.BytesIO(res.stdout)
    assert read_message(out)["ok"] and read_message(out) is None
    assert b"noise" in res.stderr and b"more" in res.stderr


def test_get_reply(tmp_path, monkeypatch):
    from calkit.browser_link import get_calkit_cmd
    from calkit.cli import raise_error

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
    for project in [
        "near",
        "a/b/c",
        "/near",
        5,
        None,
        "-o/near",
        "git@evil.example:a/b",
        "../near",
    ]:
        reply = get_reply({"type": "projects.find", "project": project})
        assert not reply["ok"] and "owner/name" in reply["error"]
    # Opening one runs 'calkit open project', which says what went wrong,
    # and never clones
    reply = get_reply({"type": "project.open", "project": "me/gone", "id": 3})
    assert reply["id"] == 3 and not reply["ok"]
    assert reply["error"] == (
        "me/gone isn't on this machine; clone it with 'calkit clone me/gone'"
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
    calkit.browser_link.get_login_shell_env.cache_clear()
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
            *get_calkit_cmd(),
            *["open", "project", "me/far"],
            *["--with", get_editor_info()["editor"]],
            # The checkout everything else here uses
            *["--checkout", os.path.realpath(far), "--path", "a.ipynb"],
        ]
        if os.name != "nt":
            assert env["PATH"].startswith("/login/bin" + os.pathsep)
    # An error a helper raises after printing why says why
    monkeypatch.setattr(
        calkit.browser_link, "get_figures", lambda wdir: raise_error("Nope")
    )
    reply = get_reply({"type": "project.figures", "project": "me/far"})
    assert reply == {"id": None, "ok": False, "error": "Nope"}
    # The editor is the one set, or else the first installed of those built
    # on VS Code, VS Code first, or else VS Code, to be installed
    installed: list[str] = []
    real_which = shutil.which

    def which(cmd, path=None, **kwargs):
        if cmd in ("code", "cursor", "positron", "codium"):
            return f"/login/bin/{cmd}" if cmd in installed else None
        return real_which(cmd, path=path, **kwargs)

    monkeypatch.setattr("shutil.which", which)
    monkeypatch.setattr("calkit.install.find", lambda app: None)
    for set_editor, now_installed, expected in [
        (None, [], {"editor": "vscode", "editor_installed": False}),
        (
            None,
            ["cursor", "positron"],
            {"editor": "cursor", "editor_installed": True},
        ),
        (
            None,
            ["code", "cursor"],
            {"editor": "vscode", "editor_installed": True},
        ),
        (
            "positron",
            ["code"],
            {"editor": "positron", "editor_installed": False},
        ),
    ]:
        installed[:] = now_installed
        if set_editor:
            settings = calkit.config.Settings(default_editor=set_editor)
            monkeypatch.setattr(calkit.config, "read", lambda **_: settings)
        assert get_editor_info() == expected


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
    reply = read_message(io.BytesIO(res.stdout))
    assert reply["ok"] and reply["result"]["version"] == calkit.__version__
    assert set(reply["result"]) == {"version", "editor", "editor_installed"}
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
    # Before a sync from here, e.g., when the hub syncs it, there's nothing
    # to compare with
    status = get_checkout_status(str(project))
    assert status["overleaf"] == [{"path": "paper", "never_synced": True}]
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


def git(*args, cwd):
    subprocess.check_call(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com"]
        + list(args),
        cwd=cwd,
    )


def make_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    os.makedirs(home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("CALKIT_USER_HOME", str(home))
    return home


def test_get_checkout_paths(tmp_path, monkeypatch):
    from calkit.browser_link import get_checkout_paths

    home = make_home(tmp_path, monkeypatch)
    main = home / "calkit" / "proj"
    make_project(main, "me", "proj")
    git("add", "-A", cwd=main)
    git("commit", "-q", "-m", "Init", cwd=main)
    worktree = home / "dev" / "proj-wt"
    os.makedirs(worktree.parent)
    git("worktree", "add", "-q", str(worktree), cwd=main)
    main_path = os.path.realpath(main)
    wt_path = os.path.realpath(worktree)
    # The one in ~/calkit first, as 'calkit open project' picks
    assert get_checkout_paths("me", "proj") == [main_path, wt_path]
    reply = get_reply({"type": "checkouts.get", "project": "me/proj"})
    assert reply["result"] == {
        "paths": [main_path, wt_path],
        "path": main_path,
    }
    # Unless another was chosen, which is remembered
    reply = get_reply(
        {"type": "checkouts.choose", "project": "me/proj", "path": wt_path}
    )
    assert reply["ok"] and reply["result"]["path"] == wt_path
    assert get_checkout_paths("me", "proj") == [wt_path, main_path]
    reply = get_reply(
        {"type": "checkouts.choose", "project": "me/proj", "path": "/x"}
    )
    assert not reply["ok"] and "isn't a checkout" in reply["error"]
    # One made since they were looked for is found when it's chosen
    newer = home / "dev" / "proj-newer"
    git("worktree", "add", "-q", str(newer), cwd=main)
    newer_path = os.path.realpath(newer)
    assert get_checkout_paths("me", "proj") == [wt_path, main_path]
    reply = get_reply(
        {"type": "checkouts.choose", "project": "me/proj", "path": newer_path}
    )
    assert reply["result"] == {
        "paths": [newer_path, main_path, wt_path],
        "path": newer_path,
    }
    reply = get_reply({"type": "checkouts.get", "project": "me/gone"})
    assert reply["result"] == {"paths": [], "path": None}


def test_get_overleaf_links(tmp_path, monkeypatch):
    import time

    import calkit.browser_link
    from calkit.browser_link import get_overleaf_links

    home = make_home(tmp_path, monkeypatch)
    project = home / "calkit" / "paper-proj"
    make_project(project, "me", "paper-proj")
    git(
        "remote",
        "add",
        "origin",
        "git@github.com:me/paper-proj.git",
        cwd=project,
    )
    with open(project / "calkit.yaml", "a") as f:
        f.write(
            "title: A paper\noverleaf_sync:\n  paper:\n"
            "    url: https://www.overleaf.com/project/abc123\n"
        )
    scans = []
    real_find = calkit.find_project_dirs

    def find_project_dirs(*args, **kwargs):
        scans.append(1)
        return real_find(*args, **kwargs)

    monkeypatch.setattr(calkit, "find_project_dirs", find_project_dirs)
    link = {
        "overleaf_project_id": "abc123",
        "path": "paper",
        "project_owner_name": "me",
        "project_name": "paper-proj",
        "project_title": "A paper",
        "current_user_access": "write",
        "github_repo_url": "https://github.com/me/paper-proj",
        "local_path": os.path.realpath(project),
    }
    # Searched for the first time, then found in the index
    assert get_overleaf_links("abc123") == [link]
    assert get_overleaf_links("abc123") == [link]
    assert len(scans) == 1
    reply = get_reply(
        {"type": "overleaf.lookup", "overleaf_project_id": "abc123"}
    )
    assert reply["result"] == {
        "links": [link],
        "projects_scanned": 1,
        "projects_remaining": 0,
    }
    # One no project here syncs with isn't searched for again for a while
    assert get_overleaf_links("other") == []
    assert len(scans) == 1
    # A project's calkit.yaml changing is noticed without searching
    text = (project / "calkit.yaml").read_text()
    (project / "calkit.yaml").write_text(text.replace("abc123", "def456"))
    os.utime(project / "calkit.yaml", (time.time() + 5, time.time() + 5))
    assert get_overleaf_links("abc123") == []
    assert get_overleaf_links("def456")[0]["overleaf_project_id"] == "def456"
    assert len(scans) == 1
    # A new one is found once the last search is old enough
    other = home / "calkit" / "other"
    make_project(other, "me", "other")
    with open(other / "calkit.yaml", "a") as f:
        f.write(
            "overleaf_sync:\n  doc:\n"
            "    url: https://www.overleaf.com/project/new789\n"
        )
    assert get_overleaf_links("new789") == []
    monkeypatch.setattr(calkit.browser_link, "LOOKUP_RESCAN_SECONDS", -1)
    [found] = get_overleaf_links("new789")
    assert (
        found["project_title"] == "other" and found["github_repo_url"] is None
    )


def test_get_overleaf_sync_statuses(tmp_path, monkeypatch):
    import git as gitpython

    import calkit.browser_link
    import calkit.cli.overleaf
    from calkit.browser_link import get_overleaf_sync_statuses
    from calkit.cli.core import raise_error

    make_home(tmp_path, monkeypatch)
    tex = "\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n"
    project = tmp_path / "project"
    os.makedirs(project / "paper")
    (project / "paper" / "main.tex").write_text(tex)
    (project / "calkit.yaml").write_text(
        "owner: me\nname: project\n"
        "overleaf_sync:\n  paper:\n"
        "    url: https://www.overleaf.com/project/abc123\n"
    )
    (project / ".gitignore").write_text(".calkit/overleaf\n")
    git("init", "-q", "-b", "main", cwd=project)
    git("add", "-A", cwd=project)
    git("commit", "-qm", "Init", cwd=project)
    clone = project / ".calkit" / "overleaf" / "abc123"
    os.makedirs(clone)
    (clone / "main.tex").write_text(tex)
    git("init", "-q", cwd=clone)
    git("add", "-A", cwd=clone)
    git("commit", "-qm", "Init", cwd=clone)
    pulled = []

    def get_pulled_repo(project_id, auth):
        # What's printed would go to the browser, so it's kept from it
        print("Pulling the latest version from Overleaf")
        pulled.append((project_id, auth))
        return gitpython.Repo(clone), auth

    n_auth_reads = []

    def get_auth():
        n_auth_reads.append(1)
        return "token"

    monkeypatch.setattr(calkit.browser_link, "_overleaf_auth", None)
    monkeypatch.setattr(calkit.browser_link, "_overleaf_pulled_at", {})
    monkeypatch.setattr(calkit.cli.overleaf, "_get_overleaf_auth", get_auth)
    monkeypatch.setattr(
        calkit.cli.overleaf, "_get_pulled_overleaf_repo", get_pulled_repo
    )
    # A change here, which a sync would send, as the hub's status says it
    (project / "paper" / "main.tex").write_text(tex + "% More\n")
    git("commit", "-qam", "Edit", cwd=project)
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    [status] = get_overleaf_sync_statuses(str(project))
    assert out.getvalue() == ""
    assert pulled == [("abc123", "token")]
    assert status["path"] == "paper"
    assert status["overleaf_project_id"] == "abc123"
    assert status["overleaf_url"] == "https://www.overleaf.com/project/abc123"
    assert [f["project_path"] for f in status["files_to_push"]] == [
        "paper/main.tex"
    ]
    assert status["files_to_push"][0]["stage_status"] is None
    assert not status["in_sync"]
    assert status["pulled"]
    # Pulled only a moment ago, so not again
    assert get_overleaf_sync_statuses(str(project), path="paper") == [status]
    assert get_overleaf_sync_statuses(str(project), "other-id") == []
    assert len(pulled) == 1
    # Later it is, with the credentials that worked, rather than reading them
    # again
    monkeypatch.setattr(calkit.browser_link, "PULL_FRESH_SECONDS", 0)
    assert get_overleaf_sync_statuses(str(project)) == [status]
    assert len(pulled) == 2 and len(n_auth_reads) == 1
    # Without pulling, the copy from the last pull is used, with no
    # credentials needed, unless there isn't one yet
    pulled.clear()
    monkeypatch.setattr(calkit.cli.overleaf, "_get_overleaf_auth", None)
    [quick] = get_overleaf_sync_statuses(str(project), pull=False)
    assert not pulled and not quick["pulled"]
    assert quick | {"pulled": True} == status
    # What Overleaf's editor has, if the copy here has it already, counts as
    # a pull without asking Overleaf
    git("update-ref", "refs/calkit/overleaf", "HEAD", cwd=clone)
    sha = gitpython.Repo(clone).head.commit.tree["main.tex"].hexsha
    assert get_overleaf_sync_statuses(
        str(project), overleaf_files={"main.tex": sha}
    ) == [status]
    assert not pulled
    monkeypatch.setattr(
        calkit.cli.overleaf, "_get_overleaf_auth", lambda: "token"
    )
    with pytest.raises(ValueError, match="isn't synced"):
        get_overleaf_sync_statuses(str(project), path="nope")
    # Without credentials, it says so as the hub does, so the extension
    # asks for them
    monkeypatch.setattr(calkit.browser_link, "_overleaf_auth", None)
    monkeypatch.setattr(
        calkit.cli.overleaf,
        "_get_overleaf_auth",
        lambda: raise_error(
            "Set one with 'calkit config set overleaf_token' and try again"
        ),
    )
    calkit.record_project_path(str(project))
    reply = get_reply({"type": "overleaf.status", "project": "me/project"})
    assert reply["status"] == 401 and "Overleaf credentials" in reply["error"]
    assert os.getcwd() != str(project)


def test_start_job(tmp_path, monkeypatch):
    import calkit.browser_link
    from calkit.browser_link import (
        get_calkit_cmd,
        get_job,
        list_jobs,
        run_job,
        start_job,
    )

    home = make_home(tmp_path, monkeypatch)
    project = home / "calkit" / "proj"
    make_project(project, "me", "proj")
    git("commit", "-q", "--allow-empty", "-m", "Init", cwd=project)
    started = []
    real_popen = subprocess.Popen
    calkit_cmd = get_calkit_cmd()
    link_cmd = get_calkit_cmd("calkit.browser_link")

    def popen(cmd, **kwargs):
        if cmd[: len(link_cmd)] == link_cmd:
            started.append(cmd)
            return None
        return real_popen(cmd, **kwargs)

    monkeypatch.setattr("subprocess.Popen", popen)
    # A run saves and syncs, in a process of its own that runs the job
    job = start_job({"kind": "run", "project": "me/proj"})
    assert job["status"] == "queued" and job["wdir"] == os.path.realpath(
        project
    )
    assert job["cmd"] == calkit_cmd + ["run", "--save", "--overleaf"]
    assert job["branch"] and len(job["git_rev"]) == 40
    assert started == [link_cmd + ["job", job["id"]]]
    assert get_reply({"type": "job.get", "job_id": job["id"]})["result"] == job
    # One at a time
    reply = get_reply(
        {"type": "job.start", "kind": "run", "project": "me/proj"}
    )
    assert not reply["ok"] and "already running" in reply["error"]
    # Nor a sync while it runs, since both commit
    reply = get_reply(
        {
            "type": "job.start",
            "kind": "sync",
            "project": "me/proj",
            "path": "paper",
        }
    )
    assert not reply["ok"] and "already running" in reply["error"]
    # Without syncing after, it only runs
    job_path = calkit.browser_link.get_job_path(job["id"])
    with open(job_path) as f:
        record = json.load(f)
    with open(job_path, "w") as f:
        json.dump(record | {"status": "succeeded"}, f)
    # Saving everything, which waits its turn like a run or sync
    saving = start_job({"kind": "save", "project": "me/proj"})
    assert saving["cmd"] == calkit_cmd + [
        "save",
        "-a",
        "-m",
        "Save from Overleaf",
    ]
    with pytest.raises(ValueError, match="already saving"):
        start_job({"kind": "save", "project": "me/proj"})
    os.remove(calkit.browser_link.get_job_path(saving["id"]))
    run_only = start_job({"kind": "run", "project": "me/proj", "sync": False})
    assert run_only["cmd"] == calkit_cmd + ["run"]
    os.remove(calkit.browser_link.get_job_path(run_only["id"]))
    # A project made from a folder here, signing in first, then importing
    # the paper and saving everything
    analysis = home / "calkit" / "analysis"
    analysis.mkdir()
    (analysis / "fit.py").write_text("")
    create = {
        "kind": "create",
        "project": "me/dye",
        "location": str(analysis),
        "hub": "http://localhost:5173",
        "title": "Dye fading",
        "overleafProjectUrl": "https://www.overleaf.com/project/abc123",
        "path": "paper",
        "docKind": "journal-article",
        "isPublic": True,
    }
    creating = start_job(create)
    hub = ["--hub", "http://localhost:5173"]
    assert creating["wdir"] == str(analysis)
    assert creating["location"] == str(analysis)
    assert creating["cmd"] == calkit_cmd + ["hub", "login", *hub]
    assert creating["then"] == [
        calkit_cmd
        + ["new", "project", ".", *hub, "--name", "dye"]
        + ["--title", "Dye fading", "--public"],
        calkit_cmd
        + ["overleaf", "import", "https://www.overleaf.com/project/abc123"]
        + ["paper", "--kind", "journal-article"],
        calkit_cmd + ["save", "-a", "-m", "Add files from this machine"],
    ]
    # With what each is doing, for the extension to show
    assert creating["steps"] == [
        "Signing in",
        "Creating project",
        "Importing paper",
        "Saving",
    ]
    os.remove(calkit.browser_link.get_job_path(creating["id"]))
    # Trying again where an earlier try made the project picks up where it
    # stopped, e.g., before the paper could be imported
    subprocess.check_call(["git", "init", "-q", str(analysis)])
    (analysis / "calkit.yaml").write_text("owner: me\nname: dye\n")
    resumed = start_job(create)
    assert resumed["then"] == creating["then"][1:]
    assert resumed["steps"] == ["Signing in", "Importing paper", "Saving"]
    os.remove(calkit.browser_link.get_job_path(resumed["id"]))
    (analysis / "calkit.yaml").write_text(
        "owner: me\nname: dye\noverleaf_sync:\n  paper: {}\n"
    )
    resumed = start_job(create)
    assert resumed["then"] == creating["then"][2:]
    os.remove(calkit.browser_link.get_job_path(resumed["id"]))
    # But not in a repo of another project
    (analysis / "calkit.yaml").write_text("owner: me\nname: other\n")
    with pytest.raises(ValueError, match="already a Git repo"):
        start_job(create)
    (analysis / "calkit.yaml").write_text("owner: me\nname: dye\n")
    for bad, error in [
        ({"location": str(project)}, "already a Git repo"),
        ({"location": str(analysis / "fit.py")}, "isn't a folder"),
        ({"location": "~/.config"}, "Can't clone"),
        ({"overleafProjectUrl": "https://x.org/project/1"}, "Overleaf"),
        ({"path": "../up"}, "folder for the document"),
        ({"hub": "file:///x"}, "hub URL"),
    ]:
        with pytest.raises(ValueError, match=error):
            start_job(create | bad)
    # VS Code, the editor Calkit installs, from the user's home folder
    installing = start_job({"kind": "install-editor", "project": "me/proj"})
    assert installing["cmd"] == calkit_cmd + ["install", "code", "--yes"]
    assert installing["wdir"] == calkit.get_user_home()
    os.remove(calkit.browser_link.get_job_path(installing["id"]))

    # A worker that can't be started leaves its job failed, not queued,
    # which would hold up the next run
    def popen_fails(cmd, **kwargs):
        if cmd[: len(link_cmd)] == link_cmd:
            raise OSError("No such file")
        return real_popen(cmd, **kwargs)

    monkeypatch.setattr("subprocess.Popen", popen_fails)
    with pytest.raises(OSError):
        start_job({"kind": "run", "project": "me/proj"})
    [failed] = [j for j in list_jobs() if j["status"] == "failed"]
    assert "Couldn't start it" in failed["error"] and failed["finished"]
    os.remove(calkit.browser_link.get_job_path(failed["id"]))
    monkeypatch.setattr("subprocess.Popen", popen)
    with open(job_path, "w") as f:
        json.dump(record, f)
    for msg, error in [
        ({"kind": "rm", "project": "me/proj"}, "Unknown kind"),
        ({"kind": "sync", "project": "me/proj"}, "folder"),
        ({"kind": "run", "project": "me/gone"}, "isn't on this machine"),
        (
            {"kind": "clone", "project": "me/proj", "location": str(project)},
            "isn't empty",
        ),
        # Only to a folder of the user's own, not one config is read from
        (
            {"kind": "clone", "project": "me/x", "location": "~/.config/git"},
            "Can't clone",
        ),
        (
            {"kind": "clone", "project": "me/x", "location": str(tmp_path)},
            "Can't clone",
        ),
        ({"kind": "clone", "project": "-u/x"}, "owner/name"),
    ]:
        with pytest.raises(ValueError, match=error):
            start_job(msg)
    with pytest.raises(ValueError):
        get_job("../../etc/passwd")
    # Running it records how it went, with the error it ended with
    job_path = calkit.browser_link.get_job_path(job["id"])

    def run(code, then=()):
        with open(job_path) as f:
            record = json.load(f)
        record["cmd"] = [sys.executable, "-c", code]
        record["then"] = [[sys.executable, "-c", c] for c in then]
        with open(job_path, "w") as f:
            json.dump(record, f)
        run_job(job["id"])
        return get_job(job["id"])

    # Each command after the first, until one fails
    chained = run(
        "print('One')",
        then=["print('Two')", "import sys; sys.exit(3)", "print('Four')"],
    )
    assert chained["status"] == "failed" and chained["returncode"] == 3
    assert chained["output"] == "One\nTwo"
    # Which it stopped at
    assert chained["step"] == 2
    done = run("print('Ran it')")
    assert done["status"] == "succeeded" and done["output"] == "Ran it"
    assert "progress" not in done and not done["log_path"]
    reply = get_reply({"type": "job.log", "job_id": job["id"]})
    assert reply["result"] == {"log": "Ran it"}
    assert done["started"] and done["finished"] and done["returncode"] == 0
    assert os.listdir(calkit.browser_link.get_jobs_dir()) == [
        f"{job['id']}.json"
    ]
    # A run's log is the one Calkit keeps in the project, not an older one,
    # then what came after, e.g., saving
    logs_dir = project / ".calkit" / "local" / "logs"
    os.makedirs(logs_dir)
    (logs_dir / "2000-01-01T00-00-00-old.log").write_text("Old\n")
    script = tmp_path / "run.py"
    script.write_text(
        "import datetime, os\n"
        "now = datetime.datetime.now(datetime.timezone.utc)\n"
        "name = now.strftime('%Y-%m-%dT%H-%M-%S') + '-new.log'\n"
        "with open(os.path.join('.calkit', 'local', 'logs', name), 'w') as f:\n"
        "    f.write(\"Running stage 'a':\\n--- calkit stage output ---\\n\")\n"
        "    f.write('\\x1b[1mHi\\x1b[0m\\n--- end calkit stage output ---\\n')\n"
        "print(\"Running stage 'a':\")\n"
        "print('Hi')\n"
        "print('Pipeline completed successfully')\n"
        "print('Saving the project after successful run')\n"
    )
    done = run(f"exec(open({str(script)!r}).read())")
    assert done["log_path"].endswith("-new.log")
    reply = get_reply({"type": "job.log", "job_id": job["id"]})
    assert reply["result"]["log"].splitlines() == [
        "Running stage 'a':",
        "Hi",
        "Pipeline completed successfully",
        "Saving the project after successful run",
    ]
    failed = run("print('Error: It broke'); print('Bye'); raise SystemExit(1)")
    assert failed["status"] == "failed" and failed["error"] == "It broke"
    # Missing Overleaf credentials are reported as the hub reports them
    failed = run(
        "print(\"Error: Set one with 'calkit config set overleaf_token'\");"
        "raise SystemExit(1)"
    )
    assert failed["error_status"] == 401
    # One with several steps says which failed
    with open(job_path) as f:
        record = json.load(f)
    with open(job_path, "w") as f:
        json.dump(record | {"steps": ["Signing in", "Saving"]}, f)
    failed = run(
        "print('In')", then=["print('Error: No'); raise SystemExit(1)"]
    )
    assert failed["error"] == "Saving failed: No"
    with open(job_path) as f:
        record = json.load(f)
    with open(job_path, "w") as f:
        json.dump(record | {"steps": None}, f)
    # One whose process died without saying so has failed
    with open(job_path) as f:
        record = json.load(f)
    record |= {"status": "running", "pid": 2**22 + 12345}
    with open(job_path, "w") as f:
        json.dump(record, f)
    assert get_job(job["id"])["status"] == "failed"
    # As has one that never started
    record |= {"status": "queued", "pid": None, "created": "2000-01-01T00:00Z"}
    with open(job_path, "w") as f:
        json.dump(record, f)
    assert get_job(job["id"])["error"] == "It never started"
    # Listed by project, newest first
    clone = start_job(
        {"kind": "clone", "project": "me/other", "location": "~/calkit/o"}
    )
    assert clone["location"] == os.path.join(str(home), "calkit", "o")
    assert [j["id"] for j in list_jobs()] == [clone["id"], job["id"]]
    reply = get_reply(
        {"type": "jobs.list", "project": "me/proj", "kind": "run"}
    )
    assert [j["id"] for j in reply["result"]] == [job["id"]]
    # A clone sets up its TeX Live environments after, not the first run
    clone_dir = home / "calkit" / "o"
    clone_dir.mkdir()
    (clone_dir / "calkit.yaml").write_text(
        "environments:\n"
        "  tex:\n    kind: texlive\n"
        "  py:\n    kind: uv\n    path: pyproject.toml\n"
    )
    clone_path = calkit.browser_link.get_job_path(clone["id"])
    with open(clone_path) as f:
        record = json.load(f)
    with open(clone_path, "w") as f:
        json.dump(record | {"cmd": [sys.executable, "-c", "pass"]}, f)
    checked = []
    real_run = subprocess.run

    def run_checks(cmd, **kwargs):
        if cmd[: len(calkit_cmd) + 1] == calkit_cmd + ["check"]:
            checked.append((cmd[len(calkit_cmd) + 1 :], kwargs["cwd"]))
            return None
        return real_run(cmd, **kwargs)

    monkeypatch.setattr("subprocess.run", run_checks)
    run_job(clone["id"])
    assert get_job(clone["id"])["status"] == "succeeded"
    assert checked == [(["env", "--name", "tex"], str(clone_dir))]


def test_get_job_progress(tmp_path):
    from calkit.browser_link import get_job_progress, get_n_pipeline_stages

    # Each of a stage's iterations is counted, as DVC runs them
    (tmp_path / "dvc.yaml").write_text(
        "stages:\n"
        "  a:\n    cmd: echo a\n"
        "  sweep:\n    cmd: echo ${item.n} ${item.m}\n"
        "    matrix:\n      n: [1, 2, 3]\n      m: [x, y]\n"
        "  each:\n    cmd: echo ${item}\n    foreach: [p, q]\n"
    )
    assert get_n_pipeline_stages(str(tmp_path)) == 9
    assert get_n_pipeline_stages(str(tmp_path / "nope")) is None
    # From what 'calkit run --save --overleaf' prints as it goes
    lines = [
        "💻 Getting system information",
        "Syncing paper with Overleaf project ID abc",
        "Pulling the latest version from Overleaf",
        "🔀 Compiling DVC pipeline",
        "Stage 'a' didn't change, skipping",
        "Running stage 'sweep@n1-mx':",
        "> echo 1 x",
        "Updating lock file 'dvc.lock'",
        "Running stage 'sweep@n1-my':",
        "Pipeline completed successfully ✅",
        "Saving the project after successful run",
        "Syncing paper with Overleaf project ID abc",
    ]
    expected = [
        {"phase": "starting", "stage": None, "n_done": 0},
        {"phase": "syncing", "stage": None, "n_done": 0},
        {"phase": "syncing", "stage": None, "n_done": 0},
        {"phase": "running", "stage": None, "n_done": 0},
        {"phase": "running", "stage": None, "n_done": 1},
        {"phase": "running", "stage": "sweep@n1-mx", "n_done": 1},
        {"phase": "running", "stage": "sweep@n1-mx", "n_done": 1},
        {"phase": "running", "stage": "sweep@n1-mx", "n_done": 1},
        {"phase": "running", "stage": "sweep@n1-my", "n_done": 2},
        {"phase": "finishing", "stage": None, "n_done": 3},
        {"phase": "saving", "stage": None, "n_done": 3},
        {"phase": "syncing", "stage": None, "n_done": 3},
    ]
    for i, want in enumerate(expected):
        log = "\n".join(lines[: i + 1])
        assert get_job_progress(log, 9) == want | {"n_stages": 9}
    # More seen than the pipeline has, e.g., a subproject's, still adds up
    log = "\n".join(f"Stage 's{i}' didn't change, skipping" for i in range(4))
    assert get_job_progress(log, 2)["n_stages"] == 4
    assert get_job_progress("", None)["n_stages"] is None


def test_get_pdf_chunk(tmp_path, monkeypatch):
    import base64
    import time

    import calkit.browser_link
    from calkit.browser_link import (
        get_pdf_chunk,
        get_pdf_path,
        get_source_text,
    )

    home = make_home(tmp_path, monkeypatch)
    project = home / "calkit" / "proj"
    make_project(project, "me", "proj")
    with open(project / "calkit.yaml", "a") as f:
        f.write(
            "publications:\n  - path: paper/main.pdf\n"
            "pipeline:\n  stages:\n    build-notes:\n      kind: latex\n"
            "      target_path: notes/notes.tex\n"
            # Relative to its working directory, built where it says
            "    build-talk:\n      kind: latex\n      wdir: talk\n"
            "      target_path: main.tex\n"
            "    build-poster:\n      kind: latex\n"
            "      target_path: poster/main.tex\n"
            "      output_dir: poster/build\n"
        )
    os.makedirs(project / "paper")
    (project / "paper" / "main.tex").write_text("Hi\n")
    pdf = b"%PDF-1.5\n" + bytes(range(256)) * 10
    (project / "paper" / "main.pdf").write_bytes(pdf)
    git("add", "-A", cwd=project)
    git("commit", "-qm", "Build", cwd=project)
    # A publication's, or else a LaTeX stage's
    assert get_pdf_path(str(project), "paper") == "paper/main.pdf"
    assert get_pdf_path(str(project), "notes") == "notes/notes.pdf"
    assert get_pdf_path(str(project), "pap") is None
    assert get_pdf_path(str(project), "talk") == "talk/main.pdf"
    assert get_pdf_path(str(project), "poster") == "poster/build/main.pdf"
    # Read a part at a time, with how fresh it is in the first
    monkeypatch.setattr(calkit.browser_link, "PDF_CHUNK_BYTES", 1000)
    first = get_pdf_chunk(str(project), "paper", 0)
    assert first["size"] == len(pdf) and first["path"] == "paper/main.pdf"
    assert len(first["commit_sha"]) == 40
    assert first["changed_since_commit"] is False
    assert first["edited_since_built"] is False
    data = base64.b64decode(first["data"])
    while len(data) < len(pdf):
        reply = get_reply(
            {
                "type": "publication.pdf",
                "project": "me/proj",
                "folder": "paper",
                "offset": len(data),
            }
        )
        assert "built" not in reply["result"]
        data += base64.b64decode(reply["result"]["data"])
    assert data == pdf
    # What the build leaves after the PDF, which Git ignores, doesn't count
    later = time.time() + 10
    (project / "paper" / ".gitignore").write_text("*.synctex.gz\n")
    os.utime(project / "paper" / ".gitignore", (0, 0))
    (project / "paper" / "main.synctex.gz").write_bytes(b"")
    os.utime(project / "paper" / "main.synctex.gz", (later, later))
    assert not get_pdf_chunk(str(project), "paper", 0)["edited_since_built"]
    # Its source changing after it was built, and it being rebuilt without
    # saving, are both said
    os.utime(project / "paper" / "main.tex", (later, later))
    assert get_pdf_chunk(str(project), "paper", 0)["edited_since_built"]
    # Including one whose name isn't ASCII
    os.utime(project / "paper" / "main.tex", (0, 0))
    (project / "paper" / "café.tex").write_text("Hi\n")
    os.utime(project / "paper" / "café.tex", (later, later))
    assert get_pdf_chunk(str(project), "paper", 0)["edited_since_built"]
    (project / "paper" / "main.pdf").write_bytes(pdf + b"more")
    assert get_pdf_chunk(str(project), "paper", 0)["changed_since_commit"]
    with pytest.raises(ValueError, match="hasn't been built"):
        get_pdf_chunk(str(project), "notes", 0)
    # Its SyncTeX file the same way, with only when it was built
    (project / "paper" / "main.synctex.gz").write_bytes(b"synctex")
    reply = get_reply(
        {
            "type": "publication.synctex",
            "project": "me/proj",
            "folder": "paper",
            "offset": 0,
        }
    )
    assert reply["result"]["path"] == "paper/main.synctex.gz"
    assert base64.b64decode(reply["result"]["data"]) == b"synctex"
    assert "built" in reply["result"]
    assert "commit_sha" not in reply["result"]
    # A LaTeX file in the folder as it is here, by its path on Overleaf
    reply = get_reply(
        {
            "type": "publication.source",
            "project": "me/proj",
            "folder": "paper",
            "path": "café.tex",
        }
    )
    assert reply["result"] == {"path": "paper/café.tex", "text": "Hi\n"}
    for path, error in [
        ("../calkit.yaml", "isn't in paper"),
        ("main.pdf", "isn't a LaTeX file"),
        ("none.tex", "isn't on this machine"),
    ]:
        with pytest.raises(ValueError, match=error):
            get_source_text(str(project), "paper", path)
    # Never one outside the project, e.g., through a link
    if os.name != "nt":
        (tmp_path / "outside.pdf").write_bytes(pdf)
        os.makedirs(project / "notes")
        os.symlink(tmp_path / "outside.pdf", project / "notes" / "notes.pdf")
        with pytest.raises(ValueError, match="isn't in the project"):
            get_pdf_chunk(str(project), "notes", 0)
    for offset in [-1, "0"]:
        reply = get_reply(
            {
                "type": "publication.pdf",
                "project": "me/proj",
                "folder": "paper",
                "offset": offset,
            }
        )
        assert "whole number" in reply["error"]


def test_get_pipeline(tmp_path):
    from calkit.browser_link import get_pipeline

    project = tmp_path / "project"
    project.mkdir()
    subprocess.check_call(["calkit", "init"], cwd=project)
    # Declared out of name order, which is the order they're listed in
    stages = {
        "make-b": {
            "kind": "command",
            "environment": "_system",
            "command": "echo b > b.txt",
            "outputs": ["b.txt"],
        },
        "make-a": {
            "kind": "command",
            "environment": "_system",
            "command": "echo a > a.txt",
            "outputs": ["a.txt"],
        },
        # Run once per value, each recorded as its own run
        "make-each": {
            "kind": "command",
            "environment": "_system",
            "command": "echo {n} > {n}.txt",
            "iterate_over": [{"arg_name": "n", "values": ["x", "y"]}],
            "outputs": ["{n}.txt"],
        },
    }
    with open(project / "calkit.yaml", "w") as f:
        calkit.ryaml.dump({"pipeline": {"stages": stages}}, f)
    cwd = os.getcwd()
    res = get_pipeline(str(project))
    assert os.getcwd() == cwd
    assert res["ck_stages"] == ["make-b", "make-a", "make-each"]
    assert res["status"] == "stale"
    assert res["stage_statuses"]["make-b"]["status"] == "not-run"
    assert res["dvc_stages"]["make-a"]["cmd"].endswith("echo a > a.txt")
    assert res["dvc_stages"]["make-a"]["outs"] == ["a.txt"]
    subprocess.check_call(["calkit", "run"], cwd=project)
    res = get_pipeline(str(project))
    assert res["status"] == "up-to-date"
    assert {s["status"] for s in res["stage_statuses"].values()} == {
        "up-to-date"
    }
    # A changed command makes it stale, and says so
    stages["make-a"]["command"] = "echo A > a.txt"
    with open(project / "calkit.yaml", "w") as f:
        calkit.ryaml.dump({"pipeline": {"stages": stages}}, f)
    status = get_pipeline(str(project))["stage_statuses"]
    assert status["make-a"]["status"] == "stale"
    assert status["make-a"]["modified_command"]
    assert status["make-b"]["status"] == "up-to-date"


def test_get_provenance(tmp_path, monkeypatch):
    from calkit.browser_link import get_provenance

    home = make_home(tmp_path, monkeypatch)
    # Committing with no Git config in the home folder
    for var in ["AUTHOR", "COMMITTER"]:
        monkeypatch.setenv(f"GIT_{var}_NAME", "T")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "t@example.com")
    project = home / "calkit" / "proj"
    project.mkdir(parents=True)
    subprocess.check_call(["calkit", "init"], cwd=project)
    (project / "data.csv").write_text("x\n1\n")
    stages = {
        "summarize": {
            "kind": "command",
            "environment": "_system",
            # The same in Windows' shell as in others
            "command": (
                f'"{sys.executable}" -c "import json; '
                "json.dump({'n': 1}, open('results.json', 'w'))\""
            ),
            "inputs": ["data.csv"],
            "outputs": ["results.json"],
        },
        "copy": {
            "kind": "command",
            "environment": "_system",
            "command": (
                f'"{sys.executable}" -c "'
                "open('out-{n}.txt', 'w').write(open('in-{n}.txt').read())\""
            ),
            "inputs": ["in-{n}.txt"],
            "outputs": ["out-{n}.txt"],
            "iterate_over": [{"arg_name": "n", "values": ["x", "y"]}],
        },
        "draw": {
            "kind": "command",
            "environment": "_system",
            "command": (
                f'"{sys.executable}" -c "import os; '
                "os.makedirs('figs', exist_ok=True); "
                "open('figs/a.txt', 'w').write('a')\""
            ),
            "outputs": ["figs"],
        },
    }
    for n in ["x", "y"]:
        (project / f"in-{n}.txt").write_text(n)
    with open(project / "calkit.yaml", "a") as f:
        f.write("owner: me\nname: proj\n")
        calkit.ryaml.dump({"pipeline": {"stages": stages}}, f)
    subprocess.check_call(["calkit", "run"], cwd=project)
    # The pipeline's status is checked once for several asked for together
    checks = []
    real_get_status = calkit.pipeline.get_status

    def get_status(*args, **kwargs):
        checks.append(1)
        return real_get_status(*args, **kwargs)

    monkeypatch.setattr(calkit.pipeline, "get_status", get_status)
    for path in ["results.png", "results.pdf"]:
        assert not get_provenance(str(project), path)["exists"]
    assert len(checks) == 1
    # The stage that makes it here, its value, how fresh it is, and the
    # data nothing records the origin of, as the hub says them
    res = get_provenance(str(project), "results.json", key="n")
    assert res["stage"] == "summarize" and res["value"] == 1
    assert res["stage_status"]["status"] == "up-to-date"
    assert res["inputs"] == ["data.csv"]
    assert [g["path"] for g in res["gaps"]] == ["data.csv"]
    assert get_reply(
        {
            "type": "project.provenance",
            "project": "me/proj",
            "path": "data.csv",
        }
    )["result"]["input_to_stages"] == ["summarize"]
    # Each iteration has its own status, and an entry dvc.lock kept from
    # before the stage was a matrix isn't taken for the current stage
    (project / "in-y.txt").write_text("changed")
    lock = calkit.ryaml.load((project / "dvc.lock").read_text())
    lock["stages"] = {"copy": lock["stages"]["copy@x"], **lock["stages"]}
    with open(project / "dvc.lock", "w") as f:
        calkit.ryaml.dump(lock, f)
    res = get_provenance(str(project), "out-x.txt")
    assert res["stage"] == "copy@x"
    assert res["stage_status"]["status"] == "up-to-date"
    res = get_provenance(str(project), "out-y.txt")
    assert res["stage"] == "copy@y" and res["stale_reason"] == "pipeline"
    # A file in a folder a stage makes is there when DVC has it, even if
    # it isn't pulled, but not a name that folder doesn't have
    (project / "figs" / "a.txt").unlink()
    assert get_provenance(str(project), "figs/a.txt")["exists"]
    assert not get_provenance(str(project), "figs/typo.txt")["exists"]
    # Nothing a symlink takes outside the project is read
    if sys.platform != "win32":
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.json").write_text('{"n": 2}')
        os.symlink(outside / "secret.json", project / "link.json")
        os.symlink(outside, project / "ext")
        for path in ["link.json", "ext/secret.json"]:
            res = get_provenance(str(project), path, key="n")
            assert res["value"] is None and not res["exists"]
    # Only paths in the project
    for path in ["../x", "/etc/passwd", 5]:
        reply = get_reply(
            {"type": "project.provenance", "project": "me/proj", "path": path}
        )
        assert not reply["ok"]


def test_get_figures(tmp_path):
    from calkit.browser_link import get_figures

    project = tmp_path / "project"
    (project / "figures").mkdir(parents=True)
    subprocess.check_call(["git", "init", "-q"], cwd=project)
    (project / "figures" / "a.png").write_text("png")
    (project / "calkit.yaml").write_text(
        "figures:\n  - path: figures/b.svg\n    title: The setup\n"
        "misc:\n  - path: paper/drawn.png\n    created_by:\n"
        "      - name: Pat\n"
    )
    assert get_figures(str(project)) == {
        "items": [
            {"path": "figures/b.svg", "title": "The setup"},
            {"path": "figures/a.png", "title": "a"},
            {"path": "paper/drawn.png", "title": "drawn"},
        ],
        "total": 3,
    }


def test_add_stage_from_script(tmp_path, monkeypatch):
    import calkit.browser_link
    from calkit.browser_link import add_stage_from_script, run_job, start_job

    make_home(tmp_path, monkeypatch)
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "test@example.com")
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "paper" / "figures").mkdir(parents=True)
    subprocess.check_call(["calkit", "init"], cwd=project)
    (project / "calkit.yaml").write_text(
        "overleaf_sync:\n  paper:\n    url: https://www.overleaf.com/project/abc\n"
    )
    paper = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\includegraphics[width=\\linewidth]{figures/fit}\n"
        "\\end{document}\n"
    )
    (project / "paper" / "paper.tex").write_text(paper)
    (project / "paper" / "figures" / "fit.png").write_text("png")
    (project / "notes.txt").write_text("first")
    repo = calkit.git.get_repo(str(project))
    repo.git.add("-A")
    repo.git.commit("-m", "Start")
    script = (
        "import matplotlib.pyplot as plt\n"
        "import pandas as pd\n"
        "df = pd.read_csv('data/raw.csv')\n"
        "fig, ax = plt.subplots()\n"
        "fig.savefig('figures/fit.png')\n"
    )
    (project / "scripts" / "plot.py").write_text(script)
    msg = {"scriptPath": "scripts/plot.py", "shows": "paper/figures/fit.png"}
    # Read, not saved, leaving the checkout as it was
    res = add_stage_from_script(str(project), msg)
    assert not res["saved"]
    assert res["stage_name"] == "plot"
    assert res["environment_is_new"]
    assert set(res["dependencies"]) == {"matplotlib", "pandas"}
    assert res["inputs"] == ["data/raw.csv"]
    assert res["missing_inputs"] == ["data/raw.csv"]
    assert res["outputs"] == ["figures/fit.png"]
    assert res["produces"] == "figures/fit.png"
    assert res["included_in"] == ["paper/paper.tex"]
    assert repo.git.status("--porcelain", "-uall") == "?? scripts/plot.py"
    # Detection failing leaves the host where it was
    cwd = os.getcwd()
    with monkeypatch.context() as m:
        m.setattr(
            calkit.pipeline.detect,
            "detect_stage",
            Mock(side_effect=ValueError("no")),
        )
        with pytest.raises(ValueError, match="no"):
            add_stage_from_script(str(project), msg)
    assert os.getcwd() == cwd
    # Read in a job of its own, the stage is the same, until the script
    # changes
    monkeypatch.setattr(
        calkit.browser_link,
        "get_checkout_paths",
        lambda owner, name: [str(project)],
    )
    monkeypatch.setattr(calkit.browser_link, "start_detached", Mock())
    job = start_job(
        {
            "kind": "detect",
            "project": "me/proj",
            "scriptPath": "scripts/plot.py",
        }
    )
    run_job(job["id"])
    from_job = add_stage_from_script(
        str(project), msg | {"detectJob": job["id"]}
    )
    assert from_job == res
    (project / "scripts" / "other.py").write_text("print(1)\n")
    with pytest.raises(ValueError, match="didn't read 'scripts/other.py'"):
        add_stage_from_script(
            str(project),
            msg | {"scriptPath": "scripts/other.py", "detectJob": job["id"]},
        )
    (project / "scripts" / "plot.py").write_text(script + "\n")
    with pytest.raises(ValueError, match="changed since it was read"):
        add_stage_from_script(str(project), msg | {"detectJob": job["id"]})
    (project / "scripts" / "plot.py").write_text(script)
    (project / "scripts" / "other.py").unlink()
    # One that takes too long is stopped
    with monkeypatch.context() as m:
        m.setattr(calkit.browser_link, "DETECT_JOB_SECONDS", 0)
        m.setattr(
            calkit.browser_link,
            "get_calkit_cmd",
            lambda *args: [
                sys.executable,
                "-c",
                "import time; time.sleep(60)",
            ],
        )
        stuck = start_job(
            {
                "kind": "detect",
                "project": "me/proj",
                "scriptPath": "scripts/plot.py",
            }
        )
        run_job(stuck["id"])
    with pytest.raises(ValueError, match="took too long"):
        add_stage_from_script(str(project), msg | {"detectJob": stuck["id"]})
    # A path given in full is the same script
    full_msg = msg | {"scriptPath": str(project / "scripts" / "plot.py")}
    assert (
        add_stage_from_script(str(project), full_msg)["stage_name"] == "plot"
    )
    # Uploads, data, and paths outside the project are for the hub
    for bad, error in [
        ({"content": "cHJpbnQoMSk="}, "folder on this machine"),
        ({"data": [{"external": "/x", "path": "data/x"}]}, "Move the data"),
        ({"scriptPath": "../plot.py"}, "isn't in the project"),
        ({"scriptPath": "scripts/none.py"}, "isn't in the project"),
        ({"scriptPath": "notes.txt"}, "Scripts can be"),
    ]:
        with pytest.raises(ValueError, match=error):
            add_stage_from_script(str(project), msg | bad)
    # Unsaved edits to what it changes aren't swept up or overwritten
    (project / "paper" / "paper.tex").write_text(paper + "% draft\n")
    with pytest.raises(ValueError, match="paper/paper.tex has changes"):
        add_stage_from_script(str(project), msg | {"save": True})
    (project / "paper" / "paper.tex").write_text(paper)
    # Saved: only what it wrote is committed, and nothing else changed here
    (project / "notes.txt").write_text("second")
    # A save that fails is undone, so a try again isn't refused
    with monkeypatch.context() as m:
        m.setattr(
            calkit.pipeline, "to_dvc", Mock(side_effect=RuntimeError("no"))
        )
        with pytest.raises(RuntimeError):
            add_stage_from_script(str(project), msg | {"save": True})
    assert repo.git.status("--porcelain", "-uall").splitlines() == [
        " M notes.txt",
        "?? scripts/plot.py",
    ]
    res = add_stage_from_script(str(project), msg | {"save": True})
    assert res["saved"]
    ck_info = calkit.load_calkit_info(wdir=str(project))
    stage = ck_info["pipeline"]["stages"]["plot"]
    assert stage["script_path"] == "scripts/plot.py"
    assert stage["environment"] in ck_info["environments"]
    assert (
        "\\ckfigure[width=\\linewidth]{figures/fit.png}"
        in (project / "paper" / "paper.tex").read_text()
    )
    committed = repo.git.show("--name-only", "--format=", "HEAD").split()
    assert {
        "calkit.yaml",
        "dvc.yaml",
        "paper/paper.tex",
        "scripts/plot.py",
        res["environment_spec_path"],
    } <= set(committed)
    assert "notes.txt" not in committed
    assert repo.git.status("--porcelain") == " M notes.txt"
    # Asked again for what the document now shows, it's the stage as saved,
    # with nothing new to commit
    head = repo.head.commit.hexsha
    again = msg | {"shows": "figures/fit.png", "save": True}
    res = add_stage_from_script(str(project), again)
    assert res["produces"] == "figures/fit.png"
    assert res["outputs"] == ["figures/fit.png"]
    assert repo.head.commit.hexsha == head


def test_move_external_data(tmp_path, monkeypatch):
    from calkit.browser_link import move_external_data

    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "test@example.com")
    project = tmp_path / "project"
    project.mkdir()
    subprocess.check_call(["calkit", "init"], cwd=project)
    (tmp_path / "instrument").mkdir()
    (tmp_path / "instrument" / "log.csv").write_text("t,T\n0,25\n")
    script = "import pandas as pd\ndf = pd.read_csv('../instrument/log.csv')\n"
    (project / "fit.py").write_text(script)
    repo = calkit.git.get_repo(str(project))
    repo.git.add("-A")
    repo.git.commit("-m", "Start")
    msg = {
        "scriptPath": "fit.py",
        "external": "../instrument/log.csv",
        "dest": "data/log.csv",
    }
    # Copied in, the script pointed at the copy, and both committed, with
    # the original left where it was
    res = move_external_data(str(project), msg)
    assert res == {"path": "data/log.csv", "script_path": "fit.py"}
    assert (project / "data" / "log.csv").read_text() == "t,T\n0,25\n"
    assert "pd.read_csv('data/log.csv')" in (project / "fit.py").read_text()
    assert (tmp_path / "instrument" / "log.csv").exists()
    assert not repo.git.status("--porcelain")
    assert repo.head.commit.message.strip() == (
        "Move ../instrument/log.csv into the project as data/log.csv"
    )
    # Nothing in the project is replaced
    (project / "fit.py").write_text(script)
    with pytest.raises(ValueError, match="already in the project"):
        move_external_data(str(project), msg)
    # Nor is anything moved that the script doesn't name, or isn't here
    (tmp_path / "log.csv").write_text("x")
    with pytest.raises(ValueError, match="Couldn't find"):
        move_external_data(
            str(project), msg | {"external": "../log.csv", "dest": "data/x"}
        )
    with pytest.raises(ValueError, match="isn't on this machine"):
        move_external_data(
            str(project), msg | {"external": "../nope.csv", "dest": "data/y"}
        )
    assert not (project / "data" / "x").exists()


def test_record_origin_and_add_export_stage(tmp_path, monkeypatch):
    from calkit.browser_link import add_export_stage, record_origin

    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "test@example.com")
    project = tmp_path / "project"
    (project / "drawings").mkdir(parents=True)
    (project / "figures").mkdir()
    subprocess.check_call(["calkit", "init"], cwd=project)
    repo = calkit.git.get_repo(str(project))
    repo.git.config("user.email", "test@example.com")
    repo.git.config("user.name", "Test")
    (project / "figures" / "photo.jpg").write_bytes(b"jpg")
    (project / "notes.txt").write_text("first")
    repo.git.add("-A")
    repo.git.commit("-m", "Start")
    (project / "notes.txt").write_text("second")
    # Where a file came from, committed alone
    person = [{"name": "Pat", "email": "pat@example.com"}]
    entry = record_origin(
        str(project), {"path": "./figures/photo.jpg", "createdBy": person}
    )
    assert entry["path"] == "figures/photo.jpg"
    ck_info = calkit.load_calkit_info(wdir=str(project))
    assert ck_info["misc"][0]["created_by"]["email"] == "pat@example.com"
    committed = repo.git.show("--name-only", "--format=", "HEAD").split()
    assert committed == ["calkit.yaml"]
    for msg, error in [
        ({"path": "figures/none.jpg", "createdBy": person}, "isn't in"),
        ({"path": "figures/photo.jpg", "createdBy": person}, "already"),
        ({"path": "figures/photo.jpg"}, "who created it or where"),
        ({"path": "../x.jpg", "createdBy": person}, "isn't in the project"),
    ]:
        with pytest.raises(ValueError, match=error):
            record_origin(str(project), msg)
    # An export stage, shown first and then added, with the file it's
    # drawn in, made by whoever commits here, committed alongside
    (project / "drawings" / "setup.psd").write_bytes(b"psd")
    (project / "drawings" / "ignored.psd").write_bytes(b"psd")
    (project / ".git" / "info" / "exclude").write_text("ignored.psd\n")
    msg = {
        "source": "drawings/setup.psd",
        "output": "figures/setup.png",
        "app": "Photoshop",
        "files": [{"path": "drawings/setup.psd", "created_by_me": True}],
    }
    head = repo.head.commit.hexsha
    shown = add_export_stage(str(project), msg | {"save": False})
    assert not shown["saved"] and shown["name"] == "export-setup"
    assert shown["stage"]["kind"] == "manual-step"
    assert repo.head.commit.hexsha == head
    for bad, error in [
        (
            {"files": [{"path": "drawings/setup.psd", "content": "eA=="}]},
            "on this machine",
        ),
        ({"files": [{"path": "drawings/none.psd"}]}, "isn't in the project"),
        ({"files": [{"path": "drawings/ignored.psd"}]}, "ignored by Git"),
        ({"output": "../setup.png"}, "isn't in the project"),
    ]:
        with pytest.raises(ValueError, match=error):
            add_export_stage(str(project), msg | bad)
    # A dvc.yaml left unsaved, e.g., compiled by checking the pipeline's
    # status, is compiled again and saved with it, not refused
    (project / "dvc.yaml").write_text("# Stale\n")
    res = add_export_stage(str(project), msg)
    assert res["saved"] and res["name"] == "export-setup"
    assert "Stale" not in (project / "dvc.yaml").read_text()
    ck_info = calkit.load_calkit_info(wdir=str(project))
    assert ck_info["pipeline"]["stages"]["export-setup"]["kind"] == (
        "manual-step"
    )
    made = [m for m in ck_info["misc"] if m["path"] == "drawings/setup.psd"]
    assert made[0]["created_by"] == {
        "email": "test@example.com",
        "name": "Test",
    }
    committed = repo.git.show("--name-only", "--format=", "HEAD").split()
    assert {"calkit.yaml", "dvc.yaml", "drawings/setup.psd"} <= set(committed)
    assert repo.git.status("--porcelain") == " M notes.txt"
    # The same figure can't be exported twice
    with pytest.raises(ValueError, match="is made by stage 'export-setup'"):
        add_export_stage(str(project), msg)
    # Slides export with what's installed here, e.g., LibreOffice
    monkeypatch.setattr(
        calkit.export.Exporter,
        "find_executable",
        lambda self: "/bin/soffice" if self.name == "libreoffice" else None,
    )
    (project / "drawings" / "setup.pptx").write_bytes(b"pptx")
    res = add_export_stage(
        str(project),
        {
            "source": "drawings/setup.pptx",
            "output": "figures/setup.pdf",
            "files": [{"path": "drawings/setup.pptx", "created_by_me": True}],
        },
    )
    ck_info = calkit.load_calkit_info(wdir=str(project))
    env_name = ck_info["pipeline"]["stages"][res["name"]]["environment"]
    assert ck_info["environments"][env_name] == {
        "kind": "system",
        "requirements": ["libreoffice"],
    }
    # One too big for Git is stored with DVC
    (project / "drawings" / "big.psd").write_bytes(b"0" * 1_000_001)
    res = add_export_stage(
        str(project),
        {
            "source": "drawings/big.psd",
            "output": "figures/big.png",
            "app": "Photoshop",
            "files": [{"path": "drawings/big.psd"}],
        },
    )
    committed = repo.git.show("--name-only", "--format=", "HEAD").split()
    assert "drawings/big.psd.dvc" in committed
    assert "drawings/big.psd" not in committed
    assert repo.git.status("--porcelain") == " M notes.txt"


def test_get_content_paths(tmp_path):
    from calkit.browser_link import get_content_paths

    project = tmp_path / "project"
    (project / ".dvc").mkdir(parents=True)
    (project / "data").mkdir()
    subprocess.check_call(["git", "init", "-q"], cwd=project)
    (project / ".gitignore").write_text("*.log\n/data/raw.csv\n")
    (project / ".dvc" / "config").write_text("")
    (project / "data" / "raw.csv.dvc").write_text("outs:\n- path: raw.csv\n")
    (project / "run.log").write_text("")
    (project / "script.py").write_text("")
    (project / "dvc.lock").write_text(
        "schema: '2.0'\nstages:\n  fit:\n    outs:\n"
        "    - path: results/fit.json\n      md5: abc\n"
        "    - path: results/plots\n      md5: def.dir\n"
    )
    repo = calkit.git.get_repo(str(project))
    repo.git.add(".gitignore", "data/raw.csv.dvc", ".dvc/config", "dvc.lock")
    # Tracked, made by the pipeline, and not saved yet, but not ignored, DVC
    # internals, or folders the pipeline makes
    assert get_content_paths(str(project)) == [
        ".gitignore",
        "data/raw.csv",
        "dvc.lock",
        "results/fit.json",
        "script.py",
    ]


def test_choose_folder(tmp_path, monkeypatch):
    from calkit.browser_link import choose_folder

    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "fit.py").write_text("")
    empty = tmp_path / "empty"
    empty.mkdir()
    calls = []

    def run(answer, returncode=0):
        def fake(cmd, **kwargs):
            calls.append((cmd, kwargs["env"]["CALKIT_PROMPT"]))
            return subprocess.CompletedProcess(cmd, returncode, answer, "")

        monkeypatch.setattr("subprocess.run", fake)
        return choose_folder("Select a folder for proj")

    # The prompt goes in the environment, so nothing in it is run
    assert run(f"{analysis}/\n") == {"path": str(analysis), "empty": False}
    assert calls[-1][1] == "Select a folder for proj"
    assert run(f"{empty}\n") == {"path": str(empty), "empty": True}
    # Cancelled
    assert run("", returncode=1) == {"path": None, "empty": True}

    def missing(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr("subprocess.run", missing)
    with pytest.raises(ValueError, match="no folder dialog"):
        choose_folder("Select")


def test_get_printed_numbers(tmp_path):
    from calkit.browser_link import get_printed_numbers

    printed = {
        "cell_type": "code",
        "id": "a",
        "source": "k = 0.0309\nprint(k)",
        "outputs": [{"output_type": "stream", "text": "0.0309\n"}],
    }
    cleaned = printed | {"outputs": []}
    (tmp_path / "fit.ipynb").write_text(json.dumps({"cells": [printed]}))
    # A notebook saved without outputs is read from the copy the pipeline
    # ran, and one with parameters is left out
    (tmp_path / "clean.ipynb").write_text(json.dumps({"cells": [cleaned]}))
    executed = tmp_path / ".calkit" / "notebooks" / "executed"
    executed.mkdir(parents=True)
    (executed / "clean.ipynb").write_text(json.dumps({"cells": [printed]}))
    (tmp_path / "calkit.yaml").write_text(
        "pipeline:\n"
        "  stages:\n"
        "    fit:\n"
        "      kind: jupyter-notebook\n"
        "      notebook_path: fit.ipynb\n"
        "      environment: py\n"
        "    clean:\n"
        "      kind: jupyter-notebook\n"
        "      notebook_path: clean.ipynb\n"
        "      environment: py\n"
        "    swept:\n"
        "      kind: jupyter-notebook\n"
        "      notebook_path: fit.ipynb\n"
        "      environment: py\n"
        "      parameters:\n"
        "        t: 25\n"
        "    missing:\n"
        "      kind: jupyter-notebook\n"
        "      notebook_path: missing.ipynb\n"
        "      environment: py\n"
    )
    found = {
        "cell": "a",
        "cell_index": 0,
        "numbers": ["0.0309"],
        "variables": ["k"],
    }
    assert get_printed_numbers(str(tmp_path)) == [
        {"notebook": "fit.ipynb", "stage": "fit"} | found,
        {"notebook": "clean.ipynb", "stage": "clean"} | found,
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="Policies in registry")
def test_get_policy_blocks(tmp_path, monkeypatch):
    import getpass
    import plistlib

    from calkit.browser_link import get_policy_blocks

    monkeypatch.setattr(
        calkit.browser_link,
        "POLICY_PATHS",
        {
            platform.system(): {
                "chrome": [str(tmp_path / "chrome" / "*.json")],
                "edge": [str(tmp_path / "{user}" / "edge.plist")],
            }
        },
    )
    (tmp_path / "chrome").mkdir()
    # Nothing set, or hosts allowed, blocks nothing
    assert get_policy_blocks() == {}
    policy = tmp_path / "chrome" / "policy.json"
    policy.write_text(json.dumps({"NativeMessagingBlocklist": ["other"]}))
    assert get_policy_blocks() == {}
    # Blocking every host, unless Calkit's is allowed
    policy.write_text(json.dumps({"NativeMessagingBlocklist": ["*"]}))
    assert "NativeMessagingAllowlist" in get_policy_blocks()["chrome"]
    policy.write_text(
        json.dumps(
            {
                "NativeMessagingBlocklist": ["*"],
                "NativeMessagingAllowlist": ["io.calkit.native"],
            }
        )
    )
    assert get_policy_blocks() == {}
    # Only allowing hosts installed for every user, from a Mac's managed
    # preferences for this user
    user_dir = tmp_path / getpass.getuser()
    user_dir.mkdir()
    with open(user_dir / "edge.plist", "wb") as f:
        plistlib.dump({"NativeMessagingUserLevelHosts": False}, f)
    assert get_policy_blocks() == {
        "edge": "only hosts installed for all users allowed"
    }
