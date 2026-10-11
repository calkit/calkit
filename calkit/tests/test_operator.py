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
from typing import Any, cast

import pytest

from calkit import operator


@pytest.fixture(autouse=True)
def _hub(monkeypatch):
    # Each test acts on one hub's Operator unless it chooses another
    monkeypatch.setattr(operator, "_hub_url", "https://calkit.io")


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
    # Projects under ~/calkit and ~/dev are found; other folders there are
    # not
    _init_project(os.path.join(home, "calkit", "demo"))
    _init_project(os.path.join(home, "dev", "tool"), name="tool")
    os.makedirs(os.path.join(home, "dev", "not-calkit"))
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
    # Managed workspaces are found under <hub>/<owner>/<name>, only for
    # this Operator's hub
    managed = os.path.join(
        home, ".calkit", "workspaces", "calkit.io", "alice", "demo"
    )
    _init_project(managed)
    _init_project(
        os.path.join(home, ".calkit", "workspaces", "other.hub", "bob", "x")
    )
    cfg = {"workspaces": [elsewhere, elsewhere + "/"]}
    workspaces = {
        Path(os.path.relpath(w["path"], os.path.realpath(home))).as_posix(): w
        for w in operator.discover_workspaces(cfg)
    }
    assert set(workspaces) == {
        "calkit/demo",
        "dev/tool",
        "src/other",
        ".calkit/workspaces/calkit.io/alice/demo",
    }
    demo = workspaces["calkit/demo"]
    assert demo["kind"] == "personal"
    assert demo["project"] == "alice/demo"
    assert demo["dirty"]
    assert len(demo["commit"]) == 40
    assert demo["last_activity"] is not None
    assert workspaces["dev/tool"]["last_activity"] is not None
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


@pytest.mark.skipif(sys.platform == "win32", reason="Agents are POSIX here")
def test_agents(tmp_path, monkeypatch):
    home = os.path.realpath(tmp_path)
    monkeypatch.setenv("CALKIT_USER_HOME", home)
    wdir = os.path.join(home, "calkit", "demo")
    _init_project(wdir)
    other = os.path.join(home, "calkit", "other")
    _init_project(other, name="other")
    os.makedirs(os.path.join(wdir, "src"))
    # Stand-ins for agents, which are found by their command, from Python
    # rather than, e.g., sleep, since macOS hides its own programs'
    # environments
    bin_dir = os.path.join(home, "bin")
    os.makedirs(bin_dir)
    for tool in ["claude", "codex", "not-an-agent"]:
        os.symlink(
            os.path.realpath(sys.executable), os.path.join(bin_dir, tool)
        )
    pids = []

    def start(tool, cwd, env=None):
        # Through a shell that exits, as an editor's terminal might, rather
        # than as a child of this process, which would make it a session's
        out = subprocess.run(
            [
                "sh",
                "-c",
                f'"{bin_dir}/{tool}" -c "import time; time.sleep(60)" '
                ">/dev/null 2>&1 & echo $!",
            ],
            cwd=cwd,
            env=dict(os.environ, **(env or {})),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        pids.append(int(out))
        return pids[-1]

    try:
        claude = start("claude", os.path.join(wdir, "src"))
        codex = start(
            "codex",
            wdir,
            {"TMUX": "/tmp/tmux-1/default,1,0", "TMUX_PANE": "%3"},
        )
        start("not-an-agent", wdir)
        start("claude", home)
        # Claude Code's record of the process names its conversation
        sessions_dir = os.path.join(home, ".claude", "sessions")
        os.makedirs(sessions_dir)
        claude_cwd = os.path.join(wdir, "src")
        with open(os.path.join(sessions_dir, f"{claude}.json"), "w") as f:
            json.dump(
                {
                    "sessionId": "abc",
                    "cwd": claude_cwd,
                    "name": "Fix plots",
                    "status": "busy",
                },
                f,
            )
        found = operator.find_agents([wdir, other])
        assert set(found) == {wdir}
        agents = {a["tool"]: a for a in found[wdir]}
        assert set(agents) == {"claude", "codex"}
        assert agents["claude"]["pid"] == claude
        assert agents["claude"]["name"] == "Fix plots"
        assert agents["claude"]["status"] == "busy"
        assert agents["claude"]["where"] == "terminal"
        assert agents["claude"]["tmux"] is None
        assert agents["codex"]["where"] == "tmux"
        assert agents["codex"]["tmux"] == {
            "socket": "/tmp/tmux-1/default",
            "pane": "%3",
        }
        # Only ones in tmux can be attached to, and only in their workspace
        op = operator.Operator({"workspaces": []})
        op.workspaces = [{"path": wdir, "kind": "personal"}]
        with pytest.raises(ValueError, match="tmux"):
            op.open_session(wdir, 80, 24, attach=claude)
        with pytest.raises(ValueError):
            operator.get_agent_log(other, claude)
        # Their conversations are read from the logs they keep, ending with
        # the latest, leaving out what isn't said or done
        transcript = os.path.join(
            home,
            ".claude",
            "projects",
            claude_cwd.replace("/", "-").replace(".", "-").replace("_", "-"),
            "abc.jsonl",
        )
        os.makedirs(os.path.dirname(transcript))
        lines = [
            {"type": "user", "timestamp": "t1", "message": {"content": "Hi"}},
            {"type": "mode", "mode": "normal"},
            {
                "type": "assistant",
                "timestamp": "t2",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "Hmm"},
                        {"type": "text", "text": "Plotting"},
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"description": "Run the plots"},
                        },
                    ]
                },
            },
        ]
        with open(transcript, "w") as f:
            f.write("".join(json.dumps(line) + "\n" for line in lines))
        log = operator.get_agent_log(wdir, claude)
        assert log["entries"] == [
            {"role": "user", "text": "Hi", "time": "t1"},
            {"role": "assistant", "text": "Plotting", "time": "t2"},
            {"role": "tool", "text": "Bash: Run the plots", "time": "t2"},
        ]
        assert operator.get_agent_log(wdir, claude, limit=1)["entries"] == [
            {"role": "tool", "text": "Bash: Run the plots", "time": "t2"}
        ]
        # Codex's are found by where they were started
        rollouts = os.path.join(home, ".codex", "sessions", "2026", "10")
        os.makedirs(rollouts)
        for name, cwd, said in [
            ("a", other, "Elsewhere"),
            ("b", wdir, "Done"),
        ]:
            with open(os.path.join(rollouts, f"{name}.jsonl"), "w") as f:
                for line in [
                    {"type": "session_meta", "payload": {"cwd": cwd}},
                    {
                        "type": "response_item",
                        "timestamp": "t3",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "<env>x</env>"},
                                {"type": "input_text", "text": "Go"},
                            ],
                        },
                    },
                    {
                        "type": "response_item",
                        "timestamp": "t4",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": said}],
                        },
                    },
                ]:
                    f.write(json.dumps(line) + "\n")
        assert operator.get_agent_log(wdir, codex)["entries"] == [
            {"role": "user", "text": "Go", "time": "t3"},
            {"role": "assistant", "text": "Done", "time": "t4"},
        ]
        # The hub hears about them at check-in, without what's only for
        # attaching or reading their logs
        demo = next(
            ws
            for ws in operator.discover_workspaces({"workspaces": []})
            if ws["path"] == wdir
        )
        assert sorted(a["tool"] for a in demo["agents"]) == ["claude", "codex"]
        assert all("tmux" not in a and "cwd" not in a for a in demo["agents"])
    finally:
        for pid in pids:
            try:
                os.kill(pid, 15)
            except OSError:
                pass


@pytest.mark.skipif(sys.platform == "win32", reason="Sessions need a PTY")
@pytest.mark.asyncio
async def test_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    monkeypatch.setenv("SHELL", "/bin/sh")
    # The Operator points its own requests at its hub, which commands in
    # sessions don't inherit, so they use the project's
    monkeypatch.setattr(operator, "_inherited_hub", None)
    monkeypatch.setenv("CALKIT_HUB", "http://localhost")
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

    # Messages go out unescaped, since escaping a TUI's box drawing makes
    # each character up to 12 bytes, which can pass the relay's limit
    class FakeSocket:
        def __init__(self):
            self.sent: list[str] = []

        async def send(self, text):
            self.sent.append(text)

    op.ws = FakeSocket()
    await operator.Operator.send(op, "x", {"data": "───"})
    assert op.ws.sent == ['{"ch": "x", "msg": {"data": "───"}}']
    op.ws = None
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
    # Opening a session takes the workspace from other hubs' Operators
    assert operator.workspace_lock_holder(workspace)["pid"] == os.getpid()
    message(
        "a",
        {
            "type": "sessions.input",
            "session": sid,
            "data": "echo HI-$((6*7))-${CALKIT_HUB:-none}\n",
        },
    )
    await wait_for(lambda: "HI-42-none" in output("a"))
    # Input the terminal can't take at once, e.g., a long paste, all arrives
    paste = ("true " + "x" * 64 + "\n") * 300 + "echo PASTED-$((2*3))\n"
    message("a", {"type": "sessions.input", "session": sid, "data": paste})
    await wait_for(lambda: "PASTED-6" in output("a"), timeout=30)
    # A second channel attaching gets the scrollback replayed
    op.on_relay_message({"type": "channel.open", "ch": "b", "grant": grant()})
    message("b", {"type": "sessions.attach", "id": 4, "session": sid})
    await wait_for(lambda: "HI-42" in output("b"))
    # Marked, so the browser doesn't answer queries in it a second time
    outputs = [(c, m) for c, m in sent if m["type"] == "sessions.output"]
    assert all(m.get("replay") for c, m in outputs if c == "b")
    assert not any(
        m.get("replay") for c, m in outputs if c == "a" and "HI" in m["data"]
    )
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
        "--hub",
        "https://calkit.io",
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
    # The whole command has its own quotes, since cmd strips the outer pair
    # of one with more than two (doubled here, for VBScript)
    assert 'cmd /c ""' in script and '2>&1"""' in script
    unit = operator._systemd_unit()
    assert f"ExecStart={shlex.join(command)}" in unit
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit
    # Restarting a loaded launchd agent happens in place, since booting it
    # out returns before it has stopped, so booting it in again fails;
    # one that isn't loaded is started
    calls: list[list[str]] = []
    loaded = [True]

    def run(cmd, **kwargs):
        calls.append(cmd)
        code = 0 if cmd[:2] != ["launchctl", "print"] or loaded[0] else 113
        return subprocess.CompletedProcess(cmd, code)

    monkeypatch.setattr(operator.subprocess, "run", run)
    monkeypatch.setattr(operator.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(operator.platform, "system", lambda: "Darwin")
    agent_path = operator._launchd_plist_path(at_boot=False)
    os.makedirs(os.path.dirname(agent_path))
    Path(agent_path).write_bytes(operator._launchd_plist(at_boot=False))
    target = f"gui/501/{operator.service_label()}"
    for is_loaded, last in [
        (True, ["launchctl", "kickstart", "-k", target]),
        (False, ["launchctl", "bootstrap", "gui/501", agent_path]),
    ]:
        loaded[0] = is_loaded
        calls.clear()
        operator.restart_service()
        assert calls == [["launchctl", "print", target], last]
    # systemd restarts in one step too
    monkeypatch.setattr(operator.platform, "system", lambda: "Linux")
    unit_path = operator._systemd_unit_path()
    os.makedirs(os.path.dirname(unit_path))
    Path(unit_path).write_text(unit)
    calls.clear()
    operator.restart_service()
    assert calls == [
        ["systemctl", "--user", "restart", operator.systemd_unit()]
    ]


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
    ours = [line for line in lines if line.endswith(operator.cron_marker())]
    assert [line.split()[0] for line in ours] == ["*/5", "@reboot"]
    assert all("--mode cron" in line for line in ours)
    assert all(operator.get_log_path() in line for line in ours)
    assert "cron" in operator.get_service_status()
    operator.uninstall_service()
    assert table.read_text().splitlines() == ["0 * * * * echo mine"]
    assert operator.get_service_status() is None
    # In cron mode, starting checks in now and stopping ends the running one
    started, stopped = [], []
    with monkeypatch.context() as m:
        m.setattr(operator, "_cron_installed", lambda: True)
        m.setattr(
            operator.subprocess,
            "Popen",
            lambda argv, **kw: started.append(argv),
        )
        m.setattr(
            operator, "_stop_running_operator", lambda: stopped.append(True)
        )
        m.setattr(operator.platform, "system", lambda: "Linux")
        operator.set_service_running(True)
        operator.set_service_running(False)
    assert started == [operator._service_command("cron")]
    assert stopped == [True]
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
    # The Git part on its own says the same, without the pipeline's wait
    git_status = operator.get_workspace_git_status(wdir, fetch=False)
    assert git_status["git"] == {
        k: git[k]
        for k in ["branch", "changed_files", "staged_files", "untracked_files"]
    }
    assert git_status["commits_ahead"] == 0
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

    # A refusal over an object that's already there leaves nothing behind
    ck_info = calkit.load_calkit_info(wdir=wdir)
    ck_info["figures"].append({"path": "drawn.png", "title": "By hand"})
    with open(os.path.join(wdir, "calkit.yaml"), "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.run(
        ["git", "commit", "-qam", "Add figure"], cwd=wdir, check=True
    )
    with pytest.raises(ValueError):
        operator.add_stage(
            wdir,
            name="draw",
            cmd="echo",
            outs=["drawn.png"],
            calkit_type="figure",
            calkit_object={"title": "Again"},
        )
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=wdir)
    assert staged.returncode == 0
    assert "draw" not in open(os.path.join(wdir, "dvc.yaml")).read()
    ck_info["figures"].pop()
    with open(os.path.join(wdir, "calkit.yaml"), "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.run(
        ["git", "commit", "-qam", "Drop figure"], cwd=wdir, check=True
    )

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
    assert result["ok"] is False
    assert result["output"]
    # Single stages can be run, and their names can't be options
    result = operator.run_pipeline(wdir, stages=["plot"])
    assert result["ok"] is False and "plot" in result["output"]
    for bad in ["--force", "-f", "a b", "x;y", ""]:
        with pytest.raises(ValueError):
            operator.run_pipeline(wdir, stages=[bad])
    # The hub follows a run through its log, named by when it started
    run_log = operator.get_run_log(wdir)
    assert run_log["name"].endswith(".log") and "plot" in run_log["log"]
    # Stopping needs a run in progress, and a run the hub started stops
    # with everything it started
    with pytest.raises(ValueError):
        operator.stop_run(wdir)
    if sys.platform != "win32":
        sleeper = subprocess.Popen(["sleep", "30"], start_new_session=True)
        operator._runs[wdir] = sleeper
        try:
            operator.stop_run(wdir)
            assert sleeper.wait(timeout=10) != 0
        finally:
            operator._runs.pop(wdir, None)
    # Another workspace for the project goes beside it in ~/calkit, where
    # it's found, and branch names can't be options or climb out of there
    created = operator.new_workspace(wdir, "fix/axes")
    assert created["path"] == os.path.join(tmp_path, "calkit", "demo-fix-axes")
    assert created["path"] in [
        ws["path"] for ws in operator.discover_workspaces({"workspaces": []})
    ]
    for bad in ["--force", "-b", "../up", "a b", ""]:
        with pytest.raises(ValueError):
            operator.new_workspace(wdir, bad)
    # One from a worktree is named after the main checkout
    wt = os.path.join(tmp_path, "dev", "demo-wt")
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "wt", wt], cwd=wdir, check=True
    )
    created = operator.new_workspace(wt, "from-wt")
    assert created["path"] == os.path.join(tmp_path, "calkit", "demo-from-wt")
    # A calkit package in the workspace, e.g., in a checkout of Calkit
    # itself, doesn't stand in for the Operator's own
    os.makedirs(os.path.join(wt, "calkit"))
    with open(os.path.join(wt, "calkit", "__init__.py"), "w") as f:
        f.write("raise SystemExit('shadowed')\n")
    operator._calkit(["--version"], wt)
    # One from ~/dev goes beside it, and one from elsewhere in ~/calkit
    calls: list[list[str]] = []
    with monkeypatch.context() as m:
        m.setattr(operator, "_calkit", lambda args, wdir: calls.append(args))
        for source, parent in [
            (os.path.join(tmp_path, "dev", "tool"), "dev"),
            (os.path.join(tmp_path, "src", "tool"), "calkit"),
        ]:
            made = operator.new_workspace(source, "x")
            assert made["path"] == os.path.join(
                os.path.realpath(tmp_path), parent, "tool-x"
            )
            assert calls[-1][-1] == made["path"]
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
    result = operator.discard_changes(wdir)
    with open(os.path.join(wdir, "notes.txt")) as f:
        assert f.read() == "hi"
    with open(os.path.join(wdir, "big.csv")) as f:
        assert f.read() == "1,2\n"
    # What was discarded comes back with calkit stash pop, data included,
    # since it was committed to DVC's cache before being stashed
    assert result == {"stashed": True}
    subprocess.run(
        [sys.executable, "-m", "calkit", "stash", "pop"], cwd=wdir, check=True
    )
    with open(os.path.join(wdir, "notes.txt")) as f:
        assert f.read() == "changed"
    with open(os.path.join(wdir, "big.csv")) as f:
        assert f.read() == "3,4\n"
    # Discarding again, and with nothing to discard, nothing is stashed
    assert operator.discard_changes(wdir) == {"stashed": True}
    with open(os.path.join(wdir, "big.csv")) as f:
        assert f.read() == "1,2\n"
    assert operator.discard_changes(wdir) == {"stashed": False}
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

    # Stages are listed in order with their state and the questions resting
    # on them, as evidence or upstream of it, matched through their paths,
    # including matrix ones, known only up to their template
    pipeline_dir = os.path.join(tmp_path, "pipeline")
    os.makedirs(pipeline_dir)
    with open(os.path.join(pipeline_dir, "dvc.yaml"), "w") as f:
        json.dump(
            {
                "stages": {
                    "fetch": {"cmd": "x", "outs": ["data/raw"]},
                    "sim": {
                        "matrix": {"case": ["a", "b"]},
                        "cmd": "x",
                        "deps": ["data/raw/mesh.csv"],
                        "outs": ["results/${item.case}/out.csv"],
                    },
                    "plot": {
                        "cmd": "x",
                        "deps": ["results", {"plot.py": {}}],
                        "outs": [{"fig.png": {"cache": False}}],
                    },
                    "other": {"cmd": "x", "outs": ["other.txt"]},
                }
            },
            f,
        )
    with open(os.path.join(pipeline_dir, "calkit.yaml"), "w") as f:
        f.write("pipeline:\n  stages:\n    plot:\n      kind: python-script\n")
    stages = operator.get_stage_list(
        pipeline_dir,
        {
            "pipeline": {
                "stale_stage_names": ["sim@b", "plot"],
                "running_stages": ["sim@a"],
            },
            "questions": {
                "questions": [
                    {"index": 1, "evidence": [{"stage": "plot"}]},
                    {"index": 2, "evidence": [{"stage": "sim@a"}, {}]},
                ]
            },
        },
    )
    assert stages == [
        {
            "name": "fetch",
            "kind": None,
            "state": "ok",
            "questions": [],
            "feeds_questions": [1, 2],
        },
        {
            "name": "sim",
            "kind": None,
            "state": "running",
            "questions": [2],
            "feeds_questions": [1],
        },
        {
            "name": "plot",
            "kind": "python-script",
            "state": "stale",
            "questions": [1],
            "feeds_questions": [],
        },
        {
            "name": "other",
            "kind": None,
            "state": "ok",
            "questions": [],
            "feeds_questions": [],
        },
    ]
    assert operator.get_stage_list(str(tmp_path), None) == []

    # Pulling only fast-forwards unless asked to merge, which is undone if
    # it conflicts
    def git(*args, cwd=wdir):
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        ).stdout

    remote = os.path.join(tmp_path, "remote.git")
    other = os.path.join(tmp_path, "other-clone")
    git("clone", "-q", "--bare", wdir, remote)
    git("remote", "add", "origin", remote)
    git("fetch", "-q", "origin")
    git("branch", "-u", f"origin/{git('branch', '--show-current').strip()}")
    git("clone", "-q", remote, other)

    def commit(path, text, cwd):
        with open(os.path.join(cwd, path), "w") as f:
            f.write(text)
        git("add", path, cwd=cwd)
        git("commit", "-qm", f"Change {path}", cwd=cwd)

    commit("a.txt", "a", other)
    git("push", "-q", cwd=other)
    assert operator.pull_workspace(wdir) == {"diverged": False}
    assert os.path.isfile(os.path.join(wdir, "a.txt"))
    commit("b.txt", "b", other)
    git("push", "-q", cwd=other)
    commit("c.txt", "c", wdir)
    assert operator.pull_workspace(wdir) == {"diverged": True}
    assert not os.path.isfile(os.path.join(wdir, "b.txt"))
    assert operator.pull_workspace(wdir, merge=True) == {"diverged": False}
    assert os.path.isfile(os.path.join(wdir, "b.txt"))
    commit("notes.txt", "theirs", other)
    git("push", "-q", cwd=other)
    commit("notes.txt", "ours", wdir)
    with pytest.raises(ValueError, match="notes.txt"):
        operator.pull_workspace(wdir, merge=True)
    assert not os.path.isfile(os.path.join(wdir, ".git", "MERGE_HEAD"))
    with open(os.path.join(wdir, "notes.txt")) as f:
        assert f.read() == "ours"
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
    # The user's active Operators, as the hub lists them
    active = []

    def request(kind, path, json=None, **kwargs):
        if kind == "get":
            return active
        posted.update(json)
        active.append({"id": "op1"})
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
        if "cat ~/.calkit/operators/calkit.io/config.yaml 2>" in argv[-1]:
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
    assert (
        "calkit operator install --hub https://calkit.io --cron"
        in install_argv[-1]
    )
    # It goes where the other machine keeps this hub's Operator
    assert "~/.calkit/operators/calkit.io/config.yaml" in write_argv[-1]
    # Reinstalling keeps the Operator already there
    remote_config["text"] = config_text
    posted.clear()
    runs.clear()
    assert operator.install_remote("cluster") == cfg
    assert posted == {}
    assert len(runs) == 2
    # One that was revoked is registered again rather than kept, since it
    # would exit at its first check-in
    active.clear()
    runs.clear()
    operator.install_remote("cluster")
    assert posted["hostname"] == "login1.cluster"
    assert len(runs) == 3
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


def test_hubs(tmp_path, monkeypatch):
    import yaml

    home = str(tmp_path)
    monkeypatch.setenv("CALKIT_USER_HOME", home)
    # A config from before Operators were kept per hub moves to its hub's
    # place
    legacy = tmp_path / ".calkit" / "operator.yaml"
    legacy.parent.mkdir()
    legacy.write_text(
        yaml.safe_dump({"name": "box", "api_url": "https://api.calkit.io"})
    )
    assert operator.list_configured_hubs() == ["https://calkit.io"]
    assert not legacy.exists()
    assert operator.load_config()["name"] == "box"
    # Each hub's Operator has its own config, service, lock, and log, keyed
    # like its managed workspaces, so they can run side by side
    monkeypatch.setenv("CALKIT_HUB", "https://calkit.io")
    keys = {}
    for url in ["https://calkit.io", "localhost", "http://localhost:5173"]:
        keys[url] = operator.select_hub(url)
        operator.save_config({"name": url, "hub_url": operator.get_hub_url()})
    assert keys == {
        "https://calkit.io": "calkit.io",
        "localhost": "localhost",
        "http://localhost:5173": "localhost-5173",
    }
    assert sorted(operator.list_configured_hubs()) == [
        "http://localhost",
        "http://localhost:5173",
        "https://calkit.io",
    ]
    names = set()
    for url in keys:
        operator.select_hub(url)
        assert operator.load_config()["name"] == url
        names.add(
            (
                operator.get_config_path(),
                operator.get_log_path(),
                operator._pid_path(),
                operator.service_label(),
                operator.systemd_unit(),
                operator.cron_marker(),
                operator._windows_startup_path(),
            )
        )
    assert len(names) == 3
    assert len({n for group in names for n in group}) == 21
    # One hub's cron entries are never taken for another's, even when one
    # key starts with the other
    operator.select_hub("localhost")
    lines = [f"* * * * * x {operator.cron_marker(k)}" for k in keys.values()]
    lines.append(f"* * * * * x {operator.cron_marker('')}")
    assert [
        line for line in lines if line.endswith(operator.cron_marker())
    ] == ["* * * * * x # calkit-operator localhost"]
    # The empty key gives the names used before, for removing them
    assert operator.service_label("") == "io.calkit.operator"
    assert operator.systemd_unit("") == "calkit-operator.service"


def test_workspace_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    wdir = os.path.join(tmp_path, "calkit", "demo")
    _init_project(wdir)
    # An Operator takes a workspace while using it, in a lock inside the
    # workspace that Git ignores, and can take it again
    operator.claim_workspace(wdir)
    operator.claim_workspace(wdir)
    holder = operator.workspace_lock_holder(wdir)
    assert holder["pid"] == os.getpid()
    assert holder["hub"] == "https://calkit.io"
    with open(os.path.join(wdir, ".calkit", "local", ".gitignore")) as f:
        assert f.read() == "*\n"
    operator.release_workspace(wdir)
    assert operator.workspace_lock_holder(wdir) is None
    # Another hub's Operator using it keeps this one out, and shows on the
    # hub, until it stops, which leaves a stale lock anyone can take
    other = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", "operator"]
    )
    try:
        with open(
            os.path.join(wdir, ".calkit", "local", "operator.lock"), "w"
        ) as f:
            json.dump({"hub": "http://localhost", "pid": other.pid}, f)
        with pytest.raises(ValueError, match="http://localhost"):
            operator.claim_workspace(wdir)
        (ws,) = [
            w
            for w in operator.discover_workspaces({})
            if w["path"] == os.path.realpath(wdir)
        ]
        assert ws["in_use_by"] == "http://localhost"
    finally:
        other.kill()
        other.wait()
    operator.claim_workspace(wdir)
    assert operator.workspace_lock_holder(wdir)["pid"] == os.getpid()
    operator.release_workspace(wdir)


@pytest.mark.asyncio
async def test_relay_connection(monkeypatch):
    import websockets.asyncio.client

    sent = []

    class FakeSocket:
        async def send(self, text):
            sent.append(json.loads(text))

        def __aiter__(self):
            return self

        async def __anext__(self):
            # Open for a moment, as a real connection waits for messages
            await asyncio.sleep(0.05)
            raise StopAsyncIteration

    class FakeConnect:
        def __init__(self, url, **kwargs):
            self.url = url

        async def __aenter__(self):
            return FakeSocket()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(websockets.asyncio.client, "connect", FakeConnect)
    op = operator.Operator({"name": "box", "workspaces": []})
    check_ins = []

    async def check_in():
        check_ins.append(op.ws is not None)
        return {}

    monkeypatch.setattr(op, "check_in", check_in)
    await op.connect({"relay_url": "wss://relay.hub", "relay_token": "tok"})
    await op.connected_check_in
    # The token goes in the first message, and the Operator checks in as
    # connected right away, so the hub doesn't show it offline until the
    # next regular check-in
    assert sent == [{"type": "auth", "token": "tok"}]
    assert check_ins == [True]


def test_restarts(tmp_path, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    monkeypatch.setattr(operator, "RESTART_CHECK_SECONDS", 0.01)
    monkeypatch.setattr(operator.calkit, "__version__", "1.0.0")
    installed = ["1.0.0"]
    monkeypatch.setattr(
        operator, "get_installed_version", lambda: installed[0]
    )
    op = operator.Operator({"name": "box", "workspaces": []})
    assert not op.restart_pending()
    # A new version installed under it, e.g., by an automatic upgrade
    installed[0] = "1.1.0"
    assert op.restart_pending()
    installed[0] = "1.0.0"
    # A request from 'calkit upgrade' is read once
    pids = {"calkit.io": 123, "other.hub": None}
    for key in pids:
        os.makedirs(operator.operator_dir(key))
    monkeypatch.setattr(
        operator, "get_running_pid", lambda key=None: pids[key]
    )
    assert operator.request_restarts() == [("calkit.io", 123)]
    assert not os.path.exists(operator._restart_request_path("other.hub"))
    assert op.restart_pending()
    assert not os.path.exists(operator._restart_request_path())
    assert op.restart_requested and not op.stop_requested
    # As is one from the hub, which comes with a check-in
    op.restart_requested = False
    assert not op.restart_pending()
    reported: list[bool] = []

    def check_in(cfg, workspaces, mode, connected, pending) -> dict:
        reported.append(pending)
        return {"restart": True}

    monkeypatch.setattr(operator, "discover_workspaces", lambda cfg: [])
    monkeypatch.setattr(operator, "check_in", check_in)
    asyncio.run(op.check_in())
    assert op.restart_requested
    asyncio.run(op.check_in())
    assert reported == [False, True]

    # It waits until no session or run is using it
    async def wait_for_idle() -> None:
        op.sessions["s"] = cast(Any, SimpleNamespace(workspace="/ws"))
        op.workspace_actions["/ws"] = "workspace.run"
        waiting = asyncio.create_task(op.wait_to_restart())
        await asyncio.sleep(0.05)
        assert not waiting.done()
        op.sessions.clear()
        await asyncio.sleep(0.05)
        assert not waiting.done()
        op.workspace_actions.clear()
        await asyncio.wait_for(waiting, 1)
        assert op.restarting
        # Asked to stop, e.g., so an upgrade can replace its files on Windows,
        # it doesn't start again
        stopping = operator.Operator({"name": "box", "workspaces": []})
        operator.request_restarts(stop=True)
        await asyncio.wait_for(stopping.wait_to_restart(), 1)
        assert stopping.stop_requested and not stopping.restarting

    asyncio.run(wait_for_idle())
    # Restarting replaces the process with one running the same way
    execs = []
    monkeypatch.setattr(operator.os, "execv", lambda *a: execs.append(a))
    monkeypatch.setattr(operator.sys, "platform", "linux")
    operator.restart_process("service")
    cmd = operator._service_command("service")
    assert execs == [(cmd[0], cmd)]
    # Run restarts once its Operator stops for one, and drops requests left
    # from before it started
    restarts: list[str] = []
    monkeypatch.setattr(operator, "restart_process", restarts.append)

    async def stop_to_restart(self) -> None:
        self.restarting = True

    monkeypatch.setattr(operator.Operator, "run", stop_to_restart)
    # Left alone, so SIGTERM still ends the tests that follow
    monkeypatch.setattr("signal.signal", lambda *args: None)
    operator.request_restarts()
    assert operator.run({"name": "box", "workspaces": []}, mode="service")
    assert restarts == ["service"]
    assert not os.path.exists(operator._restart_request_path())
