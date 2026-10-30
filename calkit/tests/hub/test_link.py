"""Tests for ``calkit.hub_link``."""

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

from calkit.hub import link as hub_link


@pytest.fixture(autouse=True)
def _hub(monkeypatch):
    # Each test acts on one hub's link unless it chooses another
    monkeypatch.setattr(hub_link, "_hub_url", "https://calkit.io")


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
    hub_link.save_config({"name": "box", "token": "ckm_x", "workspaces": []})
    if sys.platform != "win32":
        os.chmod(hub_link.get_config_path(), 0o644)
        hub_link.save_config(
            {"name": "box", "token": "ckm_x", "workspaces": []}
        )
        mode = stat.S_IMODE(os.stat(hub_link.get_config_path()).st_mode)
        assert mode == 0o600
    # Only encrypted connections are made, except locally
    for url in [
        "https://api.calkit.io",
        "wss://relay.calkit.io",
        "http://api.localhost",
        "ws://localhost:8002",
    ]:
        hub_link.check_secure_url(url)
    for url in ["http://api.calkit.io", "ws://relay.calkit.io", "ftp://x"]:
        with pytest.raises(ValueError):
            hub_link.check_secure_url(url)
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
    assert hub_link.use_own_hub() == "https://api.calkit.io"
    monkeypatch.setenv("CALKIT_HUB", "http://hub.example")
    with pytest.raises(ValueError):
        hub_link.use_own_hub()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CALKIT_ENV", "test")
    assert hub_link.load_config() == {
        "name": "box",
        "token": "ckm_x",
        "workspaces": [],
    }
    # Projects under ~/calkit and ~/dev are found; other folders there are
    # not
    _init_project(os.path.join(home, "calkit", "demo"))
    _init_project(os.path.join(home, "dev", "tool"), name="tool")
    # A project's name is whatever its repo says, so only ones the hub could
    # have are reported
    _init_project(os.path.join(home, "dev", "odd"), owner="a b", name="c")
    # Nor does looking at one run anything its own Git config says, e.g.,
    # in one unpacked from an archive rather than cloned
    ran = os.path.join(home, "ran")
    if sys.platform != "win32":
        hook = os.path.join(home, "fsmonitor.sh")
        with open(hook, "w") as f:
            f.write(f"#!/bin/sh\ntouch {shlex.quote(ran)}\n")
        os.chmod(hook, 0o755)
        subprocess.run(
            ["git", "config", "core.fsmonitor", hook],
            cwd=os.path.join(home, "dev", "odd"),
            check=True,
        )
    os.makedirs(os.path.join(home, "dev", "not-calkit"))
    os.makedirs(os.path.join(home, "calkit", "not-a-project"))
    with open(os.path.join(home, "calkit", "demo", "notes.txt"), "w") as f:
        f.write("uncommitted")
    # The hub's grant key, which comes over HTTPS, is the one grants are
    # checked with, so a new one replaces the old
    from requests.exceptions import HTTPError

    from calkit.hub import core as hub

    keys = iter(["key1", "key2"])
    posted = []

    def request(*args: Any, **kwargs: Any) -> dict:
        posted.append(kwargs["json"])
        return {"grant_public_key": next(keys)}

    monkeypatch.setattr(hub, "_request", request)
    cfg = {"token": "ckm_x", "api_url": "https://api.hub", "workspaces": []}
    hub_link.check_in(cfg, [], "service")
    assert (hub_link.load_config() or {})["grant_public_key"] == "key1"
    hub_link.check_in(cfg, [], "service")
    assert (hub_link.load_config() or {})["grant_public_key"] == "key2"
    # The link's own public key goes with each, which the hub keeps
    # the first time, for browsers to check replies with
    assert posted[0]["public_key"] == hub_link.get_link_public_jwk()
    assert posted[1]["public_key"] == posted[0]["public_key"]
    # A hub that has another key for it is refused, and installing again
    # registers it anew
    response = SimpleNamespace(status_code=409)

    def conflict(*args: Any, **kwargs: Any) -> dict:
        raise HTTPError("409: Machine key doesn't match", response=response)

    monkeypatch.setattr(hub, "_request", conflict)
    with pytest.raises(hub_link.LinkKeyRejected):
        hub_link.check_in(cfg, [], "service")
    assert (hub_link.load_config() or {})["key_rejected"]
    # Revoked, it stops
    response.status_code = 403
    with pytest.raises(hub_link.LinkRevoked) as revoked:
        hub_link.check_in(cfg, [], "service")
    assert not isinstance(revoked.value, hub_link.LinkKeyRejected)
    # Registered projects elsewhere are found, but only once
    elsewhere = os.path.join(home, "src", "other")
    _init_project(elsewhere, name="other")
    # Managed workspaces are found under <hub>/<owner>/<name>, only for
    # this link's hub
    managed = os.path.join(
        home, ".calkit", "workspaces", "calkit.io", "alice", "demo"
    )
    _init_project(managed)
    _init_project(
        os.path.join(home, ".calkit", "workspaces", "other.hub", "bob", "x")
    )
    # Projects on other hubs aren't, unless added
    other_hub = os.path.join(home, "dev", "other-hub")
    _init_project(other_hub, name="other-hub")
    with open(os.path.join(other_hub, "calkit.yaml"), "a") as f:
        f.write("hub: https://hub.example\n")
    this_hub = os.path.join(home, "dev", "this-hub")
    _init_project(this_hub, name="this-hub")
    with open(os.path.join(this_hub, "calkit.yaml"), "a") as f:
        f.write("hub: calkit.io\n")
    # A fork is named for the hub project its data goes to, though its
    # calkit.yaml and origin may name the one it was forked from
    os.makedirs(os.path.join(this_hub, ".dvc"))
    with open(os.path.join(this_hub, ".dvc", "config"), "w") as f:
        f.write(
            "[core]\n    remote = calkit\n"
            "['remote \"calkit\"']\n    url = ck://bob/upstream\n"
            "['remote \"mine\"']\n    url = ck://carol/fork\n"
        )
    with open(os.path.join(this_hub, ".dvc", "config.local"), "w") as f:
        f.write("[core]\n    remote = mine\n")
    cfg = {"workspaces": [elsewhere, elsewhere + "/"]}
    workspaces = {
        Path(os.path.relpath(w["path"], os.path.realpath(home))).as_posix(): w
        for w in hub_link.discover_workspaces(cfg)
    }
    assert set(workspaces) == {
        "calkit/demo",
        "dev/tool",
        "dev/odd",
        "dev/this-hub",
        "src/other",
        ".calkit/workspaces/calkit.io/alice/demo",
    }
    found = hub_link.discover_workspaces({"workspaces": [other_hub]})
    assert os.path.realpath(other_hub) in [w["path"] for w in found]
    # Ones that don't say are on the user's default hub
    monkeypatch.setattr(config, "_get_default_hub", lambda: "hub.example")
    found = [
        os.path.relpath(w["path"], os.path.realpath(home))
        for w in hub_link.discover_workspaces({"workspaces": []})
    ]
    assert sorted(found) == [
        os.path.join(".calkit", "workspaces", "calkit.io", "alice", "demo"),
        os.path.join("dev", "this-hub"),
    ]
    monkeypatch.setattr(config, "_get_default_hub", lambda: None)
    # A hub is known by its API, which some hubs serve at more than one URL
    local = os.path.join(home, "dev", "local")
    _init_project(local, name="local")
    with open(os.path.join(local, "calkit.yaml"), "a") as f:
        f.write("hub: localhost:5173\n")
    monkeypatch.setattr(hub_link, "_hub_url", "http://localhost")
    found = hub_link.discover_workspaces({"workspaces": []})
    assert [w["path"] for w in found] == [os.path.realpath(local)]
    monkeypatch.setattr(hub_link, "_hub_url", "https://calkit.io")
    assert workspaces["dev/odd"]["project"] is None
    assert workspaces["dev/this-hub"]["project"] == "carol/fork"
    with open(os.path.join(this_hub, ".dvc", "config.local"), "w") as f:
        f.write(
            "[core]\n    remote = http\n['remote \"http\"']\n"
            "    url = https://api.calkit.io/projects/dave/http/dvc\n"
        )
    found = hub_link.discover_workspaces({"workspaces": []})
    assert [w["project"] for w in found if w["path"].endswith("this-hub")] == [
        "dave/http"
    ]
    # One odd repo doesn't keep the rest from the hub, and a run record is
    # cut to what the hub takes
    # Without Git, so it can be removed on Windows
    broken = os.path.join(home, "dev", "broken")
    os.makedirs(os.path.join(broken, ".dvc", "tmp"))
    with open(os.path.join(broken, "calkit.yaml"), "w") as f:
        f.write("owner: alice\nname: broken\n")
    with open(os.path.join(broken, ".dvc", "tmp", "rwlock"), "w") as f:
        f.write("[]")
    runs = os.path.join(this_hub, ".calkit", "local", "runs")
    os.makedirs(runs)
    with open(os.path.join(runs, "1.json"), "w") as f:
        json.dump({"status": "x" * 100, "start_time": None, "end_time": 5}, f)
    found = hub_link.discover_workspaces({"workspaces": []})
    by_path = {w["path"]: w for w in found}
    assert os.path.realpath(broken) not in by_path
    assert by_path[os.path.realpath(this_hub)]["last_run"] == {
        "status": "x" * 16,
        "started": None,
        "ended": "5",
        "failed_stages": [],
    }
    shutil.rmtree(broken)
    shutil.rmtree(runs)
    assert not os.path.exists(ran)
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
    op = hub_link.HubLink(cfg)
    op.workspaces = list(workspaces.values())
    assert op.get_workspace(managed, personal=False) == managed_ws["path"]
    with pytest.raises(ValueError):
        op.get_workspace(managed)
    with pytest.raises(ValueError):
        op.get_workspace(home)
    # Ones added to the config while it runs, e.g., with 'calkit hub link
    # add-workspace', show at its next check-in
    op = hub_link.HubLink({"name": "box", "token": "ckm_x", "workspaces": []})
    hub_link.save_config(
        {"name": "box", "token": "ckm_x", "workspaces": [elsewhere]}
    )
    reported = []
    monkeypatch.setattr(
        hub_link,
        "check_in",
        lambda cfg, workspaces, *args: reported.append(workspaces) or {},
    )
    asyncio.run(op.check_in())
    assert os.path.realpath(elsewhere) in [w["path"] for w in reported[0]]
    assert op.cfg["workspaces"] == [elsewhere]


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
        broken = start("not-an-agent", wdir)
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
        found = hub_link.find_agents([wdir, other])
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
        # A process that psutil fails to read, e.g., as it exits, is skipped
        # rather than ending the scan
        import psutil

        cmdline = psutil.Process.cmdline

        def flaky(self):
            if self.pid == broken:
                raise SystemError("returned a result with an exception set")
            return cmdline(self)

        with monkeypatch.context() as m:
            m.setattr(psutil.Process, "cmdline", flaky)
            assert {a["pid"] for a in hub_link.find_agents([wdir])[wdir]} == {
                claude,
                codex,
            }
        # Long names and statuses are cut to what the hub takes, and others
        # are left out
        with open(os.path.join(sessions_dir, f"{claude}.json"), "w") as f:
            json.dump({"name": "n" * 300, "status": "s" * 100}, f)
        agents = {a["tool"]: a for a in hub_link.find_agents([wdir])[wdir]}
        assert agents["claude"]["name"] == "n" * 256
        assert agents["claude"]["status"] == "s" * 64
        record = {"sessionId": "abc", "cwd": claude_cwd}
        with open(os.path.join(sessions_dir, f"{claude}.json"), "w") as f:
            json.dump(record | {"name": {"a": 1}, "status": 3}, f)
        agents = {a["tool"]: a for a in hub_link.find_agents([wdir])[wdir]}
        assert agents["claude"]["name"] is None
        assert agents["claude"]["status"] is None
        # Only ones in tmux can be attached to, and only in their workspace
        op = hub_link.HubLink({"workspaces": []})
        op.workspaces = [{"path": wdir, "kind": "personal"}]
        with pytest.raises(ValueError, match="tmux"):
            op.open_session(wdir, 80, 24, attach=claude)
        with pytest.raises(ValueError):
            hub_link.get_agent_log(other, claude)
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
            # What Claude Code adds itself reads as what happened
            *[
                {"type": "user", "timestamp": "t3", "message": {"content": c}}
                for c in [
                    "<task-notification>\n<task-id>b1</task-id>\n"
                    "<status>completed</status>\n<summary>Background "
                    'command "Wait" completed (exit code 1)</summary>\n'
                    "</task-notification>",
                    "<local-command-caveat>Caveat</local-command-caveat>",
                    "<command-name>/export</command-name>\n"
                    "<command-message>export</command-message>\n"
                    "<command-args>notes.txt</command-args>",
                    "<local-command-stdout>\x1b[1mExported\x1b[22m"
                    "</local-command-stdout>",
                    "<system-reminder>Context</system-reminder>",
                    '\n<pasted_content id="1">x</pasted_content>',
                ]
            ],
        ]
        with open(transcript, "w") as f:
            f.write("".join(json.dumps(line) + "\n" for line in lines))
        log = hub_link.get_agent_log(wdir, claude)
        assert log["entries"] == [
            {"role": "user", "text": "Hi", "time": "t1"},
            {"role": "assistant", "text": "Plotting", "time": "t2"},
            {"role": "tool", "text": "Bash: Run the plots", "time": "t2"},
            {
                "role": "event",
                "text": 'Background command "Wait" completed (exit code 1)',
                "time": "t3",
            },
            {"role": "user", "text": "/export notes.txt", "time": "t3"},
            {"role": "event", "text": "Exported", "time": "t3"},
            {
                "role": "user",
                "text": '<pasted_content id="1">x</pasted_content>',
                "time": "t3",
            },
        ]
        assert hub_link.get_agent_log(wdir, claude, limit=1)["entries"] == [
            log["entries"][-1]
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
        assert hub_link.get_agent_log(wdir, codex)["entries"] == [
            {"role": "user", "text": "Go", "time": "t3"},
            {"role": "assistant", "text": "Done", "time": "t4"},
        ]
        # The hub hears about them at check-in, without what's only for
        # attaching or reading their logs
        demo = next(
            ws
            for ws in hub_link.discover_workspaces({"workspaces": []})
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
    # The link points its own requests at its hub, which commands in
    # sessions don't inherit, so they use the project's
    monkeypatch.setattr(hub_link, "_inherited_hub", None)
    monkeypatch.setenv("CALKIT_HUB", "http://localhost")
    # Sessions are login shells, which mustn't run the machine's own
    # profile, e.g., a CI runner's, whose 'set -e' ends one at the first
    # failing command
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # Git in sessions mustn't find the user's own credential helpers
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    for name in ["GIT_ASKPASS", "SSH_ASKPASS"]:
        monkeypatch.delenv(name, raising=False)
    _init_project(os.path.join(tmp_path, "calkit", "demo"))
    import base64
    import time

    import jwt
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    from cryptography.hazmat.primitives.asymmetric.utils import (
        decode_dss_signature,
        encode_dss_signature,
    )
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )

    hub_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        hub_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    cfg = {
        "id": "op1",
        "user_id": "owner",
        "api_url": "https://api.hub",
        "grant_public_key": public_key,
        "workspaces": [],
    }
    op = hub_link.HubLink(cfg)
    op.workspaces = hub_link.discover_workspaces(op.cfg)
    # Channels are only opened while the hub can be heard from
    op.last_check_in = time.monotonic()

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    # Each browser connection makes a key, which its grant names
    def browser_key():
        key = ec.generate_private_key(ec.SECP256R1())
        numbers = key.public_key().public_numbers()
        jwk = {
            "kty": "EC",
            "crv": "P-256",
            "x": b64url(numbers.x.to_bytes(32, "big")),
            "y": b64url(numbers.y.to_bytes(32, "big")),
        }
        return key, jwk

    browser, browser_jwk = browser_key()

    def grant(
        sub="owner",
        aud="op1",
        expires_in=60,
        key=hub_key,
        jti=None,
        jwk=None,
        sid="sign-in-1",
        tfa_exp=None,
        drop=(),
    ):
        payload = {
            "exp": time.time() + expires_in,
            "iat": int(time.time()),
            "aud": aud,
            "sub": sub,
            "jti": jti or os.urandom(8).hex(),
            "cnf": {"jwk": jwk or browser_jwk},
            "sid": sid,
            "tfa_exp": int(time.time()) + 3600 if tfa_exp is None else tfa_exp,
        }
        for k in drop:
            del payload[k]
        return jwt.encode(payload, key, algorithm="EdDSA")

    # As a browser signs with WebCrypto: r and s side by side
    seqs: dict[str, int] = {}

    def sign(ch, msg, key=None, seq=None):
        if seq is None:
            seq = seqs[ch] = seqs.get(ch, 0) + 1
        body = json.dumps(msg)
        r, s = decode_dss_signature(
            (key or browser).sign(
                f"{hub_link.MESSAGE_SIGNATURE_CONTEXT}\n{seq}\n{body}".encode(),
                ec.ECDSA(hashes.SHA256()),
            )
        )
        sig = b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        return {"seq": seq, "body": body, "sig": sig}

    workspace = op.workspaces[0]["path"]

    # What reaches the relay, in order
    class FakeSocket:
        def __init__(self):
            self.sent: list[str] = []

        async def send(self, text):
            self.sent.append(text)

    op.ws = FakeSocket()
    grant_ids: dict[str, str] = {}

    def open_channel(ch: str, **kwargs: Any) -> None:
        grant_ids[ch] = kwargs.setdefault("jti", os.urandom(8).hex())
        seqs[ch] = 0
        cleared_seqs[ch] = 0
        op.on_relay_message(
            {"type": "channel.open", "ch": ch, "grant": grant(**kwargs)}
        )

    def link_public_key() -> Any:
        return hub_link.get_link_key().public_key()

    def verify(signed: dict, grant_id: str) -> None:
        raw = base64.urlsafe_b64decode(signed["sig"] + "==")
        link_public_key().verify(
            encode_dss_signature(
                int.from_bytes(raw[:32], "big"),
                int.from_bytes(raw[32:], "big"),
            ),
            f"{hub_link.REPLY_SIGNATURE_CONTEXT}\n{grant_id}\n"
            f"{signed['seq']}\n{signed['body']}".encode(),
            ec.ECDSA(hashes.SHA256()),
        )

    # Replies a browser would take, each signed by the link for its
    # channel's grant, in order
    # The last reply's sequence number on each channel before what's in
    # the log, which is cleared as the test goes
    cleared_seqs: dict[str, int] = {}

    def sent() -> list[tuple[str, dict]]:
        replies, last = [], dict(cleared_seqs)
        for text in op.ws.sent:
            frame = json.loads(text)
            if "msg" not in frame:
                continue
            ch, signed = frame["ch"], frame["msg"]
            verify(signed, grant_ids[ch])
            assert signed["seq"] == last.get(ch, 0) + 1
            last[ch] = signed["seq"]
            replies.append((ch, json.loads(signed["body"])))
        return replies

    def to_relay() -> list[dict]:
        return [
            json.loads(t) for t in op.ws.sent if "msg" not in json.loads(t)
        ]

    def clear() -> None:
        for text in op.ws.sent:
            frame = json.loads(text)
            if "msg" in frame:
                cleared_seqs[frame["ch"]] = frame["msg"]["seq"]
        op.ws.sent.clear()

    async def wait_for(predicate, timeout=10.0):
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.05)

    def output(ch):
        return "".join(
            m["data"]
            for c, m in sent()
            if c == ch and m["type"] == "sessions.output"
        )

    def reply(req_id):
        replies = [m for _, m in sent() if m.get("id") == req_id]
        return replies[0] if replies else None

    def message(ch, msg):
        op.on_relay_message(
            {"type": "channel.message", "ch": ch, "msg": sign(ch, msg)}
        )

    # Channels are refused unless the hub signed a grant for the owner to use
    # this machine, whatever the relay says, and each grant works once,
    # even after a restart
    open_channel("u", jti="used")
    op.on_relay_message({"type": "channel.close", "ch": "u"})
    restarted = hub_link.HubLink(cfg)
    restarted.ws = FakeSocket()
    restarted.last_check_in = time.monotonic()
    used = grant(jti="used")
    restarted.on_relay_message(
        {"type": "channel.open", "ch": "u", "grant": used}
    )
    assert restarted.channels == {}
    await asyncio.sleep(0.05)
    assert [json.loads(t) for t in restarted.ws.sent] == [
        {"type": "channel.close", "ch": "u"}
    ]
    if sys.platform != "win32":
        used_path = os.path.join(hub_link.link_dir(), "used-grants.json")
        assert stat.S_IMODE(os.stat(used_path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(hub_link.link_dir()).st_mode) == 0o700
    await asyncio.sleep(0.05)
    clear()
    for bad in [
        None,
        "nope",
        grant(sub="eve"),
        grant(aud="op2"),
        grant(expires_in=-120),
        grant(key=Ed25519PrivateKey.generate()),
        # Grants name the browser's key and sign-in, when they were issued,
        # and when their second factor expires, which mustn't have passed
        grant(drop=["cnf"]),
        grant(drop=["sid"]),
        grant(drop=["iat"]),
        grant(drop=["tfa_exp"]),
        grant(tfa_exp=int(time.time()) - 5),
        grant(tfa_exp="later"),
        grant(jwk=browser_jwk | {"y": browser_jwk["x"]}),
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
    # Nor while the hub can't be heard from, so ended sign-ins would go
    # unnoticed
    op.last_check_in = time.monotonic() - hub_link.CHECK_IN_GRACE_SECONDS
    open_channel("x")
    op.last_check_in = time.monotonic()
    # The relay names channels, and only plainly
    for bad_ch in ["a b", "x" * 65, "a\nb", 7]:
        op.on_relay_message(
            {"type": "channel.open", "ch": bad_ch, "grant": grant()}
        )
    await asyncio.sleep(0.1)
    assert op.channels == {}
    assert sent() == []
    assert {json.dumps(m) for m in to_relay()} == {
        '{"type": "channel.close", "ch": "x"}'
    }
    clear()
    # A channel's first reply says it's ready, signed with the link's
    # key for that channel's grant only, so the relay can't move replies
    # from one channel to another
    open_channel("a")
    await wait_for(lambda: sent())
    assert sent() == [("a", {"type": "channel.ready"})]
    first = json.loads(op.ws.sent[0])["msg"]
    with pytest.raises(InvalidSignature):
        verify(first, "another-grant")
    if sys.platform != "win32":
        key_path = os.path.join(hub_link.link_dir(), "link-key.pem")
        assert stat.S_IMODE(os.stat(key_path).st_mode) == 0o600
    # It's the key the hub is told about
    numbers = link_public_key().public_numbers()
    jwk = hub_link.get_link_public_jwk()
    assert jwk["kty"] == "EC" and jwk["crv"] == "P-256"
    assert hub_link._b64url_decode(jwk["x"]) == numbers.x.to_bytes(32, "big")
    assert len(jwk["x"]) == len(jwk["y"]) == 43
    # Replies go out unescaped, since escaping a TUI's box drawing makes
    # each character up to 12 bytes, which can pass the relay's limit
    op.send_soon("a", {"data": "───"})
    await wait_for(lambda: len(sent()) == 2)
    assert "───" in op.ws.sent[-1]
    clear()
    # On an open channel, only messages the browser signed count, each once
    # and in order, without any missing, e.g., a keystroke, so the relay that
    # carried the grant can't act with it; anything else closes the channel
    listing = {"type": "sessions.list", "id": 20}
    other_key, _ = browser_key()
    for i, make_bad in enumerate(
        [
            lambda ch: listing,
            lambda ch: (
                sign(ch, listing) | {"body": json.dumps(listing | {"id": 21})}
            ),
            lambda ch: sign(ch, listing) | {"sig": "A" * 86},
            lambda ch: sign(ch, listing, key=other_key),
            lambda ch: sign(ch, listing) | {"seq": True},
            lambda ch: sign(ch, listing, seq=2),
            lambda ch: sign(ch, listing, seq=0),
        ]
    ):
        ch = f"bad{i}"
        open_channel(ch)
        op.on_relay_message(
            {"type": "channel.message", "ch": ch, "msg": make_bad(ch)}
        )
        assert ch not in op.channels
    await asyncio.sleep(0.1)
    assert all(m["type"] == "channel.ready" for _, m in sent())
    assert [m["ch"] for m in to_relay()] == [f"bad{i}" for i in range(7)]
    clear()
    open_channel("a")
    signed = sign("a", listing)
    op.on_relay_message({"type": "channel.message", "ch": "a", "msg": signed})
    await wait_for(lambda: reply(20))
    # Replaying one closes it too
    op.on_relay_message({"type": "channel.message", "ch": "a", "msg": signed})
    assert "a" not in op.channels
    clear()
    # Signed as sent, as the hub's tests check with the same vector, from
    # hub/frontend/src/components/Machines/connection.test.ts
    vector = {
        "jwk": {
            "kty": "EC",
            "crv": "P-256",
            "x": "ZfNFdAzsfpIWhDie2L9NwSNt6d6a2lwlSMf3MzH-XVk",
            "y": "Hh0kg1uyGNF6Zd34yhdohtFps5dU_GcMu5ZyZ-YL7LM",
        },
        "seq": 7,
        "body": '{"type":"sessions.input","session":"s1","data":"ls ─\\n"}',
        "sig": (
            "xshOHd9lW3FQS3_FXFFzmZU8wWUPdrVR6VmguNFs9Xr-kxLc2jzVSXqYlOfXn9DW"
            "eTjonww_5a6Rio0iIGGpZA"
        ),
    }
    auth = hub_link.check_grant(op.cfg, grant(jwk=vector["jwk"]), {})
    assert auth is not None
    auth.seq = 6
    assert hub_link.open_signed_message(
        auth, {k: vector[k] for k in ["seq", "body", "sig"]}
    ) == {"type": "sessions.input", "session": "s1", "data": "ls ─\n"}
    # A type that isn't a string is refused without ending the channel
    open_channel("a")
    message("a", {"type": ["x"], "id": 30})
    await wait_for(lambda: reply(30))
    assert reply(30) == {"type": "error", "id": 30, "error": "Invalid type"}
    # Only allowed workspaces can have sessions
    message("a", {"type": "sessions.open", "id": 2, "workspace": "/"})
    await wait_for(lambda: reply(2))
    assert reply(2)["type"] == "error"
    message("a", {"type": "sessions.open", "id": 3, "workspace": workspace})
    await wait_for(lambda: reply(3))
    sid = reply(3)["result"]["session"]
    # Opening a session takes the workspace from other hubs' links
    assert hub_link.workspace_lock_holder(workspace)["pid"] == os.getpid()
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
    # The session gets credentials from the link, which gets them from the
    # hub with the grant that opened it, over a socket in a folder only the
    # user can open, with a secret only the session is told
    from calkit.hub import core as hub

    asked: list[tuple[str, str, str]] = []

    def fake_credential(
        cfg: dict, route: str, shown: str, repo: str = ""
    ) -> tuple[str, float]:
        asked.append((route, shown, repo))
        if route == "session-token":
            return jwt.encode(
                {"exp": time.time() + 900, "n": len(asked)}, "k" * 32
            ), time.time() + 900
        return f"ghs_{len(asked)}", time.time() + 900

    monkeypatch.setattr(
        hub_link, "request_session_credential", fake_credential
    )
    session = op.sessions[sid]
    assert session.creds is not None
    cred_dir = session.creds.dir
    sock_path = os.path.join(cred_dir, "creds.sock")
    assert stat.S_IMODE(os.stat(cred_dir).st_mode) == 0o700
    message(
        "a",
        {
            "type": "sessions.input",
            "session": sid,
            "data": 'echo "CREDS:$CALKIT_LINK_SOCKET:$CALKIT_LINK_API_URL:'
            "$GIT_CONFIG_KEY_0=$GIT_CONFIG_VALUE_0:$GIT_CONFIG_KEY_2="
            '$GIT_CONFIG_VALUE_2:$GIT_CONFIG_COUNT:CREDS"\n',
        },
    )
    # Every helper GitHub would get is reset before the link's, which is
    # given the repo's path
    await wait_for(
        lambda: (
            f"CREDS:{sock_path}:https://api.hub:"
            "credential.https://github.com.helper=:"
            "credential.https://github.com.useHttpPath=true:3:CREDS"
            in output("a")
        )
    )
    monkeypatch.setenv(hub.LINK_SOCKET_ENV, sock_path)
    monkeypatch.setenv(hub.LINK_SECRET_ENV, session.creds.secret)

    async def ask(req: dict) -> dict:
        return await asyncio.to_thread(hub.ask_link, req)

    token_req = {"type": "hub.token", "api_url": "https://api.hub/"}
    first = await ask(token_req)
    assert await ask(token_req) == first
    assert asked == [("session-token", op.channels["a"].grant, "")]
    # A fresh one when the last was refused
    assert await ask(token_req | {"fresh": True}) != first
    assert len(asked) == 2
    # Only for this link's hub, and only with the secret
    with pytest.raises(hub.LinkCredentialError, match="only has tokens for"):
        await ask({"type": "hub.token", "api_url": "https://api.other"})
    monkeypatch.setenv(hub.LINK_SECRET_ENV, "wrong")
    with pytest.raises(hub.LinkCredentialError, match="secret"):
        await ask(token_req)
    monkeypatch.setenv(hub.LINK_SECRET_ENV, session.creds.secret)
    # Git asks for GitHub's through the helper sessions are set up with, only
    # for github.com, and forgets one GitHub refused
    clear()
    message(
        "a",
        {
            "type": "sessions.input",
            "session": sid,
            "data": "for h in gitlab.com github.com; do printf "
            "'protocol=https\\nhost=%s\\npath=o/r.git\\n\\n' $h | "
            "GIT_TERMINAL_PROMPT=0 "
            "git credential fill; done; echo FILLED-$((40+2))\n",
        },
    )
    # Expanded, so the terminal echoing the command doesn't count
    await wait_for(lambda: "FILLED-42" in output("a"), timeout=60)
    filled = output("a").split("FILLED-42")[0]
    assert "password=ghs_3" in filled and "host=gitlab.com" not in filled
    assert "username=x-access-token" in filled
    assert asked[-1] == ("github-token", op.channels["a"].grant, "o/r")
    # Each repo's is its own, kept until it expires, and forgetting one
    # leaves the others
    github_req = {"type": "github.token", "path": "o/r.git"}
    assert await ask(github_req) == {"token": "ghs_3"}
    assert await ask(github_req | {"path": "o/other"}) == {"token": "ghs_4"}
    assert asked[-1][2] == "o/other"
    assert await ask(github_req | {"forget": True}) == {}
    assert await ask(github_req) == {"token": "ghs_5"}
    assert await ask(github_req | {"path": "o/other"}) == {"token": "ghs_4"}
    # Repos can start with "." or "_"
    assert await ask(github_req | {"path": "o/.github.git"}) == {
        "token": "ghs_6"
    }
    assert asked[-1][2] == "o/.github"
    # Only for a plain "owner/repo"
    for bad in [
        None,
        7,
        "",
        "o",
        "o/r/x",
        "../r",
        "-o/r",
        "o/-r",
        "o/.git",
        "o/..",
        "o/.",
        "o/r?x",
    ]:
        with pytest.raises(hub.LinkCredentialError, match="GitHub"):
            await ask(github_req | {"path": bad})

    # Actions the hub starts get them the same way, with the grant of the
    # channel that asked, over a channel of their own that closes with
    # them, for what they run and for Git run from the link itself, and
    # share what that grant already got
    def credentialed(wdir: str, **kwargs: Any) -> dict:
        creds = hub_link._action_credentials.get()
        if creds is None:
            return {"creds": None}
        repo = hub_link.get_workspace_repo(wdir)
        # With the user's own helper storing what it's given, which Git
        # doesn't then ask for GitHub's
        home = tmp_path / "action-home"
        home.mkdir(exist_ok=True)
        (home / ".gitconfig").write_text("[credential]\n\thelper = store\n")
        env = hub_link.no_prompt_env(wdir) | {
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
        }

        def git_credential(operation: str, attrs: str) -> str:
            return subprocess.run(
                ["git", "credential", operation],
                input=attrs,
                env=env,
                cwd=wdir,
                capture_output=True,
                text=True,
            ).stdout

        filled = git_credential(
            "fill", "protocol=https\nhost=github.com\npath=o/r.git\n\n"
        )
        git_credential("approve", filled + "\n")
        return {
            "creds": creds.dir,
            "helper": repo.git.config(
                "--get-urlmatch", "credential.helper", "https://github.com"
            ),
            "filled": filled,
            "stored": os.listdir(home),
        }

    for kind in [
        "workspace.push",
        "workspace.status",
        "workspace.stages",
        "workspace.ignore",
    ]:
        monkeypatch.setitem(hub_link.WORKSPACE_ACTIONS, kind, credentialed)
    asked_before = len(asked)
    message("a", {"type": "workspace.push", "id": 50, "workspace": workspace})
    await wait_for(lambda: reply(50), timeout=60)
    pushed = reply(50)["result"]
    assert "git-credential" in pushed["helper"]
    assert "password=ghs_5" in pushed["filled"]
    assert pushed["stored"] == [".gitconfig"]
    assert len(asked) == asked_before
    assert not os.path.exists(pushed["creds"])
    # Only actions that may reach the network get any
    for req_id, msg in [
        (51, {"type": "workspace.stages"}),
        (52, {"type": "workspace.status", "fetch": False}),
        (53, {"type": "workspace.status"}),
        (54, {"type": "workspace.ignore", "path": "x", "push": False}),
        (55, {"type": "workspace.ignore", "path": "x", "push": True}),
    ]:
        message("a", msg | {"id": req_id, "workspace": workspace})
    await wait_for(lambda: all(reply(i) for i in range(51, 56)), timeout=60)
    assert reply(54)["result"] == {"creds": None}
    assert "password=ghs_5" in reply(55)["result"]["filled"]
    # Nor on Windows, whose event loops can't serve Unix sockets
    with monkeypatch.context() as m:
        m.setattr(hub_link.sys, "platform", "win32")
        assert op.open_credentials(op.channels["a"]) is None
    assert sys.platform != "win32"
    assert reply(51)["result"] == reply(52)["result"] == {"creds": None}
    assert "password=ghs_5" in reply(53)["result"]["filled"]
    # The sign-in they were got with ending forgets them
    assert op.credentials
    op.credentials[("other", "github-token", "o/r")] = (
        "ghs_x",
        time.time() + 60,
        "x",
    )
    op.close_ended_channels(["sign-in-gone"])
    assert ("other", "github-token", "o/r") in op.credentials
    op.close_ended_channels(["x"])
    assert ("other", "github-token", "o/r") not in op.credentials
    # A session doesn't get another's terminal, nor anything else the
    # link has open, which a shell that lists what it has shows
    assert not os.get_inheritable(op.sessions[sid].fd)
    lister = tmp_path / "lister.sh"
    lister.write_text(
        "#!/bin/sh\necho \"FDS:$(ls /dev/fd | tr '\\n' ' '):FDS\"\n"
        'exec /bin/sh "$@"\n'
    )
    lister.chmod(0o755)
    monkeypatch.setenv("SHELL", str(lister))
    message("a", {"type": "sessions.open", "id": 7, "workspace": workspace})
    await wait_for(lambda: reply(7))
    monkeypatch.setenv("SHELL", "/bin/sh")
    second = reply(7)["result"]["session"]
    await wait_for(lambda: ":FDS" in output("a"))
    listed = output("a").split("FDS:")[1].split(":FDS")[0].split()
    assert "0" in listed and str(op.sessions[sid].fd) not in listed
    message("a", {"type": "sessions.close", "session": second})
    await wait_for(lambda: second not in op.sessions)
    # A second channel attaching gets the scrollback replayed, and the
    # session's credentials then last as long as its second factor, if
    # that's longer
    open_channel("early", tfa_exp=int(time.time()) + 60)
    message("early", {"type": "sessions.attach", "id": 40, "session": sid})
    await wait_for(lambda: reply(40))
    assert op.sessions[sid].creds.auth is op.channels["a"]
    open_channel("b", tfa_exp=int(time.time()) + 7200)
    message("b", {"type": "sessions.attach", "id": 4, "session": sid})
    await wait_for(lambda: "HI-42" in output("b"))
    assert op.sessions[sid].creds.auth is op.channels["b"]
    # Marked, so the browser doesn't answer queries in it a second time
    outputs = [(c, m) for c, m in sent() if m["type"] == "sessions.output"]
    assert all(m.get("replay") for c, m in outputs if c == "b")
    assert not any(
        m.get("replay") for c, m in outputs if c == "a" and "HI" in m["data"]
    )
    # Sessions outlive the channels attached to them
    op.on_relay_message({"type": "channel.close", "ch": "a"})
    op.on_relay_message({"type": "channel.close", "ch": "b"})
    op.on_relay_message({"type": "channel.close", "ch": "early"})
    assert op.sessions[sid].channels == set()
    # With no browser attached, check-ins still ask about the sign-in its
    # credentials came from, and once that ends, e.g., with a logout, it
    # gets no more, even ones the link kept
    assert (await ask(github_req))["token"].startswith("ghs_")
    reported: list[list[str]] = []

    def logged_out(cfg, workspaces, mode, connected, restart, sessions):
        reported.append(sessions)
        return {"ended_sessions": ["sign-in-1"]}

    monkeypatch.setattr(hub_link, "check_in", logged_out)
    monkeypatch.setattr(
        hub_link, "discover_workspaces", lambda cfg: op.workspaces
    )
    await op.check_in()
    assert reported == [["sign-in-1"]]
    with pytest.raises(hub.LinkCredentialError, match="has ended"):
        await ask(github_req)
    assert not any(v[2] == "sign-in-1" for v in op.credentials.values())
    open_channel("c")
    message("c", {"type": "sessions.list", "id": 5})
    await wait_for(lambda: reply(5))
    assert [s["id"] for s in reply(5)["result"]["sessions"]] == [sid]
    message("c", {"type": "sessions.attach", "id": 6, "session": sid})
    message(
        "c", {"type": "sessions.input", "session": sid, "data": "exit 3\n"}
    )
    await wait_for(
        lambda: [
            m for c, m in sent() if c == "c" and m["type"] == "sessions.exit"
        ]
    )
    exits = [m for c, m in sent() if c == "c" and m["type"] == "sessions.exit"]
    assert exits == [{"type": "sessions.exit", "session": sid, "code": 3}]
    assert op.sessions == {}
    # Its credentials go with it
    assert not os.path.exists(cred_dir)
    with pytest.raises(hub.LinkCredentialError, match="Couldn't reach"):
        await ask(token_req)
    # A reply too large for the relay is an error instead, and a browser too
    # far behind is closed
    message("c", {"type": "sessions.list", "id": 8})
    await wait_for(lambda: reply(8))
    clear()
    op.send_soon("c", {"type": "result", "id": 9, "result": "\x1b" * 100_000})
    await wait_for(lambda: reply(9))
    assert reply(9)["type"] == "error"
    monkeypatch.setattr(hub_link, "MAX_CHANNEL_BACKLOG_BYTES", 1000)
    open_channel("slow")
    op.send_soon("slow", {"data": "x" * 900})
    assert "slow" not in op.channels
    monkeypatch.setattr(hub_link, "MAX_CHANNEL_BACKLOG_BYTES", 2**20)
    await asyncio.sleep(0.1)
    clear()
    # Channels close once the sign-in they came from ends, e.g., with a
    # password change, which check-ins hear about, and the relay is given
    # a fresh token for the connection
    open_channel("d", sid="sign-in-2")
    checked_in: list[list[str]] = []

    def fake_check_in(cfg, workspaces, mode, connected, restart, sessions):
        checked_in.append(sessions)
        return {"ended_sessions": ["sign-in-2"], "relay_token": "tok2"}

    monkeypatch.setattr(hub_link, "check_in", fake_check_in)
    monkeypatch.setattr(hub_link, "discover_workspaces", lambda cfg: [])
    await op.check_in()
    assert checked_in == [["sign-in-1", "sign-in-2"]]
    assert set(op.channels) == {"c"}
    await asyncio.sleep(0.1)
    # The relay is asked to close it, though it's refused here regardless
    assert to_relay() == [
        {"type": "channel.close", "ch": "d"},
        {"type": "auth.refresh", "token": "tok2"},
    ]
    clear()
    message("d", {"type": "sessions.list", "id": 31})
    await asyncio.sleep(0.1)
    assert sent() == []

    # A new grant key from the hub, which comes over HTTPS, replaces the
    # one grants were checked with, so channels opened with the old one close
    def new_key(cfg: dict, *args: Any) -> dict:
        cfg["grant_public_key"] = "other"
        return {}

    monkeypatch.setattr(hub_link, "check_in", new_key)
    await op.check_in()
    assert op.channels == {}
    cfg["grant_public_key"] = public_key
    # They close once their second factor expires, and while the hub can't
    # be reached
    open_channel("e")
    open_channel("f")
    op.channels["e"].tfa_exp = time.time() - 1
    op.expire_channels()
    assert set(op.channels) == {"f"}
    op.last_check_in = time.monotonic() - hub_link.CHECK_IN_GRACE_SECONDS
    op.expire_channels()
    assert op.channels == {}
    # With nothing using it, a link with an idle limit stops, but not while
    # a run goes on with no browser left
    op.idle_exit_seconds = 0.1
    op.workspace_actions["/ws"] = "workspace.run"
    idle = asyncio.create_task(op.wait_until_idle())
    await asyncio.sleep(0.35)
    assert not idle.done()
    op.workspace_actions.clear()
    await asyncio.wait_for(idle, 5)


def test_log(tmp_path, monkeypatch):
    import logging

    # A log past its limit keeps its newest whole lines, in the same file
    # the service manager has open
    fpath = str(tmp_path / "hub_link.log")
    monkeypatch.setattr(hub_link, "LOG_MAX_BYTES", 100)
    monkeypatch.setattr(hub_link, "LOG_KEEP_BYTES", 50)
    monkeypatch.setattr(hub_link.sys, "platform", "linux")
    with open(fpath, "a") as service:
        service.write("".join(f"line {i:03d}\n" for i in range(20)))
        service.flush()
        hub_link.trim_log(fpath)
        service.write("after\n")
    with open(fpath) as f:
        lines = f.read().splitlines()
    assert lines[-1] == "after"
    assert lines[0].startswith("line ") and len(lines) < 10
    assert lines[-2] == "line 019"
    # Under the limit, or missing, it's left alone
    hub_link.trim_log(fpath)
    with open(fpath) as f:
        assert f.read().splitlines() == lines
    hub_link.trim_log(str(tmp_path / "missing.log"))
    # The same warning is only logged again after a while
    records = []
    log = logging.getLogger("test_hub_link_log")
    log.propagate = False
    log.setLevel(logging.INFO)
    log.addHandler(logging.Handler())
    log.handlers[0].emit = records.append  # type: ignore[method-assign]
    log.addFilter(hub_link.RepeatFilter())
    for _ in range(3):
        log.warning("Check-in failed: 404")
        log.warning("Connection failed: 404")
        log.info("Connected to relay")
    assert [r.getMessage() for r in records].count("Check-in failed: 404") == 1
    assert len([r for r in records if r.levelno == logging.INFO]) == 3
    monkeypatch.setattr(hub_link, "REPEAT_LOG_SECONDS", 0)
    log.warning("Check-in failed: 404")
    assert [r.getMessage() for r in records].count("Check-in failed: 404") == 2


def test_service_files(tmp_path, monkeypatch):
    import plistlib

    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    # Started from /, without what's there on the import path, so modules
    # in the home folder, e.g., a pty.py, can't stand in for its own
    command = [
        *hub_link.CALKIT_COMMAND,
        "hub",
        "link",
        "start",
        "--hub",
        "https://calkit.io",
        "--mode",
        "service",
    ]
    (tmp_path / "typer.py").write_text("raise SystemExit('shadowed')\n")
    version = subprocess.run(
        [*hub_link.CALKIT_COMMAND, "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert version.returncode == 0, version.stderr
    # launchd restarts it on failure, but not after it exits because it
    # was revoked
    agent = plistlib.loads(hub_link._launchd_plist(at_boot=False))
    assert agent["ProgramArguments"] == command
    assert agent["KeepAlive"] == {"SuccessfulExit": False}
    assert agent["StandardOutPath"] == hub_link.get_log_path()
    assert agent["WorkingDirectory"] == "/"
    assert "UserName" not in agent
    # Not throttled like a background job
    assert agent["ProcessType"] == "Interactive"
    assert hub_link._launchd_plist_path(at_boot=False).startswith(
        str(tmp_path)
    )
    # At boot it's a system daemon that still runs as this user, which only
    # macOS has
    if sys.platform != "win32":
        daemon = plistlib.loads(hub_link._launchd_plist(at_boot=True))
        assert daemon["UserName"]
        # launchd opens its log as root, so the link writes its own
        assert daemon["StandardOutPath"] == "/dev/null"
        assert daemon["StandardErrorPath"] == "/dev/null"
        assert daemon["ProgramArguments"] == [*command, "--log-file"]
        assert hub_link._launchd_plist_path(at_boot=True).startswith(
            "/Library/LaunchDaemons/"
        )
    # On Windows, a script in the Startup folder runs it hidden at login
    script = hub_link._windows_startup_script()
    assert "--mode" in script and "service" in script
    assert hub_link.get_log_path() in script
    # The whole command has its own quotes, since cmd strips the outer pair
    # of one with more than two (doubled here, for VBScript)
    assert 'cmd /c ""' in script and '2>&1"""' in script
    unit = hub_link._systemd_unit()
    expected = shlex.join(command).replace("\\", "\\\\")
    assert f"ExecStart={expected}" in unit
    assert "WorkingDirectory=/\n" in unit
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit
    # What systemd would expand in a path is escaped
    with monkeypatch.context() as m:
        m.setattr(
            hub_link, "CALKIT_COMMAND", ["/opt/py%x$y/python", "-c", "x"]
        )
        assert (
            "ExecStart='/opt/py%%x$$y/python' -c x" in hub_link._systemd_unit()
        )
    # Restarting a loaded launchd agent happens in place, since booting it
    # out returns before it has stopped, so booting it in again fails;
    # one that isn't loaded is started
    calls: list[list[str]] = []
    loaded = [True]

    def run(cmd, **kwargs):
        calls.append(cmd)
        code = 0 if cmd[:2] != ["launchctl", "print"] or loaded[0] else 113
        return subprocess.CompletedProcess(cmd, code)

    monkeypatch.setattr(hub_link.subprocess, "run", run)
    monkeypatch.setattr(hub_link.os, "getuid", lambda: 501, raising=False)
    # Runners have no user 501, and Windows has no pwd module
    monkeypatch.setitem(
        sys.modules,
        "pwd",
        SimpleNamespace(getpwuid=lambda uid: SimpleNamespace(pw_name="me")),
    )
    monkeypatch.setattr(hub_link.platform, "system", lambda: "Darwin")
    agent_path = hub_link._launchd_plist_path(at_boot=False)
    os.makedirs(os.path.dirname(agent_path))
    Path(agent_path).write_bytes(hub_link._launchd_plist(at_boot=False))
    target = f"gui/501/{hub_link.service_label()}"
    for is_loaded, last in [
        (True, ["launchctl", "kickstart", "-k", target]),
        (False, ["launchctl", "bootstrap", "gui/501", agent_path]),
    ]:
        loaded[0] = is_loaded
        calls.clear()
        hub_link.restart_service()
        assert calls == [["launchctl", "print", target], last]
    # systemd restarts in one step too
    monkeypatch.setattr(hub_link.platform, "system", lambda: "Linux")
    unit_path = hub_link._systemd_unit_path()
    os.makedirs(os.path.dirname(unit_path))
    Path(unit_path).write_text(unit)
    calls.clear()
    hub_link.restart_service()
    assert calls == [
        ["systemctl", "--user", "restart", hub_link.systemd_unit()]
    ]
    # Installing starts it at boot unless told to start at login, falling
    # back to login when sudo can't be had without a terminal to ask in
    sudo_cached = [True]

    def run_install(cmd, **kwargs):
        calls.append(cmd)
        code = 0
        if cmd == ["sudo", "-n", "true"]:
            code = 0 if sudo_cached[0] else 1
        elif cmd[:2] == ["loginctl", "enable-linger"]:
            # Not allowed for this user without sudo
            code = 1
        elif "launchctl" in cmd and "print" in cmd:
            code = 113
        stdout = "no" if "show-user" in cmd else ""
        return subprocess.CompletedProcess(cmd, code, stdout=stdout)

    monkeypatch.setattr(hub_link.subprocess, "run", run_install)
    monkeypatch.setattr(hub_link.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(hub_link, "_has_terminal", lambda: False)
    monkeypatch.setattr(hub_link.platform, "system", lambda: "Darwin")
    daemon_bootstrap = [
        "sudo",
        "-n",
        "launchctl",
        "bootstrap",
        "system",
        hub_link._launchd_plist_path(at_boot=True),
    ]
    agent_bootstrap = ["launchctl", "bootstrap", "gui/501", agent_path]
    for cached, login, bootstrap, noted in [
        (True, False, daemon_bootstrap, False),
        (False, False, agent_bootstrap, True),
        (True, True, agent_bootstrap, False),
    ]:
        sudo_cached[0] = cached
        calls.clear()
        notes = hub_link.install_service(login=login)
        assert bootstrap in calls
        assert any("needs sudo" in n for n in notes) == noted
        # Starting at login never asks for sudo
        if login:
            assert not any(c[:1] == ["sudo"] for c in calls)
    # Removing the boot service says how when sudo fails, e.g., with no
    # terminal to ask in
    daemon = tmp_path / "daemon.plist"
    daemon.write_text("")
    with monkeypatch.context() as m:
        m.setattr(
            hub_link,
            "_launchd_plist_path",
            lambda at_boot, key=None: str(
                daemon if at_boot else tmp_path / "none.plist"
            ),
        )
        with pytest.raises(RuntimeError, match="sudo rm"):
            hub_link.uninstall_service()
    # On Linux, lingering is enabled with sudo if it can't be without, and
    # left alone when starting at login
    monkeypatch.setattr(hub_link.platform, "system", lambda: "Linux")
    user = os.environ.get("USER") or ""
    for cached, login, sudo_linger, noted in [
        (True, False, True, False),
        (False, False, False, True),
        (True, True, False, False),
    ]:
        sudo_cached[0] = cached
        calls.clear()
        notes = hub_link.install_service(login=login)
        assert (
            ["sudo", "-n", "loginctl", "enable-linger", user] in calls
        ) == sudo_linger
        assert any("enable-linger" in n for n in notes) == noted
        if login:
            assert not any("enable-linger" in c for c in calls)


@pytest.mark.skipif(sys.platform == "win32", reason="Cron and flock are POSIX")
def test_cron_and_lock(tmp_path, monkeypatch):
    # A service gets the PATH a login shell sets up, after whatever its
    # profile prints, or keeps its own if the shell fails
    shell = tmp_path / "fake-shell"
    shell.write_text(
        "#!/bin/sh\necho Welcome\nPATH=/custom/bin:/usr/bin:/bin\n"
        'export PATH\nshift 2\nexec /bin/sh -c "$1"\n'
    )
    shell.chmod(0o755)
    monkeypatch.setenv("SHELL", str(shell))
    assert hub_link.login_shell_path() == "/custom/bin:/usr/bin:/bin"
    shell.write_text("#!/bin/sh\nexit 1\n")
    assert hub_link.login_shell_path() is None
    # A % in a path would be a newline to cron
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path / "home%1"))
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
    hub_link.install_cron()
    hub_link.install_cron()
    lines = table.read_text().splitlines()
    assert lines[0] == "0 * * * * echo mine"
    ours = [line for line in lines if line.endswith(hub_link.cron_marker())]
    assert [line.split()[0] for line in ours] == ["*/5", "@reboot"]
    assert all("--mode cron" in line for line in ours)
    # From /, so nothing in the home folder is on its import path
    assert all(" cd / && " in line for line in ours)
    log = hub_link.get_log_path()
    assert "%" in log
    assert all(log.replace("%", "\\%") in line for line in ours)
    assert all("%" not in line.replace("\\%", "") for line in ours)
    # Its folder and log are the user's alone, e.g., on a shared login node
    assert stat.S_IMODE(os.stat(log).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(log)).st_mode) == 0o700
    assert "cron" in hub_link.get_service_status()
    hub_link.uninstall_service()
    assert table.read_text().splitlines() == ["0 * * * * echo mine"]
    assert hub_link.get_service_status() is None
    # In cron mode, starting checks in now and stopping ends the running one
    started, stopped = [], []
    with monkeypatch.context() as m:
        m.setattr(hub_link, "_cron_installed", lambda: True)
        m.setattr(
            hub_link.subprocess,
            "Popen",
            lambda argv, **kw: started.append(argv),
        )
        m.setattr(hub_link, "_stop_running_link", lambda: stopped.append(True))
        m.setattr(hub_link.platform, "system", lambda: "Linux")
        hub_link.set_service_running(True)
        hub_link.set_service_running(False)
    assert started == [hub_link._service_command("cron")]
    assert stopped == [True]
    # Only one link runs at a time
    lock = hub_link.acquire_lock()
    assert lock is not None
    with open(hub_link._pid_path()) as f:
        assert f.read() == str(os.getpid())
    assert hub_link.acquire_lock() is None
    lock.close()
    second = hub_link.acquire_lock()
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
    status = hub_link.get_workspace_status(wdir, fetch=False)
    assert status["errors"] == []
    git = status["status"]["git"]
    assert set(git["untracked_files"]) == {"notes.txt", "scratch.log"}
    # The Git part on its own says the same, without the pipeline's wait
    git_status = hub_link.get_workspace_git_status(wdir, fetch=False)
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
    assert hub_link.get_run_state(wdir) == {
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
    assert not hub_link.get_run_state(wdir)["running"]
    with open(lock, "w") as f:
        json.dump(
            {
                "read": {},
                "write": {"out.txt": {"pid": os.getpid(), "cmd": "x"}},
            },
            f,
        )
    assert hub_link.get_run_state(wdir) == {
        "running": True,
        "running_stages": ["train"],
        "running_since": "2026-09-29T12:05:00+00:00",
        "last_run": last_run,
    }
    with open(lock, "w") as f:
        f.write('{"read": {}, "write": {}}')
    assert hub_link.get_run_state(wdir)["last_run"] == last_run
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
            hub_link.save_workspace(wdir, [bad])
        with pytest.raises(ValueError):
            hub_link.ignore_path(wdir, bad)
        with pytest.raises(ValueError):
            hub_link.add_stage(wdir, name="bad", cmd="echo", deps=[bad])
    if sys.platform != "win32":
        os.symlink(str(tmp_path), os.path.join(wdir, "link"))
        with pytest.raises(ValueError):
            hub_link.save_workspace(wdir, ["link/secret"])
        os.remove(os.path.join(wdir, "link"))
        # Nor are files a repo committed as links followed out of it, e.g.,
        # a .gitignore linked to ~/.bashrc, or a pipeline linked elsewhere
        with open(outside, "w") as f:
            f.write("export SECRET=1\n")
        for fname in [".gitignore", "dvc.yaml", "calkit.yaml"]:
            moved = os.path.join(wdir, fname + ".real")
            had = os.path.lexists(os.path.join(wdir, fname))
            if had:
                os.rename(os.path.join(wdir, fname), moved)
            os.symlink(outside, os.path.join(wdir, fname))
            with pytest.raises(ValueError, match="link"):
                if fname == ".gitignore":
                    hub_link.ignore_path(wdir, "scratch.log")
                else:
                    hub_link.add_stage(wdir, name="s", cmd="echo", outs=["o"])
            if fname == "dvc.yaml":
                assert hub_link.get_stage_list(wdir, None) == []
            os.remove(os.path.join(wdir, fname))
            if had:
                os.rename(moved, os.path.join(wdir, fname))
        with open(outside) as f:
            assert f.read() == "export SECRET=1\n"
        # Or a log named like the latest run's
        logs = os.path.join(wdir, ".calkit", "logs")
        os.makedirs(logs)
        os.symlink(outside, os.path.join(logs, "9999-zz.log"))
        assert hub_link.get_run_log(wdir) == {"name": None, "log": None}
        shutil.rmtree(os.path.join(wdir, ".calkit"))
        os.remove(outside)
    # The machine's credentials never go in a commit, even when a repo's
    # own .gitignore lets them through, nor anything else of this machine's
    dvc_ignore = os.path.join(wdir, ".dvc", ".gitignore")
    with open(dvc_ignore) as f:
        dvc_ignored = f.read()
    with open(dvc_ignore, "w") as f:
        f.write("/tmp\n/cache\n")
    local_config = os.path.join(wdir, ".dvc", "config.local")
    with open(local_config, "w") as f:
        f.write(
            "['remote \"calkit\"']\n"
            "    url = HTTPS://attacker.example/dvc\n"
            "    custom_auth_header = Authorization\n"
            "    password = Bearer ckp_token\n"
        )
    for bad_paths in [
        [".dvc"],
        [".dvc/config.local"],
        [".DVC/Config.local"],
        ["."],
    ]:
        with pytest.raises(ValueError, match="credentials"):
            hub_link.save_workspace(wdir, bad_paths)
    with open(dvc_ignore, "w") as f:
        f.write(dvc_ignored)

    def committed() -> list[str]:
        return subprocess.run(
            ["git", "show", "--name-only", "--format="],
            cwd=wdir,
            capture_output=True,
            text=True,
        ).stdout.split()

    # Ignoring commits only the .gitignore change, leaving what the user
    # staged
    subprocess.run(["git", "add", "notes.txt"], cwd=wdir, check=True)
    hub_link.ignore_path(wdir, "scratch.log")
    assert committed() == [".gitignore"]
    subprocess.run(["git", "reset", "-q", "notes.txt"], cwd=wdir, check=True)
    status = hub_link.get_workspace_status(wdir, fetch=False)
    assert status["status"]["git"]["untracked_files"] == ["notes.txt"]
    assert status["status"]["git"]["changed_files"] == []
    # Saving commits only what it's given, leaving what the user staged
    with open(os.path.join(wdir, "staged.txt"), "w") as f:
        f.write("staged")
    subprocess.run(["git", "add", "staged.txt"], cwd=wdir, check=True)
    hub_link.save_workspace(wdir, ["notes.txt"], message="Add notes", to="git")
    assert "notes.txt" in committed() and "staged.txt" not in committed()
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=wdir,
        capture_output=True,
        text=True,
    )
    assert staged.stdout.split() == ["staged.txt"]
    subprocess.run(["git", "rm", "-qf", "staged.txt"], cwd=wdir, check=True)
    status = hub_link.get_workspace_status(wdir, fetch=False)
    assert status["status"]["git"]["untracked_files"] == []
    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=wdir, capture_output=True, text=True
    ).stdout.splitlines()
    assert log[:2] == ["Add notes", "Ignore scratch.log"]
    # Stages are added and committed, with an object for their output
    hub_link.add_stage(
        wdir,
        name="plot",
        cmd="python plot.py",
        outs=["fig.png"],
        calkit_type="figure",
        calkit_object={"title": "A plot", "description": "It plots"},
    )
    assert sorted(committed()) == ["calkit.yaml", "dvc.yaml"]
    with pytest.raises(ValueError):
        hub_link.add_stage(wdir, name="plot", cmd="echo")
    with pytest.raises(ValueError):
        hub_link.add_stage(wdir, name="other", cmd="echo", outs=["fig.png"])
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
        hub_link.add_stage(
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
    result = hub_link.run_pipeline(wdir)
    assert result["ok"] is False
    assert result["output"]
    # Single stages can be run, and their names can't be options
    result = hub_link.run_pipeline(wdir, stages=["plot"])
    assert result["ok"] is False and "plot" in result["output"]
    for bad in ["--force", "-f", "a b", "x;y", ""]:
        with pytest.raises(ValueError):
            hub_link.run_pipeline(wdir, stages=[bad])
    # The hub follows a run through its log, named by when it started
    run_log = hub_link.get_run_log(wdir)
    assert run_log["name"].endswith(".log") and "plot" in run_log["log"]
    # Only the end of a run's output and its log is kept, however long
    with open(os.path.join(local, "logs", "9999-zz.log"), "w") as f:
        f.write("old\n" + "x" * 300_000 + "\nEND")
    run_log = hub_link.get_run_log(wdir)
    assert len(run_log["log"]) == 50_000 and run_log["log"].endswith("END")
    os.remove(os.path.join(local, "logs", "9999-zz.log"))
    with monkeypatch.context() as m:
        m.setattr(
            hub_link,
            "CALKIT_COMMAND",
            [sys.executable, "-c", "print('y' * 300_000, end='END')"],
        )
        result = hub_link.run_pipeline(wdir)
    assert result["ok"] and len(result["output"]) == 50_000
    assert result["output"].endswith("END")
    # Output that isn't text doesn't stop it being read
    with monkeypatch.context() as m:
        m.setattr(
            hub_link,
            "CALKIT_COMMAND",
            [
                sys.executable,
                "-c",
                "import sys; "
                "sys.stdout.buffer.write(b'\\xff' * 100_000 + b'END')",
            ],
        )
        result = hub_link.run_pipeline(wdir)
    assert result["ok"] and result["output"].endswith("END")
    # Stopping needs a run in progress, and a run the hub started stops
    # with everything it started
    with pytest.raises(ValueError):
        hub_link.stop_run(wdir)
    if sys.platform != "win32":
        sleeper = subprocess.Popen(["sleep", "30"], start_new_session=True)
        hub_link._runs[wdir] = sleeper
        try:
            hub_link.stop_run(wdir)
            assert sleeper.wait(timeout=10) != 0
        finally:
            hub_link._runs.pop(wdir, None)
    # Another workspace for the project goes beside it in ~/calkit, where
    # it's found, and branch names can't be options or climb out of there
    created = hub_link.new_workspace(wdir, "fix/axes")
    assert created["path"] == os.path.join(tmp_path, "calkit", "demo-fix-axes")
    assert created["path"] in [
        ws["path"] for ws in hub_link.discover_workspaces({"workspaces": []})
    ]
    for bad in ["--force", "-b", "../up", "a b", ""]:
        with pytest.raises(ValueError):
            hub_link.new_workspace(wdir, bad)
    # One from a worktree is named after the main checkout
    wt = os.path.join(tmp_path, "dev", "demo-wt")
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "wt", wt], cwd=wdir, check=True
    )
    created = hub_link.new_workspace(wt, "from-wt")
    assert created["path"] == os.path.join(tmp_path, "calkit", "demo-from-wt")
    # A calkit package in the workspace, e.g., in a checkout of Calkit
    # itself, doesn't stand in for the link's own
    os.makedirs(os.path.join(wt, "calkit"))
    with open(os.path.join(wt, "calkit", "__init__.py"), "w") as f:
        f.write("raise SystemExit('shadowed')\n")
    hub_link._calkit(["--version"], wt)
    # One from ~/dev goes beside it, and one from elsewhere in ~/calkit
    calls: list[list[str]] = []
    with monkeypatch.context() as m:
        m.setattr(hub_link, "_calkit", lambda args, wdir: calls.append(args))
        for source, parent in [
            (os.path.join(tmp_path, "dev", "tool"), "dev"),
            (os.path.join(tmp_path, "src", "tool"), "calkit"),
        ]:
            made = hub_link.new_workspace(source, "x")
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
    hub_link.save_workspace(wdir, ["big.csv.dvc", ".gitignore"], to="git")
    with open(os.path.join(wdir, "big.csv"), "w") as f:
        f.write("3,4\n")
    with open(os.path.join(wdir, "notes.txt"), "w") as f:
        f.write("changed")
    status = hub_link.get_workspace_status(wdir, fetch=False)
    assert status["status"]["dvc"]["uncommitted"]["modified"] == ["big.csv"]
    assert status["status"]["git"]["changed_files"] == ["notes.txt"]
    result = hub_link.discard_changes(wdir)
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
    assert hub_link.discard_changes(wdir) == {"stashed": True}
    with open(os.path.join(wdir, "big.csv")) as f:
        assert f.read() == "1,2\n"
    assert hub_link.discard_changes(wdir) == {"stashed": False}
    # Cloning puts a project under ~/calkit, where it's a workspace, and
    # won't clone over anything or outside it
    calls = []
    monkeypatch.setattr(
        hub_link, "_calkit", lambda args, wdir: calls.append(args)
    )
    url = "https://github.com/someone/other"
    path = hub_link.clone_project(url)
    assert path == os.path.join(tmp_path, "calkit", "other")
    assert calls == [["clone", url, path, "--no-dvc-pull"]]
    # Or into a folder chosen for it in the home folder, which is created
    calls.clear()
    path = hub_link.clone_project(url, "~/work/other-copy")
    assert path == os.path.join(tmp_path, "work", "other-copy")
    assert calls == [["clone", url, path, "--no-dvc-pull"]]
    assert os.path.isdir(os.path.join(tmp_path, "work"))
    for bad_path in [
        "relative/path",
        "~",
        "/etc/other",
        "~/../other",
        "~/.ssh/other",
        "~/work/.hidden",
        "~/calkit/demo",
    ]:
        with pytest.raises(ValueError):
            hub_link.clone_project(url, bad_path)

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
    stages = hub_link.get_stage_list(
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
    assert hub_link.get_stage_list(str(tmp_path), None) == []
    # Without the status, every stage is there, with no state or questions
    quick = hub_link.get_workspace_stages(pipeline_dir)["stages"]
    assert [s["name"] for s in quick] == ["fetch", "sim", "plot", "other"]
    assert {s["state"] for s in quick} == {None}
    assert quick[2]["kind"] == "python-script" and not quick[2]["questions"]

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
    # DVC pulls with Calkit there, which clears the hub's token from
    # remotes the repo points elsewhere using the project's hub, not the
    # link's
    calls.clear()
    assert hub_link.pull_workspace(wdir) == {"diverged": False}
    assert os.path.isfile(os.path.join(wdir, "a.txt"))
    assert calls == [["dvc", "pull"]]
    commit("b.txt", "b", other)
    git("push", "-q", cwd=other)
    commit("c.txt", "c", wdir)
    assert hub_link.pull_workspace(wdir) == {"diverged": True}
    assert not os.path.isfile(os.path.join(wdir, "b.txt"))
    assert hub_link.pull_workspace(wdir, merge=True) == {"diverged": False}
    assert os.path.isfile(os.path.join(wdir, "b.txt"))
    commit("notes.txt", "theirs", other)
    git("push", "-q", cwd=other)
    commit("notes.txt", "ours", wdir)
    with pytest.raises(ValueError, match="notes.txt"):
        hub_link.pull_workspace(wdir, merge=True)
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
            hub_link.clone_project(bad)


def test_trim_status():
    paths = [f"data/{i}.csv" for i in range(500)]
    status: dict[str, Any] = {
        "pipeline": {
            "stale_stage_names": ["a", "b"],
            "stale_stages": {
                "a": {
                    "modified_inputs": paths,
                    "stale_outputs": ["out.csv"],
                    "raw_status": [{"big": paths}],
                    "ignored_files_in_inputs": {"x": paths},
                    "modified_command": True,
                },
                "b": {"modified_outputs": paths[:3]},
            },
        },
        "dvc": {
            "unchanged": paths,
            "not_in_cache": paths,
            "uncommitted": {"modified": paths, "deleted": paths[:2]},
            "committed": {},
        },
    }
    # What isn't shown is dropped and long lists shortened to a count
    hub_link.trim_status(status)
    a = status["pipeline"]["stale_stages"]["a"]
    assert a == {
        "modified_inputs": paths[: hub_link.MAX_STALE_PATHS],
        "modified_inputs_count": 500,
        "stale_outputs": ["out.csv"],
        "modified_command": True,
    }
    assert status["pipeline"]["stale_stages"]["b"] == {
        "modified_outputs": paths[:3]
    }
    dvc = status["dvc"]
    assert "unchanged" not in dvc
    assert dvc["not_in_cache_count"] == 500
    assert len(dvc["uncommitted"]["modified"]) == hub_link.MAX_CHANGED_PATHS
    assert dvc["uncommitted"]["deleted"] == paths[:2]
    # Too large even so, why stages are stale goes, but not which are
    hub_link.trim_status(status, max_bytes=100)
    assert status["pipeline"]["stale_stages"] == {}
    assert status["pipeline"]["stale_stage_names"] == ["a", "b"]


def test_machine_setup(tmp_path, monkeypatch):
    import keyring.errors

    from calkit import config

    home = os.path.realpath(tmp_path)
    monkeypatch.setenv("CALKIT_USER_HOME", home)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("XDG_CONFIG_HOME", os.path.join(home, ".config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ["GIT_CONFIG_GLOBAL", "GIT_SSH_COMMAND"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "supports_keyring", lambda: False)
    # A repository the project's URL leads to, without the network
    remote = os.path.join(home, "remote.git")
    subprocess.run(["git", "init", "-q", "--bare", remote], check=True)
    url = "https://example.com/someone/demo"
    subprocess.run(
        ["git", "config", "--global", f"url.file://{remote}.insteadOf", url],
        check=True,
    )
    # A fresh machine has no Git identity or token, but can reach an empty
    # repository
    setup = hub_link.check_machine_setup(url)
    assert setup == {
        "git_name": None,
        "git_email": None,
        "repo": {"host": "example.com", "ssh": False, "error": None},
        "token": False,
    }
    # One it can't reach says why
    missing = "https://example.com/someone/missing"
    subprocess.run(
        [
            "git",
            "config",
            "--global",
            f"url.file://{home}/nowhere.git.insteadOf",
            missing,
        ],
        check=True,
    )
    assert hub_link.check_machine_setup(missing)["repo"]["error"]
    ssh = hub_link.check_machine_setup("git@example.com:someone/demo.git")
    assert ssh["repo"]["host"] == "example.com" and ssh["repo"]["ssh"]
    # What the hub runs can't prompt for a password, unless the user chose
    # how Git runs SSH
    env = hub_link.no_prompt_env(home)
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    assert "accept-new" not in env["GIT_SSH_COMMAND"]
    subprocess.run(
        ["git", "config", "--global", "core.sshCommand", "ssh -i key"],
        check=True,
    )
    assert "GIT_SSH_COMMAND" not in hub_link.no_prompt_env(home)
    subprocess.run(
        ["git", "config", "--global", "--unset", "core.sshCommand"],
        check=True,
    )
    # What's missing can be set from the hub, which hands the token to the
    # link over HTTPS when the owner asked for one, never through the
    # relay
    from requests.exceptions import HTTPError

    from calkit.hub import core as hub

    token = "ckp_" + "ab" * 32
    cfg = {"token": "ckm_op", "api_url": "https://api.hub"}
    hub_token: dict[str, str] | None = {"token": token}
    requests: list[tuple[str, str, dict]] = []

    def request(kind: str, path: str, **kwargs: Any) -> dict | None:
        requests.append((kind, path, kwargs))
        if hub_token is None:
            response = SimpleNamespace(status_code=403)
            raise HTTPError("403: No token was requested", response=response)
        return hub_token

    monkeypatch.setattr(hub, "_request", request)
    hub_link.configure_machine(
        git_name=" Ada Lovelace ",
        git_email="ada@example.com",
        token=True,
        cfg=cfg,
    )
    ((kind, req_path, kwargs),) = requests
    assert (kind, req_path) == ("post", "/machines/cli-token")
    assert kwargs["headers"] == {"Authorization": "Bearer ckm_op"}
    assert kwargs["base_url"] == "https://api.hub" and not kwargs["auth"]
    setup = hub_link.check_machine_setup(url)
    assert setup["git_name"] == "Ada Lovelace"
    assert setup["git_email"] == "ada@example.com"
    assert setup["token"]
    assert config.read().token == token
    # But nothing that isn't what it says it is, including a token sent
    # with the request, as the relay could
    bad_kwargs: list[dict[str, Any]] = [
        {"git_name": ""},
        {"git_name": "a\n[core]\n\tsshCommand = evil"},
        {"git_name": ["x"]},
        {"git_email": "not-an-email"},
        {"token": token},
        {"token": "abc"},
        {"token": True},
    ]
    for kwargs in bad_kwargs:
        with pytest.raises(ValueError):
            hub_link.configure_machine(**kwargs)
    # Nor one the hub didn't hand out, or one it sent wrong
    for hub_token in [None, {"token": token + "\n"}, {}]:
        with pytest.raises(ValueError):
            hub_link.configure_machine(token=True, cfg=cfg)
    hub_token = {"token": token}
    assert hub_link.check_machine_setup(url)["git_name"] == "Ada Lovelace"
    bad_urls: list[Any] = [
        "",
        "/etc",
        "--upload-pack=touch /tmp/x",
        "https://example.com",
        "https://user@example.com/someone/demo",
        "https://example.com/someone/demo extra",
        "https://example.com/someone/demo\nx",
        "git@-oProxyCommand=x:someone/demo",
        "git@example.com:-x",
        "ssh://example.com/someone/demo",
        ["https://example.com/someone/demo"],
    ]
    for bad in bad_urls:
        with pytest.raises(ValueError):
            hub_link.check_machine_setup(bad)

    # A keyring that can't be reached, e.g., from a service started at
    # boot, says what to do instead
    def locked(self):
        raise keyring.errors.KeyringError("locked")

    monkeypatch.setattr(config.Settings, "write", locked)
    with pytest.raises(RuntimeError, match="calkit config set token"):
        hub_link.configure_machine(token=True, cfg=cfg)
    # A machine with no SSH key gets one to add to the Git host, and one that
    # has a key keeps it
    if shutil.which("ssh-keygen"):
        made = hub_link.get_ssh_public_key()
        assert made["created"] and made["public_key"].startswith("ssh-ed25519")
        assert os.path.isfile(os.path.join(home, ".ssh", "id_ed25519"))
        assert hub_link.get_ssh_public_key() == dict(made, created=False)
    # A clone outside the folders workspaces are found in is added to them,
    # so the hub lists it
    sent: list[dict] = []
    saved: list[dict] = []
    op = hub_link.HubLink({"workspaces": []})

    async def send(ch, msg):
        sent.append(msg)

    async def check_in():
        return {}

    monkeypatch.setattr(op, "send", send)
    monkeypatch.setattr(op, "check_in", check_in)
    monkeypatch.setattr(hub_link, "save_config", saved.append)
    monkeypatch.setattr(
        hub_link,
        "clone_project",
        lambda u, p: os.path.join(
            home, *(p[2:].split("/") if p else ["calkit", "demo"])
        ),
    )
    for path in [None, "~/work/demo"]:
        asyncio.run(
            op.run_action(
                "ch",
                {"type": "workspaces.clone", "id": 1, "git_repo_url": url}
                | ({"path": path} if path else {}),
            )
        )
    assert [m["result"]["path"] for m in sent] == [
        os.path.join(home, "calkit", "demo"),
        os.path.join(home, "work", "demo"),
    ]
    assert op.cfg["workspaces"] == [os.path.join(home, "work", "demo")]
    assert len(saved) == 1
    # Git status doesn't fetch while something other than a run holds the
    # workspace, e.g., a pull, which it would race for Git's ref locks
    fetched: list[bool] = []
    monkeypatch.setitem(
        hub_link.WORKSPACE_ACTIONS,
        "workspace.git_status",
        lambda wdir, fetch=True: fetched.append(fetch) or {},
    )
    monkeypatch.setattr(op, "get_workspace", lambda path, personal: "/ws")
    for holding in [None, "workspace.run", "workspace.pull"]:
        op.workspace_actions.pop("/ws", None)
        if holding is not None:
            op.workspace_actions["/ws"] = holding
        msg = {"type": "workspace.git_status", "id": 2, "workspace": "w"}
        asyncio.run(op.run_action("ch", msg | {"fetch": True}))
    op.workspace_actions.clear()
    assert fetched == [True, True, False]


def test_install_remote(monkeypatch):
    import yaml

    from calkit import workspace as ws
    from calkit.hub import core as hub

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
    from requests.exceptions import HTTPError

    posted = {}
    # The user's active machines, as the hub lists them
    active = []

    def request(kind, path, json=None, **kwargs):
        if kind == "get":
            # Asked with the machine's own token, so it works there too
            assert path == "/machines/self" and kwargs["auth"] is False
            if not active:
                raise HTTPError(response=SimpleNamespace(status_code=403))
            return active[-1]
        posted.update(json)
        active.append({"id": "op1"})
        return {"id": "op1", "name": "login1-cluster", "user_id": "u1"} | {
            "token": "ckm_secret",
            "grant_public_key": "key",
        }

    monkeypatch.setattr(hub, "_request", request)
    monkeypatch.setattr(hub, "get_base_url", lambda: "https://api.hub")
    runs = []
    remote_config = {"text": ""}

    uid = ["1000"]

    def run(argv, **kwargs):
        runs.append((argv, kwargs.get("input")))
        if "cat ~/.calkit/hubs/calkit.io/link.yaml 2>" in argv[-1]:
            # Anything a login prints comes first
            return SimpleNamespace(
                stdout=f"Welcome\ncalkit-uid={uid[0]}\n{remote_config['text']}"
            )
        if fail_install and "calkit hub link install --hub" in argv[-1]:
            raise subprocess.CalledProcessError(1, argv)
        return SimpleNamespace(stdout="")

    fail_install = False
    monkeypatch.setattr(hub_link.subprocess, "run", run)
    cfg = hub_link.install_remote("cluster", cron=True)
    # Registered from here with the far end's own details
    assert posted["hostname"] == "login1.cluster"
    assert posted["platform"] == "linux"
    assert posted["hosts"] == ["cluster", "login1.cluster"]
    # without its key, which the link there sends at its first
    # check-in
    assert "public_key" not in posted
    # Its config goes over SSH, readable only by the user, then Calkit there
    # installs it in the mode asked for
    _, (write_argv, config_text), (install_argv, _) = runs
    assert write_argv[0] == "ssh" and "cluster" in write_argv
    assert "umask 077" in write_argv[-1]
    assert yaml.safe_load(config_text) == cfg
    assert cfg["token"] == "ckm_secret" and cfg["api_url"] == "https://api.hub"
    assert (
        "calkit hub link install --hub https://calkit.io --cron"
        in install_argv[-1]
    )
    # It goes where the other machine keeps its link to this hub
    assert "~/.calkit/hubs/calkit.io/link.yaml" in write_argv[-1]
    # Reinstalling keeps the machine already there
    remote_config["text"] = config_text
    posted.clear()
    runs.clear()
    assert hub_link.install_remote("cluster") == cfg
    assert posted == {}
    assert len(runs) == 2
    # Starting at login is passed along
    runs.clear()
    hub_link.install_remote("cluster", login=True)
    assert runs[-1][0][-1].endswith("--login'")
    # One that was revoked is registered again rather than kept, since it
    # would exit at its first check-in
    active.clear()
    runs.clear()
    hub_link.install_remote("cluster")
    assert posted["hostname"] == "login1.cluster"
    assert len(runs) == 3
    # As is one whose key the hub refused, which is revoked with its own
    # token first
    deleted = []
    monkeypatch.setattr(
        hub,
        "_request",
        lambda kind, path, **kw: (
            deleted.append((path, kw.get("headers")))
            if kind == "delete"
            else request(kind, path, **kw)
        ),
    )
    remote_config["text"] = yaml.safe_dump(cfg | {"key_rejected": True})
    posted.clear()
    runs.clear()
    hub_link.install_remote("cluster")
    assert posted["hostname"] == "login1.cluster"
    assert deleted == [
        ("/machines/self", {"Authorization": "Bearer ckm_secret"})
    ]
    # A registration whose install fails is revoked, with its own token,
    # since the user's may not be from a sign-in that can
    remote_config["text"] = ""
    fail_install = True
    deleted.clear()
    with pytest.raises(subprocess.CalledProcessError):
        hub_link.install_remote("cluster")
    assert deleted == [
        ("/machines/self", {"Authorization": "Bearer ckm_secret"})
    ]
    # Sessions would be root shells, so it's never installed as root there
    uid[0] = "0"
    posted.clear()
    with pytest.raises(ValueError, match="root"):
        hub_link.install_remote("root@cluster")
    assert posted == {}


def test_hubs(tmp_path, monkeypatch):

    home = str(tmp_path)
    monkeypatch.setenv("CALKIT_USER_HOME", home)
    # Each hub's link has its own config, service, lock, and log, keyed
    # like its managed workspaces, so they can run side by side
    monkeypatch.setenv("CALKIT_HUB", "https://calkit.io")
    keys = {}
    for url in ["https://calkit.io", "localhost", "http://localhost:5173"]:
        keys[url] = hub_link.select_hub(url)
        hub_link.save_config({"name": url, "hub_url": hub_link.get_hub_url()})
    assert keys == {
        "https://calkit.io": "calkit.io",
        "localhost": "localhost",
        "http://localhost:5173": "localhost-5173",
    }
    assert sorted(hub_link.list_configured_hubs()) == [
        "http://localhost",
        "http://localhost:5173",
        "https://calkit.io",
    ]
    names = set()
    for url in keys:
        hub_link.select_hub(url)
        assert hub_link.load_config()["name"] == url
        names.add(
            (
                hub_link.get_config_path(),
                hub_link.get_log_path(),
                hub_link._pid_path(),
                hub_link.service_label(),
                hub_link.systemd_unit(),
                hub_link.cron_marker(),
                hub_link._windows_startup_path(),
            )
        )
    assert len(names) == 3
    assert len({n for group in names for n in group}) == 21
    # One hub's cron entries are never taken for another's, even when one
    # key starts with the other
    hub_link.select_hub("localhost")
    lines = [f"* * * * * x {hub_link.cron_marker(k)}" for k in keys.values()]
    assert [
        line for line in lines if line.endswith(hub_link.cron_marker())
    ] == ["* * * * * x # calkit-hub-link localhost"]


def test_workspace_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    wdir = os.path.join(tmp_path, "calkit", "demo")
    _init_project(wdir)
    # A link takes a workspace while using it, in a lock inside the
    # workspace that Git ignores, and can take it again
    hub_link.claim_workspace(wdir)
    hub_link.claim_workspace(wdir)
    holder = hub_link.workspace_lock_holder(wdir)
    assert holder["pid"] == os.getpid()
    assert holder["hub"] == "https://calkit.io"
    with open(os.path.join(wdir, ".calkit", "local", ".gitignore")) as f:
        assert f.read() == "*\n"
    hub_link.release_workspace(wdir)
    assert hub_link.workspace_lock_holder(wdir) is None
    # Another hub's link using it keeps this one out, and shows on the
    # hub, until it stops, which leaves a stale lock anyone can take
    other = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", "hub link start"]
    )
    try:
        with open(
            os.path.join(wdir, ".calkit", "local", "hub-link.lock"), "w"
        ) as f:
            json.dump({"hub": "http://localhost", "pid": other.pid}, f)
        # Without saying which hub, which is none of this one's business
        with pytest.raises(ValueError, match="another hub"):
            hub_link.claim_workspace(wdir)
        (ws,) = [
            w
            for w in hub_link.discover_workspaces({})
            if w["path"] == os.path.realpath(wdir)
        ]
        assert ws["in_use_by"] == "another hub"
        # One the repo committed was written by no link
        subprocess.run(
            ["git", "add", "-f", hub_link.LOCK_PATH], cwd=wdir, check=True
        )
        assert hub_link.workspace_lock_holder(wdir) is None
        subprocess.run(
            ["git", "rm", "-q", "--cached", hub_link.LOCK_PATH],
            cwd=wdir,
            check=True,
        )
        assert hub_link.workspace_lock_holder(wdir) is not None
    finally:
        other.kill()
        other.wait()
    hub_link.claim_workspace(wdir)
    assert hub_link.workspace_lock_holder(wdir)["pid"] == os.getpid()
    hub_link.release_workspace(wdir)
    # Nor is a lock written through a link the repo committed
    if sys.platform != "win32":
        outside = tmp_path / "outside"
        outside.mkdir()
        shutil.rmtree(os.path.join(wdir, ".calkit", "local"))
        os.symlink(outside, os.path.join(wdir, ".calkit", "local"))
        with pytest.raises(ValueError):
            hub_link.claim_workspace(wdir)
        os.remove(os.path.join(wdir, ".calkit", "local"))
        os.makedirs(os.path.join(wdir, ".calkit", "local"))
        os.symlink(
            outside / "lock",
            os.path.join(wdir, ".calkit", "local", "hub-link.lock"),
        )
        assert hub_link.workspace_lock_holder(wdir) is None
        hub_link.claim_workspace(wdir)
        hub_link.release_workspace(wdir)
        assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_relay_connection(monkeypatch):
    import websockets.asyncio.client

    sent = []
    # What the relay sends, including what isn't JSON or an object
    incoming = ["not json", "[1]", '{"type": "first"}', '{"type": "second"}']

    class FakeSocket:
        async def send(self, text):
            sent.append(json.loads(text))

        def __aiter__(self):
            return self

        async def __anext__(self):
            if incoming:
                return incoming.pop(0)
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
    op = hub_link.HubLink({"name": "box", "workspaces": []})
    check_ins = []

    async def check_in():
        check_ins.append(op.ws is not None)
        return {}

    monkeypatch.setattr(op, "check_in", check_in)
    handled = []

    # One that fails to be handled doesn't end the connection
    def on_relay_message(frame: dict) -> None:
        handled.append(frame["type"])
        raise TypeError("unhashable type: 'list'")

    monkeypatch.setattr(op, "on_relay_message", on_relay_message)
    await op.connect({"relay_url": "wss://relay.hub", "relay_token": "tok"})
    await op.connected_check_in
    assert handled == ["first", "second"]
    # The token goes in the first message, and the link checks in as
    # connected right away, so the hub doesn't show it offline until the
    # next regular check-in
    assert sent == [{"type": "auth", "token": "tok"}]
    assert check_ins == [True]


def test_restarts(tmp_path, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    monkeypatch.setattr(hub_link, "RESTART_CHECK_SECONDS", 0.01)
    monkeypatch.setattr(hub_link.calkit, "__version__", "1.0.0")
    installed = ["1.0.0"]
    monkeypatch.setattr(
        hub_link, "get_installed_version", lambda: installed[0]
    )
    op = hub_link.HubLink({"name": "box", "workspaces": []})
    assert not op.restart_pending()
    # A new version installed under it, e.g., by an automatic upgrade
    installed[0] = "1.1.0"
    assert op.restart_pending()
    installed[0] = "1.0.0"
    # A request from 'calkit upgrade' is read once
    pids = {"calkit.io": 123, "other.hub": None}
    for key in pids:
        os.makedirs(hub_link.link_dir(key))
    monkeypatch.setattr(
        hub_link, "get_running_pid", lambda key=None: pids[key]
    )
    assert hub_link.request_restarts() == [("calkit.io", 123)]
    assert not os.path.exists(hub_link._restart_request_path("other.hub"))
    assert op.restart_pending()
    assert not os.path.exists(hub_link._restart_request_path())
    assert op.restart_requested and not op.stop_requested
    # As is one from the hub, which comes with a check-in
    op.restart_requested = False
    assert not op.restart_pending()
    reported: list[bool] = []

    def check_in(cfg, workspaces, mode, connected, pending, sessions) -> dict:
        reported.append(pending)
        return {"restart": True}

    monkeypatch.setattr(hub_link, "discover_workspaces", lambda cfg: [])
    monkeypatch.setattr(hub_link, "check_in", check_in)
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
        stopping = hub_link.HubLink({"name": "box", "workspaces": []})
        hub_link.request_restarts(stop=True)
        await asyncio.wait_for(stopping.wait_to_restart(), 1)
        assert stopping.stop_requested and not stopping.restarting

    asyncio.run(wait_for_idle())
    # Restarting replaces the process with one running the same way
    execs = []
    monkeypatch.setattr(hub_link.os, "execv", lambda *a: execs.append(a))
    platform = hub_link.sys.platform
    monkeypatch.setattr(hub_link.sys, "platform", "linux")
    hub_link.restart_process("service")
    cmd = hub_link._service_command("service")
    assert execs == [(cmd[0], cmd)]
    monkeypatch.setattr(hub_link.sys, "platform", platform)
    # Run restarts once its link stops for one, and drops requests left
    # from before it started
    restarts: list[str] = []
    monkeypatch.setattr(hub_link, "restart_process", restarts.append)

    async def stop_to_restart(self) -> None:
        self.restarting = True

    monkeypatch.setattr(hub_link.HubLink, "run", stop_to_restart)
    # Left alone, so SIGTERM still ends the tests that follow
    monkeypatch.setattr("signal.signal", lambda *args: None)
    hub_link.request_restarts()
    assert hub_link.run({"name": "box", "workspaces": []}, mode="service")
    assert restarts == ["service"]
    assert not os.path.exists(hub_link._restart_request_path())
