"""Tests for ``calkit.browser_link``."""

import io
import json
import os
import platform
import shutil
import struct
import subprocess
import sys

import pytest

import calkit
import calkit.config
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
            "result": {"version": calkit.__version__} | get_editor_info(),
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
            *["--with", get_editor_info()["editor"], "--path", "a.ipynb"],
        ]
        if os.name != "nt":
            assert env["PATH"].startswith("/login/bin" + os.pathsep)
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
            monkeypatch.setattr(calkit.config, "read", lambda: settings)
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

    monkeypatch.setattr(
        calkit.cli.overleaf, "_get_overleaf_auth", lambda: "token"
    )
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
    assert get_overleaf_sync_statuses(str(project), path="paper") == [status]
    assert get_overleaf_sync_statuses(str(project), "other-id") == []
    with pytest.raises(ValueError, match="isn't synced"):
        get_overleaf_sync_statuses(str(project), path="nope")
    # Without credentials, it says so as the hub does, so the extension
    # asks for them
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
    from calkit.browser_link import get_job, list_jobs, run_job, start_job

    home = make_home(tmp_path, monkeypatch)
    project = home / "calkit" / "proj"
    make_project(project, "me", "proj")
    git("commit", "-q", "--allow-empty", "-m", "Init", cwd=project)
    started = []
    real_popen = subprocess.Popen

    def popen(cmd, **kwargs):
        if cmd[1:3] == ["-m", "calkit.browser_link"]:
            started.append(cmd)
            return None
        return real_popen(cmd, **kwargs)

    monkeypatch.setattr("subprocess.Popen", popen)
    # A run saves and syncs, in a process of its own that runs the job
    job = start_job({"kind": "run", "project": "me/proj"})
    assert job["status"] == "queued" and job["wdir"] == os.path.realpath(
        project
    )
    assert job["cmd"][1:] == ["-m", "calkit", "run", "--save", "--overleaf"]
    assert job["branch"] and len(job["git_rev"]) == 40
    assert started == [
        [sys.executable, "-m", "calkit.browser_link", "job", job["id"]]
    ]
    assert get_reply({"type": "job.get", "job_id": job["id"]})["result"] == job
    # One at a time
    reply = get_reply(
        {"type": "job.start", "kind": "run", "project": "me/proj"}
    )
    assert not reply["ok"] and "already running" in reply["error"]
    # Without syncing after, it only runs
    job_path = calkit.browser_link.get_job_path(job["id"])
    with open(job_path) as f:
        record = json.load(f)
    with open(job_path, "w") as f:
        json.dump(record | {"status": "succeeded"}, f)
    run_only = start_job({"kind": "run", "project": "me/proj", "sync": False})
    assert run_only["cmd"][1:] == ["-m", "calkit", "run"]
    os.remove(calkit.browser_link.get_job_path(run_only["id"]))
    # VS Code, the editor Calkit installs, from the user's home folder
    installing = start_job({"kind": "install-editor", "project": "me/proj"})
    assert installing["cmd"][1:] == [
        "-m",
        "calkit",
        "install",
        "code",
        "--yes",
    ]
    assert installing["wdir"] == calkit.get_user_home()
    os.remove(calkit.browser_link.get_job_path(installing["id"]))
    with open(job_path, "w") as f:
        json.dump(record, f)
    for msg, error in [
        ({"kind": "rm", "project": "me/proj"}, "Unknown kind"),
        ({"kind": "sync", "project": "me/proj"}, "folder"),
        ({"kind": "run", "project": "me/gone"}, "isn't on this computer"),
        (
            {"kind": "clone", "project": "me/proj", "location": str(project)},
            "isn't empty",
        ),
    ]:
        with pytest.raises(ValueError, match=error):
            start_job(msg)
    with pytest.raises(ValueError):
        get_job("../../etc/passwd")
    # Running it records how it went, with the error it ended with
    job_path = calkit.browser_link.get_job_path(job["id"])

    def run(code):
        with open(job_path) as f:
            record = json.load(f)
        record["cmd"] = [sys.executable, "-c", code]
        with open(job_path, "w") as f:
            json.dump(record, f)
        run_job(job["id"])
        return get_job(job["id"])

    done = run("print('Ran it')")
    assert done["status"] == "succeeded" and done["output"] == "Ran it"
    # Its whole log can be read, as it's written while it runs
    reply = get_reply({"type": "job.log", "job_id": job["id"]})
    assert reply["result"] == {"log": "Ran it\n"}
    assert done["started"] and done["finished"] and done["returncode"] == 0
    failed = run("print('Error: It broke'); print('Bye'); raise SystemExit(1)")
    assert failed["status"] == "failed" and failed["error"] == "It broke"
    # Missing Overleaf credentials are reported as the hub reports them
    failed = run(
        "print(\"Error: Set one with 'calkit config set overleaf_token'\");"
        "raise SystemExit(1)"
    )
    assert failed["error_status"] == 401
    # One whose process died without saying so has failed
    with open(job_path) as f:
        record = json.load(f)
    record |= {"status": "running", "pid": 2**22 + 12345}
    with open(job_path, "w") as f:
        json.dump(record, f)
    assert get_job(job["id"])["status"] == "failed"
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
    from calkit.browser_link import get_pdf_chunk, get_pdf_path

    home = make_home(tmp_path, monkeypatch)
    project = home / "calkit" / "proj"
    make_project(project, "me", "proj")
    with open(project / "calkit.yaml", "a") as f:
        f.write(
            "publications:\n  - path: paper/main.pdf\n"
            "pipeline:\n  stages:\n    build-notes:\n      kind: latex\n"
            "      target_path: notes/notes.tex\n"
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
    # Its source changing after it was built, and it being rebuilt without
    # saving, are both said
    later = time.time() + 10
    os.utime(project / "paper" / "main.tex", (later, later))
    assert get_pdf_chunk(str(project), "paper", 0)["edited_since_built"]
    (project / "paper" / "main.pdf").write_bytes(pdf + b"more")
    assert get_pdf_chunk(str(project), "paper", 0)["changed_since_commit"]
    with pytest.raises(ValueError, match="hasn't been built"):
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
