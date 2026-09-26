"""The Operator: a long-running process that lets the hub use this machine.

It checks in with the hub API periodically, reporting its workspaces, and
holds a websocket to the relay, through which the owner's browser opens and
attaches to shell sessions in those workspaces. Sessions belong to this
process, so they survive browsers and relay connections coming and going.

See docs/dev/adrs/0001-operators.md and docs/dev/operator-protocol.md.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import logging
import os
import platform
import shlex
import shutil
import socket
import subprocess
import sys
import uuid
import warnings
from dataclasses import dataclass, field
from typing import Any

import calkit
from calkit import config

logger = logging.getLogger(__name__)

SCROLLBACK_BYTES = 256 * 1024
# Output is batched this long so a burst of redraws goes out as one message
OUTPUT_COALESCE_SECONDS = 0.02
# Terminal output is full of escape sequences, which JSON escapes to six
# characters each, so chunks stay well under the relay's message limit
OUTPUT_CHUNK_CHARS = 32 * 1024
RECONNECT_MAX_DELAY_SECONDS = 60
# In cron mode, the Operator exits after this long with no sessions or
# browsers, and cron starts it again when the hub asks
CRON_IDLE_EXIT_SECONDS = 900
CRON_MARKER = "# calkit-operator"


class OperatorRevoked(Exception):
    pass


def get_config_path() -> str:
    return os.path.join(
        config.get_user_home(),
        ".calkit",
        f"operator{config.get_env_suffix()}.yaml",
    )


def load_config() -> dict | None:
    import yaml

    fpath = get_config_path()
    if not os.path.isfile(fpath):
        return None
    with open(fpath) as f:
        return yaml.safe_load(f) or {}


def save_config(cfg: dict) -> None:
    """Save the Operator's config, which holds its token.

    It's a file only the user can read rather than a keyring entry, since
    a service started at boot often can't reach the user's keyring.
    """
    import yaml

    fpath = get_config_path()
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    fd = os.open(fpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)


def register(name: str | None = None, hosts: list[str] | None = None) -> dict:
    """Register this machine as an Operator with the hub and save its
    config.
    """
    from calkit import hub

    hostname = socket.gethostname()
    resp = hub._request(
        "post",
        "/operators",
        json=dict(
            name=name,
            hostname=hostname,
            machine_id=calkit.get_machine_id(),
            platform=platform.system().lower(),
            calkit_version=calkit.__version__,
            hosts=hosts or [hostname],
        ),
    )
    cfg = dict(
        api_url=hub.get_base_url(),
        id=resp["id"],
        name=resp["name"],
        user_id=resp["user_id"],
        token=resp["token"],
        workspaces=[],
    )
    save_config(cfg)
    return cfg


def _git_status(path: str) -> dict:
    """Branch, commit, dirtiness, and divergence of a checkout."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain=v2", "--branch"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return {}
    info: dict[str, Any] = {"dirty": False}
    for line in out.splitlines():
        if line.startswith("# branch.oid "):
            oid = line.split()[2]
            info["commit"] = None if oid == "(initial)" else oid
        elif line.startswith("# branch.head "):
            head = line.split()[2]
            info["branch"] = None if head == "(detached)" else head
        elif line.startswith("# branch.ab "):
            _, _, ahead, behind = line.split()
            info["ahead"] = int(ahead)
            info["behind"] = -int(behind)
        elif not line.startswith("#"):
            info["dirty"] = True
    return info


def discover_workspaces(cfg: dict) -> list[dict]:
    """Find the workspaces this Operator gives the hub access to.

    These are Calkit projects directly under ``~/calkit``, ones registered
    in the config, and the managed ones Calkit creates for running stages.
    """
    home = config.get_user_home()
    candidates: list[tuple[str, str]] = []
    root = os.path.join(home, "calkit")
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            candidates.append((os.path.join(root, name), "personal"))
    for path in cfg.get("workspaces", []):
        candidates.append((os.path.expanduser(path), "personal"))
    # Managed workspaces are laid out as <hub>/<owner>/<name>
    managed_root = os.path.join(home, ".calkit", "workspaces")
    if os.path.isdir(managed_root):
        for hub_dir in sorted(os.listdir(managed_root)):
            hub_path = os.path.join(managed_root, hub_dir)
            if not os.path.isdir(hub_path):
                continue
            for owner in sorted(os.listdir(hub_path)):
                owner_path = os.path.join(hub_path, owner)
                if not os.path.isdir(owner_path):
                    continue
                for name in sorted(os.listdir(owner_path)):
                    candidates.append(
                        (os.path.join(owner_path, name), "managed")
                    )
    workspaces = []
    seen = set()
    for path, kind in candidates:
        path = os.path.realpath(path)
        if path in seen:
            continue
        if not os.path.isfile(os.path.join(path, "calkit.yaml")):
            continue
        seen.add(path)
        try:
            project = calkit.detect_project_name(wdir=path)
        except Exception:
            project = None
        workspaces.append(
            dict(path=path, kind=kind, project=project) | _git_status(path)
        )
    return workspaces


def check_in(
    cfg: dict, workspaces: list[dict], mode: str, connected: bool = True
) -> dict:
    from requests.exceptions import HTTPError

    from calkit import hub

    try:
        resp: dict = hub._request(
            "post",
            "/operators/check-in",
            json=dict(
                calkit_version=calkit.__version__,
                workspaces=workspaces,
                mode=mode,
                connected=connected,
            ),
            headers={"Authorization": f"Bearer {cfg['token']}"},
            auth=False,
            allow_login=False,
            base_url=cfg["api_url"],
            max_retries=2,
        )
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            raise OperatorRevoked(str(e))
        raise
    return resp


def get_shell() -> str:
    shell = os.environ.get("SHELL")
    if shell:
        return shell
    try:
        import pwd

        return pwd.getpwuid(os.getuid()).pw_shell or "/bin/sh"
    except (ImportError, KeyError):
        return "/bin/sh"


@dataclass
class Session:
    id: str
    workspace: str
    pid: int
    fd: int
    scrollback: bytearray = field(default_factory=bytearray)
    channels: set[str] = field(default_factory=set)
    pending: list[str] = field(default_factory=list)
    flush_scheduled: bool = False
    decoder: Any = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")(
            errors="replace"
        )
    )

    @property
    def label(self) -> str:
        """What's running in the foreground, e.g., 'bash' or 'claude'."""
        import psutil

        try:
            return psutil.Process(os.tcgetpgrp(self.fd)).name()
        except (OSError, psutil.Error):
            return "shell"

    def info(self) -> dict:
        return dict(
            id=self.id,
            workspace=self.workspace,
            label=self.label,
            attached=len(self.channels),
        )


def _chunks(text: str, size: int = OUTPUT_CHUNK_CHARS) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


class Operator:
    def __init__(
        self,
        cfg: dict,
        mode: str = "foreground",
        idle_exit_seconds: float | None = None,
    ) -> None:
        self.cfg = cfg
        self.mode = mode
        self.idle_exit_seconds = idle_exit_seconds
        self.sessions: dict[str, Session] = {}
        # Browser channels, which are all the owner's
        self.channels: set[str] = set()
        self.workspaces: list[dict] = []
        self.ws: Any = None
        self.check_in_interval = 60

    async def send(self, ch: str, msg: dict) -> None:
        ws = self.ws
        if ws is None:
            return
        try:
            await ws.send(json.dumps({"ch": ch, "msg": msg}))
        except Exception as e:
            logger.debug(f"Dropped message to {ch}: {e}")

    def send_soon(self, ch: str, msg: dict) -> None:
        asyncio.get_running_loop().create_task(self.send(ch, msg))

    def open_session(self, workspace: str, cols: int, rows: int) -> Session:
        import pty

        allowed = {w["path"] for w in self.workspaces}
        workspace = os.path.realpath(workspace)
        if workspace not in allowed:
            raise ValueError("Not a workspace this Operator allows")
        # Everything the child needs is prepared here, since it's forked
        # from a process with threads: between fork and exec it may only
        # make system calls, not run code that could wait on a lock held
        # by a thread that no longer exists in it
        shell = shutil.which(get_shell()) or "/bin/sh"
        env = dict(os.environ, TERM="xterm-256color")
        argv = [os.fsencode(shell), b"-l"]
        envb = {os.fsencode(k): os.fsencode(v) for k, v in env.items()}
        cwd = os.fsencode(workspace)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            pid, fd = pty.fork()
        if pid == 0:
            # Child: a login shell in the workspace, as over SSH
            try:
                os.chdir(cwd)
                os.execve(argv[0], argv, envb)
            finally:
                os._exit(127)
        os.set_blocking(fd, False)
        session = Session(
            id=uuid.uuid4().hex[:12], workspace=workspace, pid=pid, fd=fd
        )
        self.sessions[session.id] = session
        self.resize(session, cols, rows)
        asyncio.get_running_loop().add_reader(fd, self._on_output, session)
        return session

    def resize(self, session: Session, cols: int, rows: int) -> None:
        import fcntl
        import struct
        import termios

        cols = max(1, min(int(cols), 1000))
        rows = max(1, min(int(rows), 1000))
        fcntl.ioctl(
            session.fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", rows, cols, 0, 0),
        )

    def _on_output(self, session: Session) -> None:
        try:
            data = os.read(session.fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self._on_exit(session)
            return
        session.scrollback += data
        if len(session.scrollback) > SCROLLBACK_BYTES:
            del session.scrollback[:-SCROLLBACK_BYTES]
        session.pending.append(session.decoder.decode(data))
        if not session.flush_scheduled:
            session.flush_scheduled = True
            asyncio.get_running_loop().call_later(
                OUTPUT_COALESCE_SECONDS, self._flush, session
            )

    def _flush(self, session: Session) -> None:
        session.flush_scheduled = False
        text = "".join(session.pending)
        session.pending.clear()
        if not text:
            return
        for ch in session.channels:
            for chunk in _chunks(text):
                self.send_soon(
                    ch,
                    {
                        "type": "sessions.output",
                        "session": session.id,
                        "data": chunk,
                    },
                )

    def _on_exit(self, session: Session) -> None:
        loop = asyncio.get_running_loop()
        loop.remove_reader(session.fd)
        self._flush(session)
        try:
            os.close(session.fd)
        except OSError:
            pass
        code = None
        try:
            _, status = os.waitpid(session.pid, 0)
            code = os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            pass
        self.sessions.pop(session.id, None)
        for ch in session.channels:
            self.send_soon(
                ch,
                {"type": "sessions.exit", "session": session.id, "code": code},
            )
        logger.info(f"Session {session.id} exited with code {code}")

    def attach(self, session: Session, ch: str) -> None:
        session.channels.add(ch)
        # Replay recent output so a reattaching browser sees the screen
        text = bytes(session.scrollback).decode("utf-8", errors="replace")
        if text:
            for chunk in _chunks(text):
                self.send_soon(
                    ch,
                    {
                        "type": "sessions.output",
                        "session": session.id,
                        "data": chunk,
                    },
                )

    def close_session(self, session: Session) -> None:
        import signal

        try:
            os.kill(session.pid, signal.SIGHUP)
        except ProcessLookupError:
            pass

    def close_all(self) -> None:
        for session in list(self.sessions.values()):
            self.close_session(session)

    def _get_session(self, msg: dict) -> Session:
        session = self.sessions.get(msg.get("session", ""))
        if session is None:
            raise ValueError("No such session")
        return session

    def handle(self, ch: str, msg: dict) -> dict | None:
        """Handle a message from a browser, returning a result, if any."""
        kind = msg.get("type")
        if kind == "workspaces.list":
            return {"workspaces": self.workspaces}
        if kind == "sessions.list":
            return {"sessions": [s.info() for s in self.sessions.values()]}
        if kind == "sessions.open":
            session = self.open_session(
                msg["workspace"], msg.get("cols", 80), msg.get("rows", 24)
            )
            self.attach(session, ch)
            return {"session": session.id}
        if kind == "sessions.attach":
            session = self._get_session(msg)
            if "cols" in msg and "rows" in msg:
                self.resize(session, msg["cols"], msg["rows"])
            self.attach(session, ch)
            return {"session": session.id}
        if kind == "sessions.detach":
            self._get_session(msg).channels.discard(ch)
            return None
        if kind == "sessions.input":
            data = msg.get("data", "")
            if isinstance(data, str) and data:
                os.write(self._get_session(msg).fd, data.encode())
            return None
        if kind == "sessions.resize":
            self.resize(self._get_session(msg), msg["cols"], msg["rows"])
            return None
        if kind == "sessions.close":
            self.close_session(self._get_session(msg))
            return None
        raise ValueError(f"Unknown message type: {kind}")

    def on_relay_message(self, frame: dict) -> None:
        kind = frame.get("type")
        ch = frame.get("ch")
        if not isinstance(ch, str):
            return
        if kind == "channel.open":
            # Only the owner may use this Operator, whatever the relay says
            if frame.get("user_id") == self.cfg["user_id"]:
                self.channels.add(ch)
            else:
                logger.warning(f"Refused channel for {frame.get('user_id')}")
            return
        if kind == "channel.close":
            self.channels.discard(ch)
            for session in self.sessions.values():
                session.channels.discard(ch)
            return
        if kind != "channel.message" or ch not in self.channels:
            return
        msg = frame.get("msg")
        if not isinstance(msg, dict):
            return
        req_id = msg.get("id")
        try:
            result = self.handle(ch, msg)
        except Exception as e:
            if req_id is not None:
                self.send_soon(
                    ch, {"type": "error", "id": req_id, "error": str(e)}
                )
            else:
                logger.warning(f"Failed to handle {msg.get('type')}: {e}")
            return
        if req_id is not None:
            self.send_soon(
                ch, {"type": "result", "id": req_id, "result": result}
            )

    async def check_in(self) -> dict:
        self.workspaces = await asyncio.to_thread(
            discover_workspaces, self.cfg
        )
        resp = await asyncio.to_thread(
            check_in, self.cfg, self.workspaces, self.mode
        )
        self.check_in_interval = resp.get("check_in_interval", 60)
        return resp

    async def keep_checking_in(self) -> None:
        while True:
            await asyncio.sleep(self.check_in_interval)
            try:
                await self.check_in()
            except OperatorRevoked:
                raise
            except Exception as e:
                logger.warning(f"Check-in failed: {e}")

    async def connect(self, resp: dict) -> None:
        from websockets.asyncio.client import connect

        url = f"{resp['relay_url']}/operator?token={resp['relay_token']}"
        async with connect(url, max_size=None) as ws:
            self.ws = ws
            logger.info(f"Connected to relay as {self.cfg['name']}")
            try:
                async for text in ws:
                    try:
                        frame = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(frame, dict):
                        self.on_relay_message(frame)
            finally:
                self.ws = None
                self.channels.clear()
                for session in self.sessions.values():
                    session.channels.clear()

    async def wait_until_idle(self) -> None:
        """Return once nothing has used this Operator for its idle limit."""
        assert self.idle_exit_seconds is not None
        loop = asyncio.get_running_loop()
        last_used = loop.time()
        while True:
            await asyncio.sleep(min(30, self.idle_exit_seconds))
            if self.sessions or self.channels:
                last_used = loop.time()
            elif loop.time() - last_used >= self.idle_exit_seconds:
                logger.info("Idle, so stopping until the hub asks again")
                return

    async def run(self) -> None:
        checker: asyncio.Task | None = None
        idle: asyncio.Task | None = None
        if self.idle_exit_seconds is not None:
            idle = asyncio.create_task(self.wait_until_idle())
        delay = 1.0
        try:
            while True:
                try:
                    resp = await self.check_in()
                    if checker is None:
                        checker = asyncio.create_task(self.keep_checking_in())
                    delay = 1.0
                    connection = asyncio.create_task(self.connect(resp))
                    waiting = [connection, checker]
                    if idle is not None:
                        waiting.append(idle)
                    done, _ = await asyncio.wait(
                        waiting, return_when=asyncio.FIRST_COMPLETED
                    )
                    if idle in done:
                        connection.cancel()
                        return
                    if checker in done:
                        connection.cancel()
                        checker.result()
                    connection.result()
                    logger.info("Relay connection closed")
                except OperatorRevoked:
                    raise
                except Exception as e:
                    logger.warning(f"Connection failed: {e}")
                    delay = min(delay * 2, RECONNECT_MAX_DELAY_SECONDS)
                await asyncio.sleep(delay)
        finally:
            for task in [checker, idle]:
                if task is not None:
                    task.cancel()
            self.close_all()
            # So the hub shows it offline now rather than minutes from now
            try:
                await asyncio.to_thread(
                    check_in, self.cfg, self.workspaces, self.mode, False
                )
            except Exception:
                pass


def acquire_lock() -> Any:
    """Take the lock that keeps one Operator running per machine and user,
    returning its file, or None if another Operator holds it.

    Two would each replace the other's relay connection, and in cron mode
    cron starts one every few minutes regardless.
    """
    import fcntl

    fpath = os.path.join(config.get_user_home(), ".calkit", "operator.lock")
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    f = open(fpath, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def run(cfg: dict, mode: str = "foreground") -> bool:
    """Run the Operator until it's revoked, interrupted, or, in cron mode,
    idle or not asked to connect.

    Returns False if another Operator is already running.
    """
    import signal

    lock = acquire_lock()
    if lock is None:
        return False

    # Service managers stop it with SIGTERM, which should shut down as
    # cleanly as Ctrl+C
    def interrupt(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        if mode == "cron":
            workspaces = discover_workspaces(cfg)
            resp = check_in(cfg, workspaces, mode, connected=False)
            if not resp["connect"]:
                return True
            operator = Operator(
                cfg, mode=mode, idle_exit_seconds=CRON_IDLE_EXIT_SECONDS
            )
        else:
            operator = Operator(cfg, mode=mode)
        asyncio.run(operator.run())
    finally:
        lock.close()
    return True


SERVICE_LABEL = "io.calkit.operator"
SYSTEMD_UNIT = "calkit-operator.service"


def get_log_path() -> str:
    return os.path.join(config.get_user_home(), ".calkit", "operator.log")


def _service_command(mode: str = "service") -> list[str]:
    # The interpreter Calkit runs in, so the service doesn't depend on PATH
    return [
        sys.executable,
        "-m",
        "calkit",
        "operator",
        "start",
        "--mode",
        mode,
    ]


def _read_crontab() -> list[str]:
    out = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    # A user with no crontab gets an error, which means an empty one
    return out.stdout.splitlines() if out.returncode == 0 else []


def _write_crontab(lines: list[str]) -> None:
    subprocess.run(
        ["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True
    )


def install_cron() -> None:
    """Have cron start the Operator every few minutes and at boot, so it
    checks in and connects only when the hub asks.
    """
    if shutil.which("crontab") is None:
        raise NotImplementedError(
            "This machine has no crontab; install with --no-service and run "
            "'calkit operator start' yourself, e.g., inside tmux"
        )
    os.makedirs(os.path.dirname(get_log_path()), exist_ok=True)
    command = shlex.join(_service_command("cron"))
    log = shlex.quote(get_log_path())
    lines = [line for line in _read_crontab() if CRON_MARKER not in line]
    for schedule in ["*/5 * * * *", "@reboot"]:
        lines.append(f"{schedule} {command} >> {log} 2>&1 {CRON_MARKER}")
    _write_crontab(lines)


def _cron_installed() -> bool:
    if shutil.which("crontab") is None:
        return False
    return any(CRON_MARKER in line for line in _read_crontab())


def _launchd_plist_path(at_boot: bool) -> str:
    if at_boot:
        return f"/Library/LaunchDaemons/{SERVICE_LABEL}.plist"
    return os.path.join(
        config.get_user_home(),
        "Library",
        "LaunchAgents",
        f"{SERVICE_LABEL}.plist",
    )


def _launchd_plist(at_boot: bool) -> bytes:
    import getpass
    import plistlib

    plist: dict[str, Any] = {
        "Label": SERVICE_LABEL,
        "ProgramArguments": _service_command(),
        "RunAtLoad": True,
        # Restarted if it fails, but not after it exits cleanly because it
        # was revoked
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": get_log_path(),
        "StandardErrorPath": get_log_path(),
        "EnvironmentVariables": {"HOME": config.get_user_home()},
    }
    if at_boot:
        plist["UserName"] = getpass.getuser()
    return plistlib.dumps(plist)


def _systemd_unit_path() -> str:
    return os.path.join(
        config.get_user_home(), ".config", "systemd", "user", SYSTEMD_UNIT
    )


def _systemd_unit() -> str:
    command = " ".join(shlex.quote(arg) for arg in _service_command())
    return (
        "[Unit]\n"
        "Description=Calkit Operator\n"
        "After=network-online.target\n"
        "\n"
        "[Service]\n"
        f"ExecStart={command}\n"
        "Restart=on-failure\n"
        "RestartSec=10\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def install_service(at_boot: bool = False) -> list[str]:
    """Install the Operator as a service that runs as this user, returning
    notes for the user.

    On Linux it starts at boot if the user's services are allowed to linger.
    On macOS it starts at login unless ``at_boot``, which needs sudo.
    """
    notes = []
    system = platform.system()
    os.makedirs(os.path.dirname(get_log_path()), exist_ok=True)
    if system == "Linux":
        # Clusters often have no user systemd, e.g., on login nodes
        probe = (
            subprocess.run(
                ["systemctl", "--user", "show-environment"],
                capture_output=True,
            )
            if shutil.which("systemctl")
            else None
        )
        if probe is None or probe.returncode != 0:
            raise NotImplementedError(
                "This machine has no user systemd to run the Operator as a "
                "service. Reinstall with --cron to have cron start it when "
                "the hub asks, or with --no-service and run "
                "'calkit operator start' yourself, e.g., inside tmux"
            )
        fpath = _systemd_unit_path()
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w") as f:
            f.write(_systemd_unit())
        for args in [
            ["daemon-reload"],
            ["enable", "--now", SYSTEMD_UNIT],
            ["restart", SYSTEMD_UNIT],
        ]:
            subprocess.run(["systemctl", "--user", *args], check=True)
        # Without lingering, user services stop at logout and don't start
        # at boot
        user = os.environ.get("USER") or ""
        linger = subprocess.run(
            ["loginctl", "show-user", user, "--property=Linger", "--value"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if linger != "yes":
            enabled = subprocess.run(
                ["loginctl", "enable-linger", user], capture_output=True
            )
            if enabled.returncode != 0:
                notes.append(
                    "The Operator will only run while you're logged in. "
                    "To start it at boot, run: "
                    f"sudo loginctl enable-linger {user}"
                )
    elif system == "Darwin":
        fpath = _launchd_plist_path(at_boot)
        domain = "system" if at_boot else f"gui/{os.getuid()}"
        sudo = ["sudo"] if at_boot else []
        subprocess.run(
            [*sudo, "launchctl", "bootout", f"{domain}/{SERVICE_LABEL}"],
            capture_output=True,
        )
        if at_boot:
            import tempfile

            with tempfile.NamedTemporaryFile("wb", delete=False) as tmp:
                tmp.write(_launchd_plist(at_boot))
            subprocess.run(["sudo", "cp", tmp.name, fpath], check=True)
            os.remove(tmp.name)
        else:
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "wb") as plist_file:
                plist_file.write(_launchd_plist(at_boot))
        subprocess.run(
            [*sudo, "launchctl", "bootstrap", domain, fpath], check=True
        )
        if not at_boot:
            notes.append(
                "The Operator will start when you log in. To start it at "
                "boot instead, reinstall with --at-boot, which needs sudo."
            )
    else:
        raise NotImplementedError(
            f"Installing the Operator as a service isn't supported on "
            f"{system} yet; run 'calkit operator start' instead"
        )
    return notes


def uninstall_service() -> None:
    if _cron_installed():
        _write_crontab(
            [line for line in _read_crontab() if CRON_MARKER not in line]
        )
    system = platform.system()
    if system == "Linux":
        fpath = _systemd_unit_path()
        if os.path.isfile(fpath):
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT]
            )
            os.remove(fpath)
            subprocess.run(["systemctl", "--user", "daemon-reload"])
    elif system == "Darwin":
        agent = _launchd_plist_path(at_boot=False)
        if os.path.isfile(agent):
            subprocess.run(
                [
                    "launchctl",
                    "bootout",
                    f"gui/{os.getuid()}/{SERVICE_LABEL}",
                ],
                capture_output=True,
            )
            os.remove(agent)
        daemon = _launchd_plist_path(at_boot=True)
        if os.path.isfile(daemon):
            subprocess.run(
                ["sudo", "launchctl", "bootout", f"system/{SERVICE_LABEL}"],
                capture_output=True,
            )
            subprocess.run(["sudo", "rm", daemon])


def get_service_status() -> str | None:
    """Describe the service, or return None if it isn't installed."""
    if _cron_installed():
        return "cron, checking in every 5 minutes"
    system = platform.system()
    if system == "Linux" and os.path.isfile(_systemd_unit_path()):
        return subprocess.run(
            ["systemctl", "--user", "is-active", SYSTEMD_UNIT],
            capture_output=True,
            text=True,
        ).stdout.strip()
    if system == "Darwin":
        for at_boot in [False, True]:
            if not os.path.isfile(_launchd_plist_path(at_boot)):
                continue
            domain = "system" if at_boot else f"gui/{os.getuid()}"
            out = subprocess.run(
                ["launchctl", "print", f"{domain}/{SERVICE_LABEL}"],
                capture_output=True,
                text=True,
            ).stdout
            state = "not running"
            # The first state is the service's; later ones are its parts'
            for line in out.splitlines():
                if line.strip().startswith("state = "):
                    state = line.split("=", 1)[1].strip()
                    break
            return f"{state} ({'at boot' if at_boot else 'at login'})"
    return None


def set_service_running(running: bool) -> None:
    system = platform.system()
    if system == "Linux" and os.path.isfile(_systemd_unit_path()):
        action = "start" if running else "stop"
        subprocess.run(
            ["systemctl", "--user", action, SYSTEMD_UNIT], check=True
        )
        return
    if system == "Darwin":
        for at_boot in [False, True]:
            fpath = _launchd_plist_path(at_boot)
            if not os.path.isfile(fpath):
                continue
            domain = "system" if at_boot else f"gui/{os.getuid()}"
            sudo = ["sudo"] if at_boot else []
            if running:
                subprocess.run(
                    [*sudo, "launchctl", "bootstrap", domain, fpath],
                    check=True,
                )
            else:
                subprocess.run(
                    [
                        *sudo,
                        "launchctl",
                        "bootout",
                        f"{domain}/{SERVICE_LABEL}",
                    ],
                    check=True,
                )
            return
    raise RuntimeError("The Operator isn't installed as a service")
