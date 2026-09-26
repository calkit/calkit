"""Tests for ``calkit.operator``."""

import asyncio
import os
import stat
import subprocess
import sys

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
    # The config holds a token, so only the user can read it
    operator.save_config({"name": "box", "token": "cko_x", "workspaces": []})
    if sys.platform != "win32":
        mode = stat.S_IMODE(os.stat(operator.get_config_path()).st_mode)
        assert mode == 0o600
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
        os.path.relpath(w["path"], os.path.realpath(home)): w
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


@pytest.mark.skipif(sys.platform == "win32", reason="Sessions need a PTY")
@pytest.mark.asyncio
async def test_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    monkeypatch.setenv("SHELL", "/bin/sh")
    _init_project(os.path.join(tmp_path, "calkit", "demo"))
    op = operator.Operator({"user_id": "owner", "workspaces": []})
    op.workspaces = operator.discover_workspaces(op.cfg)
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

    # Channels for anyone but the owner are refused
    op.on_relay_message({"type": "channel.open", "ch": "x", "user_id": "eve"})
    message("x", {"type": "sessions.list", "id": 1})
    await asyncio.sleep(0.1)
    assert sent == []
    op.on_relay_message(
        {"type": "channel.open", "ch": "a", "user_id": "owner"}
    )
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
    op.on_relay_message(
        {"type": "channel.open", "ch": "b", "user_id": "owner"}
    )
    message("b", {"type": "sessions.attach", "id": 4, "session": sid})
    await wait_for(lambda: "HI-42" in output("b"))
    # Sessions outlive the channels attached to them
    op.on_relay_message({"type": "channel.close", "ch": "a"})
    op.on_relay_message({"type": "channel.close", "ch": "b"})
    assert op.sessions[sid].channels == set()
    op.on_relay_message(
        {"type": "channel.open", "ch": "c", "user_id": "owner"}
    )
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
    # At boot it's a system daemon that still runs as this user
    daemon = plistlib.loads(operator._launchd_plist(at_boot=True))
    assert daemon["UserName"]
    assert operator._launchd_plist_path(at_boot=True).startswith(
        "/Library/LaunchDaemons/"
    )
    unit = operator._systemd_unit()
    assert (
        f"ExecStart={sys.executable} -m calkit operator start --mode service"
        in unit
    )
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
    assert operator.get_service_status().startswith("cron")
    operator.uninstall_service()
    assert table.read_text().splitlines() == ["0 * * * * echo mine"]
    assert operator.get_service_status() is None
    # Only one Operator runs at a time
    lock = operator.acquire_lock()
    assert lock is not None
    assert operator.acquire_lock() is None
    lock.close()
    second = operator.acquire_lock()
    assert second is not None
    second.close()
