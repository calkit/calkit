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

    from calkit import hub

    keys = iter(["key1", "key2"])
    posted = []

    def request(*args: Any, **kwargs: Any) -> dict:
        posted.append(kwargs["json"])
        return {"grant_public_key": next(keys)}

    monkeypatch.setattr(hub, "_request", request)
    cfg = {"token": "cko_x", "api_url": "https://api.hub", "workspaces": []}
    operator.check_in(cfg, [], "service")
    assert (operator.load_config() or {})["grant_public_key"] == "key1"
    operator.check_in(cfg, [], "service")
    assert (operator.load_config() or {})["grant_public_key"] == "key2"
    # The Operator's own public key goes with each, which the hub keeps
    # the first time, for browsers to check replies with
    assert posted[0]["public_key"] == operator.get_operator_public_jwk()
    assert posted[1]["public_key"] == posted[0]["public_key"]
    # A hub that has another key for it is refused, and installing again
    # registers it anew
    response = SimpleNamespace(status_code=409)

    def conflict(*args: Any, **kwargs: Any) -> dict:
        raise HTTPError("409: Operator key doesn't match", response=response)

    monkeypatch.setattr(hub, "_request", conflict)
    with pytest.raises(operator.OperatorKeyRejected):
        operator.check_in(cfg, [], "service")
    assert (operator.load_config() or {})["key_rejected"]
    # Revoked, it stops
    response.status_code = 403
    with pytest.raises(operator.OperatorRevoked) as revoked:
        operator.check_in(cfg, [], "service")
    assert not isinstance(revoked.value, operator.OperatorKeyRejected)
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
        "dev/odd",
        "src/other",
        ".calkit/workspaces/calkit.io/alice/demo",
    }
    assert workspaces["dev/odd"]["project"] is None
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
            assert {a["pid"] for a in operator.find_agents([wdir])[wdir]} == {
                claude,
                codex,
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
        log = operator.get_agent_log(wdir, claude)
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
        assert operator.get_agent_log(wdir, claude, limit=1)["entries"] == [
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
        "grant_public_key": public_key,
        "workspaces": [],
    }
    op = operator.Operator(cfg)
    op.workspaces = operator.discover_workspaces(op.cfg)
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
                f"{operator.MESSAGE_SIGNATURE_CONTEXT}\n{seq}\n{body}".encode(),
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

    def operator_public_key() -> Any:
        return operator.get_operator_key().public_key()

    def verify(signed: dict, grant_id: str) -> None:
        raw = base64.urlsafe_b64decode(signed["sig"] + "==")
        operator_public_key().verify(
            encode_dss_signature(
                int.from_bytes(raw[:32], "big"),
                int.from_bytes(raw[32:], "big"),
            ),
            f"{operator.REPLY_SIGNATURE_CONTEXT}\n{grant_id}\n"
            f"{signed['seq']}\n{signed['body']}".encode(),
            ec.ECDSA(hashes.SHA256()),
        )

    # Replies a browser would take, each signed by the Operator for its
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
    # this Operator, whatever the relay says, and each grant works once,
    # even after a restart
    open_channel("u", jti="used")
    op.on_relay_message({"type": "channel.close", "ch": "u"})
    restarted = operator.Operator(cfg)
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
        used_path = os.path.join(operator.operator_dir(), "used-grants.json")
        assert stat.S_IMODE(os.stat(used_path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(operator.operator_dir()).st_mode) == 0o700
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
    op.last_check_in = time.monotonic() - operator.CHECK_IN_GRACE_SECONDS
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
    # A channel's first reply says it's ready, signed with the Operator's
    # key for that channel's grant only, so the relay can't move replies
    # from one channel to another
    open_channel("a")
    await wait_for(lambda: sent())
    assert sent() == [("a", {"type": "channel.ready"})]
    first = json.loads(op.ws.sent[0])["msg"]
    with pytest.raises(InvalidSignature):
        verify(first, "another-grant")
    if sys.platform != "win32":
        key_path = os.path.join(operator.operator_dir(), "operator-key.pem")
        assert stat.S_IMODE(os.stat(key_path).st_mode) == 0o600
    # It's the key the hub is told about
    numbers = operator_public_key().public_numbers()
    jwk = operator.get_operator_public_jwk()
    assert jwk["kty"] == "EC" and jwk["crv"] == "P-256"
    assert operator._b64url_decode(jwk["x"]) == numbers.x.to_bytes(32, "big")
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
    # hub/frontend/src/components/Operators/connection.test.ts
    vector = {
        "jwk": {
            "kty": "EC",
            "crv": "P-256",
            "x": "QF8jZqZXlCI2kwXe6F3IGC3DlMRjap4e8f1DV0uWNiQ",
            "y": "GAhXTzjif_yPldGN07yo6alEe_o-IyFSC83KEKILGdE",
        },
        "seq": 7,
        "body": '{"type":"sessions.input","session":"s1","data":"ls ─\\n"}',
        "sig": (
            "Cml8CVzkHw2lLu6pU4A4BLtI17I6xUkJ_onoD76cKc10ZP4CjQ6_-XvcP3DmUqpn"
            "i_b8crjTTi1SDU8jBZpumw"
        ),
    }
    auth = operator.check_grant(op.cfg, grant(jwk=vector["jwk"]), {})
    assert auth is not None
    auth.seq = 6
    assert operator.open_signed_message(
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
    # A session doesn't get another's terminal, nor anything else the
    # Operator has open, which a shell that lists what it has shows
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
    # A second channel attaching gets the scrollback replayed
    open_channel("b")
    message("b", {"type": "sessions.attach", "id": 4, "session": sid})
    await wait_for(lambda: "HI-42" in output("b"))
    # Marked, so the browser doesn't answer queries in it a second time
    outputs = [(c, m) for c, m in sent() if m["type"] == "sessions.output"]
    assert all(m.get("replay") for c, m in outputs if c == "b")
    assert not any(
        m.get("replay") for c, m in outputs if c == "a" and "HI" in m["data"]
    )
    # Sessions outlive the channels attached to them
    op.on_relay_message({"type": "channel.close", "ch": "a"})
    op.on_relay_message({"type": "channel.close", "ch": "b"})
    assert op.sessions[sid].channels == set()
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
    # A reply too large for the relay is an error instead, and a browser too
    # far behind is closed
    message("c", {"type": "sessions.list", "id": 8})
    await wait_for(lambda: reply(8))
    clear()
    op.send_soon("c", {"type": "result", "id": 9, "result": "\x1b" * 100_000})
    await wait_for(lambda: reply(9))
    assert reply(9)["type"] == "error"
    monkeypatch.setattr(operator, "MAX_CHANNEL_BACKLOG_BYTES", 1000)
    open_channel("slow")
    op.send_soon("slow", {"data": "x" * 900})
    assert "slow" not in op.channels
    monkeypatch.setattr(operator, "MAX_CHANNEL_BACKLOG_BYTES", 2**20)
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

    monkeypatch.setattr(operator, "check_in", fake_check_in)
    monkeypatch.setattr(operator, "discover_workspaces", lambda cfg: [])
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

    monkeypatch.setattr(operator, "check_in", new_key)
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
    op.last_check_in = time.monotonic() - operator.CHECK_IN_GRACE_SECONDS
    op.expire_channels()
    assert op.channels == {}
    # With nothing using it, an Operator with an idle limit stops
    op.idle_exit_seconds = 0.1
    await asyncio.wait_for(op.wait_until_idle(), 5)


def test_log(tmp_path, monkeypatch):
    import logging

    # A log past its limit keeps its newest whole lines, in the same file
    # the service manager has open
    fpath = str(tmp_path / "operator.log")
    monkeypatch.setattr(operator, "LOG_MAX_BYTES", 100)
    monkeypatch.setattr(operator, "LOG_KEEP_BYTES", 50)
    monkeypatch.setattr(operator.sys, "platform", "linux")
    with open(fpath, "a") as service:
        service.write("".join(f"line {i:03d}\n" for i in range(20)))
        service.flush()
        operator.trim_log(fpath)
        service.write("after\n")
    with open(fpath) as f:
        lines = f.read().splitlines()
    assert lines[-1] == "after"
    assert lines[0].startswith("line ") and len(lines) < 10
    assert lines[-2] == "line 019"
    # Under the limit, or missing, it's left alone
    operator.trim_log(fpath)
    with open(fpath) as f:
        assert f.read().splitlines() == lines
    operator.trim_log(str(tmp_path / "missing.log"))
    # The same warning is only logged again after a while
    records = []
    log = logging.getLogger("test_operator_log")
    log.propagate = False
    log.setLevel(logging.INFO)
    log.addHandler(logging.Handler())
    log.handlers[0].emit = records.append  # type: ignore[method-assign]
    log.addFilter(operator.RepeatFilter())
    for _ in range(3):
        log.warning("Check-in failed: 404")
        log.warning("Connection failed: 404")
        log.info("Connected to relay")
    assert [r.getMessage() for r in records].count("Check-in failed: 404") == 1
    assert len([r for r in records if r.levelno == logging.INFO]) == 3
    monkeypatch.setattr(operator, "REPEAT_LOG_SECONDS", 0)
    log.warning("Check-in failed: 404")
    assert [r.getMessage() for r in records].count("Check-in failed: 404") == 2


def test_service_files(tmp_path, monkeypatch):
    import plistlib

    monkeypatch.setenv("CALKIT_USER_HOME", str(tmp_path))
    # Started from /, without what's there on the import path, so modules
    # in the home folder, e.g., a pty.py, can't stand in for its own
    command = [
        *operator.CALKIT_COMMAND,
        "operator",
        "start",
        "--hub",
        "https://calkit.io",
        "--mode",
        "service",
    ]
    (tmp_path / "typer.py").write_text("raise SystemExit('shadowed')\n")
    version = subprocess.run(
        [*operator.CALKIT_COMMAND, "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert version.returncode == 0, version.stderr
    # launchd restarts it on failure, but not after it exits because it
    # was revoked
    agent = plistlib.loads(operator._launchd_plist(at_boot=False))
    assert agent["ProgramArguments"] == command
    assert agent["KeepAlive"] == {"SuccessfulExit": False}
    assert agent["StandardOutPath"] == operator.get_log_path()
    assert agent["WorkingDirectory"] == "/"
    assert "UserName" not in agent
    # Not throttled like a background job
    assert agent["ProcessType"] == "Interactive"
    assert operator._launchd_plist_path(at_boot=False).startswith(
        str(tmp_path)
    )
    # At boot it's a system daemon that still runs as this user, which only
    # macOS has
    if sys.platform != "win32":
        daemon = plistlib.loads(operator._launchd_plist(at_boot=True))
        assert daemon["UserName"]
        # launchd opens its log as root, so the Operator writes its own
        assert daemon["StandardOutPath"] == "/dev/null"
        assert daemon["StandardErrorPath"] == "/dev/null"
        assert daemon["ProgramArguments"] == [*command, "--log-file"]
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
    expected = shlex.join(command).replace("\\", "\\\\")
    assert f"ExecStart={expected}" in unit
    assert "WorkingDirectory=/\n" in unit
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit
    # What systemd would expand in a path is escaped
    with monkeypatch.context() as m:
        m.setattr(
            operator, "CALKIT_COMMAND", ["/opt/py%x$y/python", "-c", "x"]
        )
        assert (
            "ExecStart='/opt/py%%x$$y/python' -c x" in operator._systemd_unit()
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

    monkeypatch.setattr(operator.subprocess, "run", run)
    monkeypatch.setattr(operator.os, "getuid", lambda: 501, raising=False)
    # Runners have no user 501, and Windows has no pwd module
    monkeypatch.setitem(
        sys.modules,
        "pwd",
        SimpleNamespace(getpwuid=lambda uid: SimpleNamespace(pw_name="me")),
    )
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

    monkeypatch.setattr(operator.subprocess, "run", run_install)
    monkeypatch.setattr(operator.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(operator, "_has_terminal", lambda: False)
    monkeypatch.setattr(operator.platform, "system", lambda: "Darwin")
    daemon_bootstrap = [
        "sudo",
        "-n",
        "launchctl",
        "bootstrap",
        "system",
        operator._launchd_plist_path(at_boot=True),
    ]
    agent_bootstrap = ["launchctl", "bootstrap", "gui/501", agent_path]
    for cached, login, bootstrap, noted in [
        (True, False, daemon_bootstrap, False),
        (False, False, agent_bootstrap, True),
        (True, True, agent_bootstrap, False),
    ]:
        sudo_cached[0] = cached
        calls.clear()
        notes = operator.install_service(login=login)
        assert bootstrap in calls
        assert any("needs sudo" in n for n in notes) == noted
        # Starting at login never asks for sudo
        if login:
            assert not any(c[:1] == ["sudo"] for c in calls)
    # On Linux, lingering is enabled with sudo if it can't be without, and
    # left alone when starting at login
    monkeypatch.setattr(operator.platform, "system", lambda: "Linux")
    user = os.environ.get("USER") or ""
    for cached, login, sudo_linger, noted in [
        (True, False, True, False),
        (False, False, False, True),
        (True, True, False, False),
    ]:
        sudo_cached[0] = cached
        calls.clear()
        notes = operator.install_service(login=login)
        assert (
            ["sudo", "-n", "loginctl", "enable-linger", user] in calls
        ) == sudo_linger
        assert any("enable-linger" in n for n in notes) == noted
        if login:
            assert not any("enable-linger" in c for c in calls)


@pytest.mark.skipif(sys.platform == "win32", reason="Cron and flock are POSIX")
def test_cron_and_lock(tmp_path, monkeypatch):
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
    operator.install_cron()
    operator.install_cron()
    lines = table.read_text().splitlines()
    assert lines[0] == "0 * * * * echo mine"
    ours = [line for line in lines if line.endswith(operator.cron_marker())]
    assert [line.split()[0] for line in ours] == ["*/5", "@reboot"]
    assert all("--mode cron" in line for line in ours)
    # From /, so nothing in the home folder is on its import path
    assert all(" cd / && " in line for line in ours)
    log = operator.get_log_path()
    assert "%" in log
    assert all(log.replace("%", "\\%") in line for line in ours)
    assert all("%" not in line.replace("\\%", "") for line in ours)
    # Its folder and log are the user's alone, e.g., on a shared login node
    assert stat.S_IMODE(os.stat(log).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(log)).st_mode) == 0o700
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
                    operator.ignore_path(wdir, "scratch.log")
                else:
                    operator.add_stage(wdir, name="s", cmd="echo", outs=["o"])
            if fname == "dvc.yaml":
                assert operator.get_stage_list(wdir, None) == []
            os.remove(os.path.join(wdir, fname))
            if had:
                os.rename(moved, os.path.join(wdir, fname))
        with open(outside) as f:
            assert f.read() == "export SECRET=1\n"
        # Or a log named like the latest run's
        logs = os.path.join(wdir, ".calkit", "logs")
        os.makedirs(logs)
        os.symlink(outside, os.path.join(logs, "9999-zz.log"))
        assert operator.get_run_log(wdir) == {"name": None, "log": None}
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
            operator.save_workspace(wdir, bad_paths)
    with open(dvc_ignore, "w") as f:
        f.write(dvc_ignored)
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
    # Only the end of a run's output and its log is kept, however long
    with open(os.path.join(local, "logs", "9999-zz.log"), "w") as f:
        f.write("old\n" + "x" * 300_000 + "\nEND")
    run_log = operator.get_run_log(wdir)
    assert len(run_log["log"]) == 50_000 and run_log["log"].endswith("END")
    os.remove(os.path.join(local, "logs", "9999-zz.log"))
    with monkeypatch.context() as m:
        m.setattr(
            operator,
            "CALKIT_COMMAND",
            [sys.executable, "-c", "print('y' * 300_000, end='END')"],
        )
        result = operator.run_pipeline(wdir)
    assert result["ok"] and len(result["output"]) == 50_000
    assert result["output"].endswith("END")
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
    # Or into a folder chosen for it in the home folder, which is created
    calls.clear()
    path = operator.clone_project(url, "~/work/other-copy")
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
            operator.clone_project(url, bad_path)

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
    # Without the status, every stage is there, with no state or questions
    quick = operator.get_workspace_stages(pipeline_dir)["stages"]
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
    # Pulling clears the hub's token from remotes the repo points elsewhere,
    # e.g., with a scheme in capitals, before DVC sends it there
    assert "ckp_token" in open(local_config).read()
    assert operator.pull_workspace(wdir) == {"diverged": False}
    assert os.path.isfile(os.path.join(wdir, "a.txt"))
    assert "ckp_token" not in open(local_config).read()
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
    setup = operator.check_machine_setup(url)
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
    assert operator.check_machine_setup(missing)["repo"]["error"]
    ssh = operator.check_machine_setup("git@example.com:someone/demo.git")
    assert ssh["repo"]["host"] == "example.com" and ssh["repo"]["ssh"]
    # What's missing can be set from the hub, which hands the token to the
    # Operator over HTTPS when the owner asked for one, never through the
    # relay
    from requests.exceptions import HTTPError

    from calkit import hub

    token = "ckp_" + "ab" * 32
    cfg = {"token": "cko_op", "api_url": "https://api.hub"}
    hub_token: dict[str, str] | None = {"token": token}
    requests: list[tuple[str, str, dict]] = []

    def request(kind: str, path: str, **kwargs: Any) -> dict | None:
        requests.append((kind, path, kwargs))
        if hub_token is None:
            response = SimpleNamespace(status_code=403)
            raise HTTPError("403: No token was requested", response=response)
        return hub_token

    monkeypatch.setattr(hub, "_request", request)
    operator.configure_machine(
        git_name=" Ada Lovelace ",
        git_email="ada@example.com",
        token=True,
        cfg=cfg,
    )
    ((kind, req_path, kwargs),) = requests
    assert (kind, req_path) == ("post", "/operators/cli-token")
    assert kwargs["headers"] == {"Authorization": "Bearer cko_op"}
    assert kwargs["base_url"] == "https://api.hub" and not kwargs["auth"]
    setup = operator.check_machine_setup(url)
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
            operator.configure_machine(**kwargs)
    # Nor one the hub didn't hand out, or one it sent wrong
    for hub_token in [None, {"token": token + "\n"}, {}]:
        with pytest.raises(ValueError):
            operator.configure_machine(token=True, cfg=cfg)
    hub_token = {"token": token}
    assert operator.check_machine_setup(url)["git_name"] == "Ada Lovelace"
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
            operator.check_machine_setup(bad)

    # A keyring that can't be reached, e.g., from a service started at
    # boot, says what to do instead
    def locked(self):
        raise keyring.errors.KeyringError("locked")

    monkeypatch.setattr(config.Settings, "write", locked)
    with pytest.raises(RuntimeError, match="calkit config set token"):
        operator.configure_machine(token=True, cfg=cfg)
    # A machine with no SSH key gets one to add to the Git host, and one that
    # has a key keeps it
    if shutil.which("ssh-keygen"):
        made = operator.get_ssh_public_key()
        assert made["created"] and made["public_key"].startswith("ssh-ed25519")
        assert os.path.isfile(os.path.join(home, ".ssh", "id_ed25519"))
        assert operator.get_ssh_public_key() == dict(made, created=False)
    # A clone outside the folders workspaces are found in is added to them,
    # so the hub lists it
    sent: list[dict] = []
    saved: list[dict] = []
    op = operator.Operator({"workspaces": []})

    async def send(ch, msg):
        sent.append(msg)

    async def check_in():
        return {}

    monkeypatch.setattr(op, "send", send)
    monkeypatch.setattr(op, "check_in", check_in)
    monkeypatch.setattr(operator, "save_config", saved.append)
    monkeypatch.setattr(
        operator,
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

    uid = ["1000"]

    def run(argv, **kwargs):
        runs.append((argv, kwargs.get("input")))
        if "cat ~/.calkit/operators/calkit.io/config.yaml 2>" in argv[-1]:
            # Anything a login prints comes first
            return SimpleNamespace(
                stdout=f"Welcome\ncalkit-uid={uid[0]}\n{remote_config['text']}"
            )
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
    # without its key, which the Operator there sends at its first
    # check-in
    assert "public_key" not in posted
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
    # Starting at login is passed along
    runs.clear()
    operator.install_remote("cluster", login=True)
    assert runs[-1][0][-1].endswith("--login'")
    # One that was revoked is registered again rather than kept, since it
    # would exit at its first check-in
    active.clear()
    runs.clear()
    operator.install_remote("cluster")
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
    operator.install_remote("cluster")
    assert posted["hostname"] == "login1.cluster"
    assert deleted == [
        ("/operators/self", {"Authorization": "Bearer cko_secret"})
    ]
    # A registration whose install fails is revoked, with its own token,
    # since the user's may not be from a sign-in that can
    remote_config["text"] = ""
    fail_install = True
    deleted.clear()
    with pytest.raises(subprocess.CalledProcessError):
        operator.install_remote("cluster")
    assert deleted == [
        ("/operators/self", {"Authorization": "Bearer cko_secret"})
    ]
    # Sessions would be root shells, so it's never installed as root there
    uid[0] = "0"
    posted.clear()
    with pytest.raises(ValueError, match="root"):
        operator.install_remote("root@cluster")
    assert posted == {}


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
        # Without saying which hub, which is none of this one's business
        with pytest.raises(ValueError, match="another hub"):
            operator.claim_workspace(wdir)
        (ws,) = [
            w
            for w in operator.discover_workspaces({})
            if w["path"] == os.path.realpath(wdir)
        ]
        assert ws["in_use_by"] == "another hub"
        # One the repo committed was written by no Operator
        subprocess.run(
            ["git", "add", "-f", operator.LOCK_PATH], cwd=wdir, check=True
        )
        assert operator.workspace_lock_holder(wdir) is None
        subprocess.run(
            ["git", "rm", "-q", "--cached", operator.LOCK_PATH],
            cwd=wdir,
            check=True,
        )
        assert operator.workspace_lock_holder(wdir) is not None
    finally:
        other.kill()
        other.wait()
    operator.claim_workspace(wdir)
    assert operator.workspace_lock_holder(wdir)["pid"] == os.getpid()
    operator.release_workspace(wdir)
    # Nor is a lock written through a link the repo committed
    if sys.platform != "win32":
        outside = tmp_path / "outside"
        outside.mkdir()
        shutil.rmtree(os.path.join(wdir, ".calkit", "local"))
        os.symlink(outside, os.path.join(wdir, ".calkit", "local"))
        with pytest.raises(ValueError):
            operator.claim_workspace(wdir)
        os.remove(os.path.join(wdir, ".calkit", "local"))
        os.makedirs(os.path.join(wdir, ".calkit", "local"))
        os.symlink(
            outside / "lock",
            os.path.join(wdir, ".calkit", "local", "operator.lock"),
        )
        assert operator.workspace_lock_holder(wdir) is None
        operator.claim_workspace(wdir)
        operator.release_workspace(wdir)
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
    op = operator.Operator({"name": "box", "workspaces": []})
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

    def check_in(cfg, workspaces, mode, connected, pending, sessions) -> dict:
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
    platform = operator.sys.platform
    monkeypatch.setattr(operator.sys, "platform", "linux")
    operator.restart_process("service")
    cmd = operator._service_command("service")
    assert execs == [(cmd[0], cmd)]
    monkeypatch.setattr(operator.sys, "platform", platform)
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
