"""Tests for ``calkit.operator``."""

import asyncio
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from calkit import operator


def _init_project(path, owner="alice", name="demo"):
    os.makedirs(path)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    with open(os.path.join(path, "calkit.yaml"), "w") as f:
        f.write(f"owner: {owner}\nname: {name}\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=a@b.c",
            "-c",
            "user.name=a",
            "commit",
            "-qm",
            "init",
        ],
        cwd=path,
        check=True,
    )


def test_config_and_workspaces(tmp_path, monkeypatch):
    home = str(tmp_path)
    monkeypatch.setenv("CALKIT_USER_HOME", home)
    # The config holds a token, so only the user can read it, even if it
    # was readable before
    operator.save_config({"name": "box", "token": "cko_x", "workspaces": []})
    if sys.platform != "win32":
        os.chmod(operator.get_config_path(), 0o644)
        operator.save_config(
            {"name": "box", "token": "cko_x", "workspaces": []}
        )
        mode = stat.S_IMODE(os.stat(operator.get_config_path()).st_mode)
        assert mode == 0o600
    # Only encrypted connections are made, except locally
    for url in [
        "https://api.calkit.io",
        "wss://relay.calkit.io",
        "http://api.localhost",
        "ws://localhost:8002",
    ]:
        operator.check_secure_url(url)
    for url in ["http://api.calkit.io", "ws://relay.calkit.io", "ftp://x"]:
        with pytest.raises(ValueError):
            operator.check_secure_url(url)
    # Registering uses the user's own hub, never one named by a project in
    # the working directory, which could be anyone's
    from calkit import config

    project = tmp_path / "cloned"
    project.mkdir()
    (project / "calkit.yaml").write_text("hub: https://evil.example\n")
    monkeypatch.chdir(project)
    monkeypatch.setenv("CALKIT_ENV", "")
    monkeypatch.setenv("CALKIT_HUB", "")
    monkeypatch.delenv("CALKIT_HUB")
    monkeypatch.setattr(config, "_get_default_hub", lambda: None)
    assert operator.use_own_hub() == "https://api.calkit.io"
    monkeypatch.setenv("CALKIT_HUB", "http://hub.example")
    with pytest.raises(ValueError):
        operator.use_own_hub()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CALKIT_ENV", "test")
    assert operator.load_config() == {
        "name": "box",
        "token": "cko_x",
        "workspaces": [],
    }
    # Projects under ~/calkit are found; other folders there are not
    _init_project(os.path.join(home, "calkit", "demo"))
    os.makedirs(os.path.join(home, "calkit", "not-a-project"))
    with open(os.path.join(home, "calkit", "demo", "notes.txt"), "w") as f:
        f.write("uncommitted")
    # The hub's grant key is pinned at the first check-in of an Operator
    # registered before grants were signed, and never replaced after
    from calkit import hub

    keys = iter(["key1", "key2"])
    monkeypatch.setattr(
        hub, "_request", lambda *a, **kw: {"grant_public_key": next(keys)}
    )
    cfg = {"token": "cko_x", "api_url": "https://api.hub", "workspaces": []}
    operator.check_in(cfg, [], "service")
    operator.check_in(cfg, [], "service")
    assert operator.load_config()["grant_public_key"] == "key1"
    # Registered projects elsewhere are found, but only once
    elsewhere = os.path.join(home, "src", "other")
    _init_project(elsewhere, name="other")
    # Managed workspaces are found under <hub>/<owner>/<name>
    managed = os.path.join(
        home, ".calkit", "workspaces", "calkit.io", "alice", "demo"
    )
    _init_project(managed)
    cfg = {"workspaces": [elsewhere, elsewhere + "/"]}
    workspaces = {
        Path(os.path.relpath(w["path"], os.path.realpath(home))).as_posix(): w
        for w in operator.discover_workspaces(cfg)
    }
    assert set(workspaces) == {
        "calkit/demo",
        "src/other",
        ".calkit/workspaces/calkit.io/alice/demo",
    }
    demo = workspaces["calkit/demo"]
    assert demo["kind"] == "personal"
    assert demo["project"] == "alice/demo"
    assert demo["dirty"]
    assert len(demo["commit"]) == 40
    assert demo["branch"] is not None
    assert not workspaces["src/other"]["dirty"]
    assert workspaces["src/other"]["project"] == "alice/other"
    managed_ws = workspaces[".calkit/workspaces/calkit.io/alice/demo"]
    assert managed_ws["kind"] == "managed"
    # Managed workspaces can be read but not changed from the hub
    op = operator.Operator(cfg)
    op.workspaces = list(workspaces.values())
    assert op.get_workspace(managed, personal=False) == managed_ws["path"]
    with pytest.raises(ValueError):
        op.get_workspace(managed)
    with pytest.raises(ValueError):
        op.get_workspace(home)


@pytest.mark.skipif(sys.platform == "win32", reason="Sessions need a PTY")
@pytest.mark.asyncio
async def test_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    monkeypatch.setenv("SHELL", "/bin/sh")
    _init_project(os.path.join(tmp_path, "calkit", "demo"))
    import base64
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )

    hub_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        hub_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    op = operator.Operator(
        {
            "id": "op1",
            "user_id": "owner",
            "grant_public_key": public_key,
            "workspaces": [],
        }
    )
    op.workspaces = operator.discover_workspaces(op.cfg)

    def grant(sub="owner", aud="op1", expires_in=60, key=hub_key, jti=None):
        return jwt.encode(
            {
                "exp": time.time() + expires_in,
                "aud": aud,
                "sub": sub,
                "jti": jti or os.urandom(8).hex(),
            },
            key,
            algorithm="EdDSA",
        )

    workspace = op.workspaces[0]["path"]
    sent: list[tuple[str, dict]] = []

    async def send(ch, msg):
        sent.append((ch, msg))

    monkeypatch.setattr(op, "send", send)

    async def wait_for(predicate, timeout=10.0):
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.05)

    def output(ch):
        return "".join(
            m["data"]
            for c, m in sent
            if c == ch and m["type"] == "sessions.output"
        )

    def reply(req_id):
        replies = [m for _, m in sent if m.get("id") == req_id]
        return replies[0] if replies else None

    def message(ch, msg):
        op.on_relay_message({"type": "channel.message", "ch": ch, "msg": msg})

    # Channels are refused unless the hub signed a grant for the owner to use
    # this Operator, whatever the relay says, and each grant works once
    used = grant(jti="used")
    op.on_relay_message({"type": "channel.open", "ch": "u", "grant": used})
    op.on_relay_message({"type": "channel.close", "ch": "u"})
    for bad in [
        None,
        "nope",
        grant(sub="eve"),
        grant(aud="op2"),
        grant(expires_in=-120),
        grant(key=Ed25519PrivateKey.generate()),
        used,
    ]:
        op.on_relay_message(
            {
                "type": "channel.open",
                "ch": "x",
                "user_id": "owner",
                "grant": bad,
            }
        )
        message("x", {"type": "sessions.list", "id": 1})
    await asyncio.sleep(0.1)
    assert sent == []
    op.on_relay_message({"type": "channel.open", "ch": "a", "grant": grant()})
    # Only allowed workspaces can have sessions
    message("a", {"type": "sessions.open", "id": 2, "workspace": "/"})
    await wait_for(lambda: reply(2))
    assert reply(2)["type"] == "error"
    message("a", {"type": "sessions.open", "id": 3, "workspace": workspace})
    await wait_for(lambda: reply(3))
    sid = reply(3)["result"]["session"]
    message(
        "a",
        {
            "type": "sessions.input",
            "session": sid,
            "data": "echo HI-$((6*7))\n",
        },
    )
    await wait_for(lambda: "HI-42" in output("a"))
    # A second channel attaching gets the scrollback replayed
    op.on_relay_message({"type": "channel.open", "ch": "b", "grant": grant()})
    message("b", {"type": "sessions.attach", "id": 4, "session": sid})
    await wait_for(lambda: "HI-42" in output("b"))
    # Sessions outlive the channels attached to them
    op.on_relay_message({"type": "channel.close", "ch": "a"})
    op.on_relay_message({"type": "channel.close", "ch": "b"})
    assert op.sessions[sid].channels == set()
    op.on_relay_message({"type": "channel.open", "ch": "c", "grant": grant()})
    message("c", {"type": "sessions.list", "id": 5})
    await wait_for(lambda: reply(5))
    assert [s["id"] for s in reply(5)["result"]["sessions"]] == [sid]
    message("c", {"type": "sessions.attach", "id": 6, "session": sid})
    message(
        "c", {"type": "sessions.input", "session": sid, "data": "exit 3\n"}
    )
    await wait_for(
        lambda: [m for _, m in sent if m["type"] == "sessions.exit"]
    )
    exits = [m for _, m in sent if m["type"] == "sessions.exit"]
    assert exits == [{"type": "sessions.exit", "session": sid, "code": 3}]
    assert op.sessions == {}
    # With nothing using it, an Operator with an idle limit stops
    op.on_relay_message({"type": "channel.close", "ch": "c"})
    op.idle_exit_seconds = 0.1
    await asyncio.wait_for(op.wait_until_idle(), 5)


def test_service_files(tmp_path, monkeypatch):
    import plistlib

    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    command = [
        sys.executable,
        "-m",
        "calkit",
        "operator",
        "start",
        "--mode",
        "service",
    ]
    # launchd restarts it on failure, but not after it exits because it
    # was revoked
    agent = plistlib.loads(operator._launchd_plist(at_boot=False))
    assert agent["ProgramArguments"] == command
    assert agent["KeepAlive"] == {"SuccessfulExit": False}
    assert agent["StandardOutPath"] == operator.get_log_path()
    assert "UserName" not in agent
    assert operator._launchd_plist_path(at_boot=False).startswith(
        str(tmp_path)
    )
    # At boot it's a system daemon that still runs as this user, which only
    # macOS has
    if sys.platform != "win32":
        daemon = plistlib.loads(operator._launchd_plist(at_boot=True))
        assert daemon["UserName"]
        assert operator._launchd_plist_path(at_boot=True).startswith(
            "/Library/LaunchDaemons/"
        )
    # On Windows, a script in the Startup folder runs it hidden at login
    script = operator._windows_startup_script()
    assert "--mode" in script and "service" in script
    assert operator.get_log_path() in script
    unit = operator._systemd_unit()
    assert f"ExecStart={shlex.join(command)}" in unit
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit


@pytest.mark.skipif(sys.platform == "win32", reason="Cron and flock are POSIX")
def test_cron_and_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    # A fake crontab that keeps its table in a file
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    table = tmp_path / "crontab.txt"
    crontab = bin_dir / "crontab"
    crontab.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "-l" ]; then cat "{table}" 2>/dev/null || exit 1; '
        f'else cat > "{table}"; fi\n'
    )
    crontab.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    table.write_text("0 * * * * echo mine\n")
    # Installing twice leaves one set of entries and the user's own alone
    operator.install_cron()
    operator.install_cron()
    lines = table.read_text().splitlines()
    assert lines[0] == "0 * * * * echo mine"
    ours = [line for line in lines if operator.CRON_MARKER in line]
    assert [line.split()[0] for line in ours] == ["*/5", "@reboot"]
    assert all("--mode cron" in line for line in ours)
    assert all(operator.get_log_path() in line for line in ours)
    assert "cron" in operator.get_service_status()
    operator.uninstall_service()
    assert table.read_text().splitlines() == ["0 * * * * echo mine"]
    assert operator.get_service_status() is None
    # Only one Operator runs at a time
    lock = operator.acquire_lock()
    assert lock is not None
    with open(operator._pid_path()) as f:
        assert f.read() == str(os.getpid())
    assert operator.acquire_lock() is None
    lock.close()
    second = operator.acquire_lock()
    assert second is not None
    second.close()


def test_workspace_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    wdir = os.path.join(tmp_path, "calkit", "demo")
    _init_project(wdir)
    subprocess.run(
        [sys.executable, "-m", "dvc", "init", "-q"], cwd=wdir, check=True
    )
    for args in [["add", "."], ["commit", "-qm", "Init DVC"]]:
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=a", *args],
            cwd=wdir,
            check=True,
        )
    monkeypatch.setenv("GIT_AUTHOR_NAME", "a")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "a@b.c")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "a")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "a@b.c")
    with open(os.path.join(wdir, "notes.txt"), "w") as f:
        f.write("hi")
    with open(os.path.join(wdir, "scratch.log"), "w") as f:
        f.write("noise")
    status = operator.get_workspace_status(wdir, fetch=False)
    assert status["errors"] == []
    git = status["status"]["git"]
    assert set(git["untracked_files"]) == {"notes.txt", "scratch.log"}
    assert status["status"]["pipeline"]["stale_stage_names"] == []
    assert status["commits_ahead"] == 0
    # What the pipeline is doing, or last did, comes cheaply from the files
    # a run leaves: DVC's lock, while a live process holds it, the run log
    # for the stage it's on, and the record of how the last run ended
    assert operator.get_run_state(wdir) == {
        "running": False,
        "running_stages": [],
        "running_since": None,
        "last_run": None,
    }
    lock = os.path.join(wdir, ".dvc", "tmp", "rwlock")
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    local = os.path.join(wdir, ".calkit", "local")
    os.makedirs(os.path.join(local, "logs"))
    os.makedirs(os.path.join(local, "runs"))
    with open(
        os.path.join(local, "logs", "2026-09-29T12-00-00-a.log"), "w"
    ) as f:
        f.write(
            "2026-09-29 12:00:00,000 - INFO - Running stage 'prep':\n"
            "2026-09-29 12:05:00,000 - INFO - Running stage 'train':\n"
        )
    with open(
        os.path.join(local, "runs", "2026-09-28T09-00-00-b.json"), "w"
    ) as f:
        json.dump(
            {
                "status": "failed",
                "start_time": "2026-09-28T09:00:00+00:00",
                "end_time": "2026-09-28T09:10:00+00:00",
                "stages": {
                    "prep": {"status": "completed"},
                    "plot": {"status": "failed"},
                },
            },
            f,
        )
    last_run = {
        "status": "failed",
        "started": "2026-09-28T09:00:00+00:00",
        "ended": "2026-09-28T09:10:00+00:00",
        "failed_stages": ["plot"],
    }
    # A lock left by a process that's gone doesn't count as running
    with open(lock, "w") as f:
        json.dump(
            {
                "read": {},
                "write": {"out.txt": {"pid": 2**22, "cmd": "calkit run"}},
            },
            f,
        )
    assert not operator.get_run_state(wdir)["running"]
    with open(lock, "w") as f:
        json.dump(
            {
                "read": {},
                "write": {"out.txt": {"pid": os.getpid(), "cmd": "x"}},
            },
            f,
        )
    assert operator.get_run_state(wdir) == {
        "running": True,
        "running_stages": ["train"],
        "running_since": "2026-09-29T12:05:00+00:00",
        "last_run": last_run,
    }
    with open(lock, "w") as f:
        f.write('{"read": {}, "write": {}}')
    assert operator.get_run_state(wdir)["last_run"] == last_run
    shutil.rmtree(os.path.join(wdir, ".calkit"))
    # Paths from the hub have to be plain ones inside the workspace, so they
    # can't be taken as options or reach anything else on the machine
    outside = os.path.join(str(tmp_path), "secret")
    for bad in [
        "--push",
        "-f",
        outside,
        "../secret",
        "a/../../secret",
        "x\n!important",
    ]:
        with pytest.raises(ValueError):
            operator.save_workspace(wdir, [bad])
        with pytest.raises(ValueError):
            operator.ignore_path(wdir, bad)
        with pytest.raises(ValueError):
            operator.add_stage(wdir, name="bad", cmd="echo", deps=[bad])
    if sys.platform != "win32":
        os.symlink(str(tmp_path), os.path.join(wdir, "link"))
        with pytest.raises(ValueError):
            operator.save_workspace(wdir, ["link/secret"])
        os.remove(os.path.join(wdir, "link"))
    # Ignoring commits the .gitignore change
    operator.ignore_path(wdir, "scratch.log")
    status = operator.get_workspace_status(wdir, fetch=False)
    assert status["status"]["git"]["untracked_files"] == ["notes.txt"]
    assert status["status"]["git"]["changed_files"] == []
    # Saving commits only what it's given
    operator.save_workspace(wdir, ["notes.txt"], message="Add notes", to="git")
    status = operator.get_workspace_status(wdir, fetch=False)
    assert status["status"]["git"]["untracked_files"] == []
    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=wdir, capture_output=True, text=True
    ).stdout.splitlines()
    assert log[:2] == ["Add notes", "Ignore scratch.log"]
    # Stages are added and committed, with an object for their output
    operator.add_stage(
        wdir,
        name="plot",
        cmd="python plot.py",
        outs=["fig.png"],
        calkit_type="figure",
        calkit_object={"title": "A plot", "description": "It plots"},
    )
    with pytest.raises(ValueError):
        operator.add_stage(wdir, name="plot", cmd="echo")
    with pytest.raises(ValueError):
        operator.add_stage(wdir, name="other", cmd="echo", outs=["fig.png"])
    import calkit

    figures = calkit.load_calkit_info(wdir=wdir)["figures"]
    assert figures == [
        {
            "path": "fig.png",
            "stage": "plot",
            "title": "A plot",
            "description": "It plots",
        }
    ]
    # Running without a terminal reports how it went; this stage's script
    # doesn't exist, so it fails
    result = operator.run_pipeline(wdir)
    # Single stages can be run, and their names can't be options
    result = operator.run_pipeline(wdir, stages=["plot"])
    assert result["ok"] is False and "plot" in result["output"]
    for bad in ["--force", "-f", "a b", "x;y", ""]:
        with pytest.raises(ValueError):
            operator.run_pipeline(wdir, stages=[bad])
    assert result["ok"] is False
    assert result["output"]
    subprocess.run(["git", "checkout", "--", "."], cwd=wdir, check=True)
    # Changes to DVC-tracked files show up too, and discarding puts back
    # what was committed with either
    with open(os.path.join(wdir, "big.csv"), "w") as f:
        f.write("1,2\n")
    subprocess.run(
        [sys.executable, "-m", "dvc", "add", "-q", "big.csv"],
        cwd=wdir,
        check=True,
    )
    operator.save_workspace(wdir, ["big.csv.dvc", ".gitignore"], to="git")
    with open(os.path.join(wdir, "big.csv"), "w") as f:
        f.write("3,4\n")
    with open(os.path.join(wdir, "notes.txt"), "w") as f:
        f.write("changed")
    status = operator.get_workspace_status(wdir, fetch=False)
    assert status["status"]["dvc"]["uncommitted"]["modified"] == ["big.csv"]
    assert status["status"]["git"]["changed_files"] == ["notes.txt"]
    operator.discard_changes(wdir)
    with open(os.path.join(wdir, "notes.txt")) as f:
        assert f.read() == "hi"
    with open(os.path.join(wdir, "big.csv")) as f:
        assert f.read() == "1,2\n"
    # Cloning puts a project under ~/calkit, where it's a workspace, and
    # won't clone over anything or outside it
    calls = []
    monkeypatch.setattr(
        operator, "_calkit", lambda args, wdir: calls.append(args)
    )
    url = "https://github.com/someone/other"
    path = operator.clone_project(url)
    assert path == os.path.join(tmp_path, "calkit", "other")
    assert calls == [["clone", url, path, "--no-dvc-pull"]]
    for bad in [
        url.replace("other", "demo"),
        "https://github.com/x/..",
        "",
        "--upload-pack=touch /tmp/x",
        "ext::sh -c touch% /tmp/x",
        "file:///etc/other",
        "/etc/other",
    ]:
        with pytest.raises(ValueError):
            operator.clone_project(bad)


def test_install_remote(monkeypatch):
    import yaml

    from calkit import hub
    from calkit import workspace as ws

    monkeypatch.setattr(ws, "ensure_reachable", lambda target, **kw: target)
    monkeypatch.setattr(ws, "ensure_calkit_installed", lambda *a, **kw: True)
    monkeypatch.setattr(
        ws,
        "remote_system_info",
        lambda target: {
            "hostname": "login1.cluster",
            "machine_id": "abc",
            "os": "Linux",
            "calkit_version": "1.0",
        },
    )
    posted = {}

    def request(kind, path, json=None, **kwargs):
        posted.update(json)
        return {"id": "op1", "name": "login1-cluster", "user_id": "u1"} | {
            "token": "cko_secret",
            "grant_public_key": "key",
        }

    monkeypatch.setattr(hub, "_request", request)
    monkeypatch.setattr(hub, "get_base_url", lambda: "https://api.hub")
    runs = []
    remote_config = {"text": ""}

    def run(argv, **kwargs):
        runs.append((argv, kwargs.get("input")))
        if "cat ~/.calkit/operator.yaml 2>" in argv[-1]:
            return SimpleNamespace(stdout=remote_config["text"])
        if fail_install and "operator install" in argv[-1]:
            raise subprocess.CalledProcessError(1, argv)
        return SimpleNamespace(stdout="")

    fail_install = False
    monkeypatch.setattr(operator.subprocess, "run", run)
    cfg = operator.install_remote("cluster", cron=True)
    # Registered from here with the far end's own details
    assert posted["hostname"] == "login1.cluster"
    assert posted["platform"] == "linux"
    assert posted["hosts"] == ["cluster", "login1.cluster"]
    # Its config goes over SSH, readable only by the user, then Calkit there
    # installs it in the mode asked for
    _, (write_argv, config_text), (install_argv, _) = runs
    assert write_argv[0] == "ssh" and "cluster" in write_argv
    assert "umask 077" in write_argv[-1]
    assert yaml.safe_load(config_text) == cfg
    assert cfg["token"] == "cko_secret" and cfg["api_url"] == "https://api.hub"
    assert "calkit operator install --cron" in install_argv[-1]
    # Reinstalling keeps the Operator already there
    remote_config["text"] = config_text
    posted.clear()
    runs.clear()
    assert operator.install_remote("cluster") == cfg
    assert posted == {}
    assert len(runs) == 2
    # A registration whose install fails is revoked
    remote_config["text"] = ""
    fail_install = True
    deleted = []
    monkeypatch.setattr(
        hub,
        "_request",
        lambda kind, path, **kw: (
            deleted.append(path)
            if kind == "delete"
            else request(kind, path, **kw)
        ),
    )
    with pytest.raises(subprocess.CalledProcessError):
        operator.install_remote("cluster")
    assert deleted == ["/operators/op1"]
