"""A machine's link to a hub: a long-running process that lets the hub use
this machine.

It checks in with the hub API periodically, reporting its workspaces, and
holds a websocket to the relay, through which the owner's browser opens and
attaches to shell sessions in those workspaces. Sessions belong to this
process, so they survive browsers and relay connections coming and going.

See docs/dev/adrs/0001-linked-machines.md and docs/dev/hub-link-protocol.md.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import logging
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import uuid
import warnings
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import calkit
from calkit import config

if TYPE_CHECKING:
    import git

logger = logging.getLogger(__name__)

SCROLLBACK_BYTES = 256 * 1024
# Output is batched this long so a burst of redraws goes out as one message
OUTPUT_COALESCE_SECONDS = 0.02
# Terminal output is full of escape sequences, which JSON escapes to six
# characters each and again to seven in a signed reply's body, so chunks stay
# well under the relay's message limit
OUTPUT_CHUNK_CHARS = 16 * 1024
RECONNECT_MAX_DELAY_SECONDS = 60
# Messages from the relay are at most 256 KiB, plus its wrapping
MAX_FRAME_BYTES = 1024 * 1024
# What the relay takes in one message, with room to spare
MAX_SEND_BYTES = 250_000
# Paths given for why a stage is stale, and of DVC's changes, past which
# only a count goes, so a large project's status fits in one message
MAX_STALE_PATHS = 10
MAX_CHANGED_PATHS = 200
# Replies waiting to go to one browser, past which it's too far behind and
# its channel is closed, so a slow one can't make this hold everything
MAX_CHANNEL_BACKLOG_BYTES = 8 * 1024 * 1024
# How often channels are checked for an expired second factor
CHANNEL_CHECK_SECONDS = 30
# Without a check-in for this long, the link can't hear of ended
# sign-ins, so it closes its channels until it can
CHECK_IN_GRACE_SECONDS = 600
# What the relay names channels, which the link logs
CHANNEL_ID_PATTERN = r"[A-Za-z0-9_-]{1,64}"
# Session input waiting for its terminal to drain, e.g., a long paste
MAX_INPUT_BUFFER_BYTES = 1024 * 1024
# In cron mode, the link exits after this long with no sessions or
# browsers, and cron starts it again when the hub asks
CRON_IDLE_EXIT_SECONDS = 900
# So a file a repo committed as a link isn't followed out of it
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
# Folders in the home directory whose Calkit projects are workspaces
WORKSPACE_ROOTS = ["calkit", "dev"]
# How often to check whether Calkit was upgraded or a restart was asked for
RESTART_CHECK_SECONDS = 30
# The log is cut down to its last LOG_KEEP_BYTES past LOG_MAX_BYTES
LOG_MAX_BYTES = 5_000_000
LOG_KEEP_BYTES = 1_000_000
# How long the same warning isn't logged again
REPEAT_LOG_SECONDS = 3600
# Coding agents found running in workspaces, by command
AGENT_TOOLS = ("claude", "codex", "opencode")
# How long before a session's hub token expires the link gets another,
# which is longer than Calkit's own margin, so it never gets an old one
SESSION_TOKEN_MARGIN_SECONDS = 120
# How long a session's GitHub token is kept, which the hub refreshes well
# before it expires
GITHUB_TOKEN_CACHE_SECONDS = 300

# The hub the link commands in this process act on, by its web URL.
# Each hub's link has its own config, service, lock, and log, named by
# the hub's key, so links to several hubs can run side by side.
_hub_url: str | None = None
# Hub requests are pointed at the link's hub through CALKIT_HUB, but
# what runs in workspaces gets the value it started with
_inherited_hub = os.environ.get("CALKIT_HUB")


class LinkRevoked(Exception):
    pass


class LinkKeyRejected(LinkRevoked):
    """The hub has another key for this machine, so it mustn't connect."""


def select_hub(hub_url: str | None = None) -> str:
    """Choose the hub the link commands act on, or the user's own hub
    if not given, returning its key.
    """
    global _hub_url
    if hub_url is None:
        from calkit.hub import core as hub

        use_own_hub()
        hub_url = hub.get_hub_url()
    else:
        hub_url = config.normalize_hub_url(hub_url)
        # So hub requests go to it too
        os.environ["CALKIT_HUB"] = hub_url
    _hub_url = hub_url
    return hub_key()


def get_hub_url() -> str:
    if _hub_url is None:
        select_hub()
    assert _hub_url is not None
    return _hub_url


def hub_key(hub_url: str | None = None) -> str:
    """A short name for a hub, e.g., "calkit.io", which is also what its
    managed workspaces are filed under.
    """
    from calkit.workspace import _path_segment

    url = hub_url or get_hub_url()
    return _path_segment(re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", url))


def link_dir(key: str | None = None) -> str:
    return os.path.join(
        config.get_user_home(),
        ".calkit",
        "hubs",
        hub_key() if key is None else key,
    )


def get_config_path() -> str:
    return os.path.join(link_dir(), "link.yaml")


def list_configured_hubs() -> list[str]:
    """The web URLs of the hubs this machine is linked to."""
    import yaml

    root = os.path.join(config.get_user_home(), ".calkit", "hubs")
    hubs = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        fpath = os.path.join(root, name, "link.yaml")
        if not os.path.isfile(fpath):
            continue
        with open(fpath) as f:
            cfg = yaml.safe_load(f) or {}
        if cfg.get("hub_url"):
            hubs.append(cfg["hub_url"])
    return hubs


def _private_dir(path: str) -> str:
    """Make a folder only the user can open, e.g., a link's, which on
    a shared login node others could otherwise look in.
    """
    os.makedirs(path, mode=0o700, exist_ok=True)
    if os.name == "posix":
        os.chmod(path, 0o700)
    return path


def _write_private(fpath: str, text: str) -> None:
    """Write a file only the user can read, e.g., one holding a token."""
    _private_dir(os.path.dirname(fpath))
    fd = os.open(fpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    # A file that already existed keeps its mode otherwise
    if hasattr(os, "fchmod"):
        os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def _private_log() -> str:
    """Create the log, if it isn't there, so only the user can read it, as
    what service managers and cron create is readable by anyone.
    """
    fpath = get_log_path()
    _private_dir(os.path.dirname(fpath))
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    fd = os.open(fpath, flags | NOFOLLOW, 0o600)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    return fpath


def get_link_key() -> Any:
    """This link's own P-256 key, made the first time it's needed, which
    it signs what it sends browsers with, so they know it's from here.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    fpath = os.path.join(link_dir(), "link-key.pem")
    if os.path.isfile(fpath):
        with open(fpath, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        if isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(
            key.curve, ec.SECP256R1
        ):
            return key
        raise ValueError(f"{fpath} isn't a P-256 key")
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    _write_private(fpath, pem.decode())
    return key


def get_link_public_jwk() -> dict:
    """The public half of this link's key, as a JSON Web Key."""
    import base64

    numbers = get_link_key().public_key().public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        **{
            name: base64.urlsafe_b64encode(value.to_bytes(32, "big"))
            .decode()
            .rstrip("=")
            for name, value in [("x", numbers.x), ("y", numbers.y)]
        },
    }


def _used_grants_path() -> str:
    return os.path.join(link_dir(), "used-grants.json")


def load_used_grants() -> dict[str, float]:
    """IDs of grants channels were opened with, and when they expire, kept
    across restarts, so a grant can't be used again after one.
    """
    try:
        with open(_used_grants_path()) as f:
            used = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(used, dict):
        return {}
    return {
        str(jti): float(exp)
        for jti, exp in used.items()
        if isinstance(exp, (int, float))
    }


def save_used_grants(used: dict[str, float]) -> None:
    _write_private(_used_grants_path(), json.dumps(used))


def load_config() -> dict | None:
    import yaml

    fpath = get_config_path()
    if not os.path.isfile(fpath):
        return None
    with open(fpath) as f:
        return yaml.safe_load(f) or {}


def save_config(cfg: dict) -> None:
    """Save the link's config, which holds its token.

    It's a file only the user can read rather than a keyring entry, since
    a service started at boot often can't reach the user's keyring.
    """
    import yaml

    _write_private(get_config_path(), yaml.safe_dump(cfg, sort_keys=False))


def check_secure_url(url: str) -> None:
    """Refuse a hub or relay URL that isn't encrypted, unless it's local,
    since whoever can tamper with the connection could run commands here.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or ""
    local = host in ("localhost", "127.0.0.1", "::1") or host.endswith(
        ".localhost"
    )
    if parsed.scheme not in ("https", "wss") and not local:
        raise ValueError(f"Refusing to connect to {url} without TLS")


def use_own_hub() -> str:
    """Point hub requests at the user's own hub, returning its API URL.

    Hub requests otherwise go to the hub named by the project in the
    working directory, if any, and a cloned project mustn't be able to
    decide which hub gets to run commands on this machine.
    """
    from calkit.hub import core as hub

    if not os.getenv("CALKIT_HUB") and os.getenv("CALKIT_ENV") != "test":
        os.environ["CALKIT_HUB"] = (
            config._get_default_hub() or hub.DEFAULT_HUB_URL
        )
    url = hub.get_base_url()
    check_secure_url(url)
    return url


def is_registered(cfg: Any) -> bool:
    """Whether a config is for an active machine on the user's own hub,
    rather than a revoked one or one from another hub, asked with the
    machine's own token so it works without the user's login there.
    """
    from requests.exceptions import HTTPError

    from calkit.hub import core as hub

    if not isinstance(cfg, dict) or cfg.get("api_url") != use_own_hub():
        return False
    try:
        resp = hub._request(
            "get",
            "/machines/self",
            headers={"Authorization": f"Bearer {cfg.get('token')}"},
            auth=False,
            allow_login=False,
            base_url=cfg["api_url"],
            max_retries=2,
        )
    except HTTPError as e:
        # Its token is refused once it's revoked
        status = e.response.status_code if e.response is not None else None
        if status in (401, 403, 410):
            return False
        raise
    return bool(resp.get("id") == cfg.get("id"))


def register(name: str | None = None, hosts: list[str] | None = None) -> dict:
    """Register this machine with the hub and save its link's
    config.
    """
    from calkit.hub import core as hub

    use_own_hub()
    hostname = socket.gethostname()
    resp = hub._request(
        "post",
        "/machines",
        json=dict(
            name=name,
            hostname=hostname,
            machine_id=calkit.get_machine_id(),
            platform=platform.system().lower(),
            calkit_version=calkit.__version__,
            hosts=hosts or [hostname],
            # So browsers can tell its replies from anyone else's
            public_key=get_link_public_jwk(),
        ),
    )
    cfg = dict(
        api_url=hub.get_base_url(),
        hub_url=get_hub_url(),
        id=resp["id"],
        name=resp["name"],
        user_id=resp["user_id"],
        token=resp["token"],
        grant_public_key=resp["grant_public_key"],
        workspaces=[],
    )
    save_config(cfg)
    return cfg


def revoke_self(cfg: dict) -> None:
    """Revoke a machine on the hub with its own token, which works however
    the user is signed in, taking one already revoked as done.
    """
    from requests.exceptions import HTTPError

    from calkit.hub import core as hub

    try:
        hub._request(
            "delete",
            "/machines/self",
            headers={"Authorization": f"Bearer {cfg['token']}"},
            auth=False,
            allow_login=False,
            base_url=cfg["api_url"],
            max_retries=2,
        )
    except HTTPError as e:
        # Its token is refused once it's revoked
        status = e.response.status_code if e.response is not None else None
        if status not in (401, 403, 410):
            raise


def refuse_root() -> None:
    """Refuse to run as root, since sessions would be root shells."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise ValueError(
            "The hub link can't run as root; run it as your own user"
        )


def install_remote(
    host: str,
    cron: bool = False,
    no_service: bool = False,
    login: bool = False,
    interactive: bool = True,
) -> dict:
    """Link another machine over SSH, returning its
    config.

    It's registered from here, with this machine's hub login, since the
    other one may never have logged in; its config is then written there
    and Calkit there installs the service, finding itself already
    registered.
    """
    import yaml

    from calkit import workspace as ws
    from calkit.hub import core as hub

    use_own_hub()
    # Where the other machine keeps its link to this hub
    remote_dir = f"~/.calkit/hubs/{hub_key()}"
    remote_config = f"{remote_dir}/link.yaml"
    # Otherwise ssh would take it as an option
    if host.startswith("-"):
        raise ValueError(f"Invalid host '{host}'")
    target = ws.Workspace(host=host, wdir="~")
    target = ws.ensure_reachable(target, interactive=interactive)
    ws.ensure_calkit_installed(target, interactive=interactive, required=True)
    # Reinstalling, e.g., to change mode, keeps the machine it already has
    # rather than leaving that one behind on the hub. Who it would run as is
    # asked at the same time, to save logging in again.
    out = subprocess.run(
        target.login_argv(
            f'echo "calkit-uid=$(id -u)" && cat {remote_config} 2>/dev/null '
            "|| true"
        ),
        capture_output=True,
        text=True,
    ).stdout
    # After anything a login prints first
    uid, _, existing = out.partition("calkit-uid=")[2].partition("\n")
    if uid.strip() == "0":
        raise ValueError(
            "The hub link can't run as root; install it as another user"
        )
    cfg = yaml.safe_load(existing) if existing.strip() else None
    registered = False
    # One whose key the hub refused is replaced, since it can't connect
    if isinstance(cfg, dict) and cfg.get("key_rejected"):
        try:
            revoke_self(cfg)
        except Exception:
            pass
        cfg = None
    if not is_registered(cfg):
        info = ws.remote_system_info(target)
        hostname = info.get("hostname") or host
        resp = hub._request(
            "post",
            "/machines",
            json=dict(
                hostname=hostname,
                machine_id=info.get("machine_id"),
                platform=str(info.get("os", "")).lower() or None,
                calkit_version=info.get("calkit_version"),
                hosts=list(dict.fromkeys([host, hostname])),
            ),
        )
        cfg = dict(
            api_url=hub.get_base_url(),
            hub_url=get_hub_url(),
            id=resp["id"],
            name=resp["name"],
            user_id=resp["user_id"],
            token=resp["token"],
            grant_public_key=resp["grant_public_key"],
            workspaces=[],
        )
        registered = True
    assert isinstance(cfg, dict)
    try:
        if registered:
            # Only the user can read it there either, since it holds the
            # token
            subprocess.run(
                # The key is a plain path segment, so needs no quoting
                target.login_argv(
                    f"umask 077 && mkdir -p {remote_dir} "
                    f"&& cat > {remote_config}"
                ),
                input=yaml.safe_dump(cfg, sort_keys=False),
                text=True,
                check=True,
            )
        args = ["calkit", "hub", "link", "install", "--hub", get_hub_url()]
        if cron:
            args.append("--cron")
        if no_service:
            args.append("--no-service")
        # Over SSH there's no terminal for sudo to ask in, so it starts at
        # boot only if sudo can without asking, and says so if not
        if login:
            args.append("--login")
        subprocess.run(target.login_argv(shlex.join(args)), check=True)
    except Exception:
        # A registration nothing can use would linger on the hub
        if registered:
            revoke_self(cfg)
        raise
    return dict(cfg)


def _open_in_workspace(wdir: str, path: str, mode: str = "r") -> Any:
    """Open a file in a workspace for reading or writing, refusing a link or
    a path through one out of it, since a repo can commit links to anywhere,
    e.g., a .gitignore linked to ~/.bashrc.
    """
    root = os.path.realpath(wdir)
    parent = os.path.realpath(os.path.join(root, os.path.dirname(path)))
    if parent != root and not parent.startswith(root + os.sep):
        raise ValueError(f"{path} is outside the workspace")
    fpath = os.path.join(parent, os.path.basename(path))
    if os.path.islink(fpath):
        raise ValueError(f"{path} is a link, which won't be followed")
    flags = os.O_RDONLY if mode == "r" else os.O_WRONLY | os.O_CREAT
    if mode == "w":
        flags |= os.O_TRUNC
    elif mode == "x":
        flags |= os.O_EXCL
    fd = os.open(fpath, flags | NOFOLLOW, 0o644)
    return os.fdopen(fd, "r" if mode == "r" else "w")


LOCK_PATH = ".calkit/local/hub-link.lock"


def workspace_lock_holder(wdir: str) -> dict | None:
    """Who's using a workspace, if anyone: the hub whose link holds its
    lock, as long as that link is still running.

    The lock lives in the workspace, so links to different hubs on
    the same machine see each other's.
    """
    import psutil

    try:
        with _open_in_workspace(wdir, LOCK_PATH) as f:
            holder = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(holder, dict):
        return None
    pid = holder.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    if pid == os.getpid():
        return holder
    # One that's gone left a stale lock, as did one whose ID has since been
    # reused by something else
    try:
        proc = psutil.Process(pid)
        if "hub link start" not in " ".join(proc.cmdline()):
            return None
        if hasattr(os, "getuid") and proc.uids().real != os.getuid():
            return None
    except (psutil.Error, SystemError):
        return None
    # A repo can commit one, which no link wrote
    try:
        tracked = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "ls-files", "--", LOCK_PATH],
            cwd=wdir,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    if tracked:
        return None
    return holder


def claim_workspace(wdir: str) -> None:
    """Take a workspace for this hub's link, refusing if another hub's
    is using it, since two hubs changing one checkout would step on each
    other.
    """
    holder = workspace_lock_holder(wdir)
    if holder is not None:
        if holder.get("pid") == os.getpid():
            return
        # Not saying which, since that's another hub's business
        raise ValueError(
            "This workspace is in use by this machine's link to another hub"
        )
    root = os.path.realpath(wdir)
    local = os.path.realpath(os.path.join(root, os.path.dirname(LOCK_PATH)))
    if not local.startswith(root + os.sep):
        raise ValueError(".calkit/local is outside the workspace")
    os.makedirs(local, exist_ok=True)
    # Which keeps it out of Git
    if not os.path.lexists(os.path.join(local, ".gitignore")):
        with _open_in_workspace(wdir, ".calkit/local/.gitignore", "w") as f:
            f.write("*\n")
    fpath = os.path.join(local, os.path.basename(LOCK_PATH))
    tmp = f"{LOCK_PATH}.{os.getpid()}"
    if os.path.lexists(os.path.join(root, tmp)):
        os.remove(os.path.join(root, tmp))
    with _open_in_workspace(wdir, tmp, "x") as f:
        json.dump(
            {
                "hub": get_hub_url(),
                "pid": os.getpid(),
                "since": calkit.utcnow().isoformat(),
            },
            f,
        )
    # Replacing a link, rather than writing through it
    os.replace(os.path.join(root, tmp), fpath)
    # Another link may have claimed it at the same moment, in which
    # case only one of the writes stands
    holder = workspace_lock_holder(wdir)
    if holder is None or holder.get("pid") != os.getpid():
        raise ValueError("This workspace is in use by another hub link")


def release_workspace(wdir: str) -> None:
    """Let other hubs' links use a workspace this one was using."""
    holder = workspace_lock_holder(wdir)
    if holder is not None and holder.get("pid") == os.getpid():
        try:
            os.remove(os.path.join(wdir, LOCK_PATH))
        except OSError:
            pass


# Git as discovery runs it in every folder that looks like a project, where
# a repo's own config, e.g., in one unpacked from an archive rather than
# cloned, mustn't be able to run anything
SAFE_GIT = [
    "git",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
]


def is_on_this_hub(wdir: str) -> bool:
    """Whether a project is on this link's hub: the one it declares, else the
    user's default hub, else calkit.io, as Calkit decides it there.
    """
    from calkit.hub import DEFAULT_HUB_URL, get_api_url

    hub = (
        config._get_project_hub(wdir)
        or config._get_default_hub()
        or DEFAULT_HUB_URL
    )
    return get_api_url(hub) == get_api_url(get_hub_url())


def discover_workspaces(cfg: dict) -> list[dict]:
    """Find the workspaces this link gives the hub access to.

    These are Calkit projects on this hub directly under ``~/calkit`` or
    ``~/dev``, ones registered in the config, and the managed ones Calkit
    creates for running stages.
    """

    def _git_status(path: str) -> dict:
        """Branch, commit, dirtiness, and divergence of a checkout."""
        try:
            out = subprocess.run(
                [*SAFE_GIT, "status", "--porcelain=v2", "--branch"],
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
                info["branch"] = None if head == "(detached)" else head[:256]
            elif line.startswith("# branch.ab "):
                _, _, ahead, behind = line.split()
                info["ahead"] = int(ahead)
                info["behind"] = -int(behind)
            elif not line.startswith("#"):
                info["dirty"] = True
        return info

    def _last_activity(path: str, last_run: dict | None) -> str | None:
        """When a checkout last changed, as far as is cheap to tell: its
        latest commit, Git's index, which staging and checkouts write, or
        its latest run ending.
        """
        from datetime import datetime, timezone

        times = []
        try:
            out = subprocess.run(
                [*SAFE_GIT, "log", "-1", "--format=%ct"],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            if out:
                times.append(float(out))
        except (subprocess.SubprocessError, OSError, ValueError):
            pass
        # A worktree's .git is a file pointing at its Git directory
        git_dir = os.path.join(path, ".git")
        try:
            if os.path.isfile(git_dir):
                with open(git_dir) as f:
                    git_dir = os.path.join(
                        path, f.read().removeprefix("gitdir:").strip()
                    )
            times.append(os.path.getmtime(os.path.join(git_dir, "index")))
        except OSError:
            pass
        if last_run and last_run.get("ended"):
            try:
                ended = datetime.fromisoformat(last_run["ended"])
                if ended.tzinfo is None:
                    ended = ended.replace(tzinfo=timezone.utc)
                times.append(ended.timestamp())
            except (TypeError, ValueError):
                pass
        if not times:
            return None
        return datetime.fromtimestamp(max(times), timezone.utc).isoformat()

    home = config.get_user_home()
    candidates: list[tuple[str, str]] = []
    for root_name in WORKSPACE_ROOTS:
        root = os.path.join(home, root_name)
        if os.path.isdir(root):
            for name in sorted(os.listdir(root)):
                candidates.append((os.path.join(root, name), "personal"))
    for path in cfg.get("workspaces", []):
        candidates.append((os.path.expanduser(path), "personal"))
    # Managed workspaces are laid out as <hub>/<owner>/<name>, and only
    # this hub's are its business
    hub_path = os.path.join(home, ".calkit", "workspaces", hub_key())
    if os.path.isdir(hub_path):
        for owner in sorted(os.listdir(hub_path)):
            owner_path = os.path.join(hub_path, owner)
            if not os.path.isdir(owner_path):
                continue
            for name in sorted(os.listdir(owner_path)):
                candidates.append((os.path.join(owner_path, name), "managed"))
    added = {
        os.path.realpath(os.path.expanduser(p))
        for p in cfg.get("workspaces", [])
    }
    found: dict[str, str] = {}
    for path, kind in candidates:
        path = os.path.realpath(path)
        if path in found or not os.path.isfile(
            os.path.join(path, "calkit.yaml")
        ):
            continue
        # Only this hub's projects, so other hubs never hear of them, unless
        # one was added on purpose
        if (
            kind == "personal"
            and path not in added
            and not is_on_this_hub(path)
        ):
            continue
        found[path] = kind

    def describe(path: str, kind: str) -> dict:
        try:
            project = calkit.detect_project_name(wdir=path)
        except Exception:
            project = None
        # Only names the hub could have, since it's whatever the repo says
        if not isinstance(project, str) or not re.fullmatch(
            r"[A-Za-z0-9._-]{1,128}/[A-Za-z0-9._-]{1,128}", project
        ):
            project = None
        # Another hub's link using it, which this one has to wait for,
        # without saying which hub, since that's none of this one's business
        holder = workspace_lock_holder(path)
        in_use_by = None
        if holder is not None and holder.get("hub") != get_hub_url():
            in_use_by = "another hub"
        ws = (
            dict(path=path, kind=kind, project=project, in_use_by=in_use_by)
            | _git_status(path)
            | get_run_state(path)
        )
        ws["last_activity"] = _last_activity(path, ws["last_run"])
        return ws

    from concurrent.futures import ThreadPoolExecutor

    # Mostly waiting on Git, so they're looked at together
    with ThreadPoolExecutor(max_workers=8) as pool:
        workspaces = list(pool.map(describe, found, found.values()))
    # What the hub is told of each, leaving out what's only for attaching
    # or reading its log
    agents = find_agents([ws["path"] for ws in workspaces])
    for ws in workspaces:
        ws["agents"] = [
            {
                k: agent[k]
                for k in ["tool", "pid", "started", "where", "app", "name"]
            }
            | {"status": agent["status"]}
            # As many as the hub takes
            for agent in agents.get(ws["path"], [])[:20]
        ]
    return workspaces


def check_in(
    cfg: dict,
    workspaces: list[dict],
    mode: str,
    connected: bool = True,
    restart_pending: bool = False,
    channel_sessions: list[str] | None = None,
) -> dict:
    from requests.exceptions import HTTPError

    from calkit.hub import core as hub

    try:
        resp: dict = hub._request(
            "post",
            "/machines/check-in",
            json=dict(
                calkit_version=calkit.__version__,
                workspaces=workspaces,
                mode=mode,
                connected=connected,
                restart_pending=restart_pending,
                channel_sessions=channel_sessions or [],
                # Kept by the hub the first time, e.g., for one installed
                # over SSH, and never replaced
                public_key=get_link_public_jwk(),
            ),
            headers={"Authorization": f"Bearer {cfg['token']}"},
            auth=False,
            allow_login=False,
            base_url=cfg["api_url"],
            max_retries=2,
        )
    except HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 403:
            raise LinkRevoked(str(e))
        if status == 409:
            # So 'calkit hub link install' registers it again
            cfg["key_rejected"] = True
            save_config(cfg)
            logger.error(
                "The hub has a different key for this machine, so it won't "
                "connect; run 'calkit hub link install' again"
            )
            raise LinkKeyRejected(str(e))
        raise
    # The hub's, which came over HTTPS, so it's what grants are checked with
    key = resp.get("grant_public_key")
    if key and key != cfg.get("grant_public_key"):
        if cfg.get("grant_public_key"):
            logger.info("The hub's grant key changed")
        cfg["grant_public_key"] = key
        save_config(cfg)
    return resp


@dataclass
class ChannelAuth:
    """What a channel's grant lets through: messages signed with the
    browser's key, in order, while the sign-in it came from and its second
    factor last.
    """

    key: Any
    session_id: str
    # The grant's ID, which replies are signed with, so they only count on
    # this channel
    grant_id: str = ""
    # The grant itself, which sessions opened on the channel show the hub
    # to get credentials
    grant: str = ""
    # When the second factor that let the grant be issued expires
    tfa_exp: float = float("inf")
    # The last message's sequence number, which the next one must follow
    seq: int = 0
    # The last reply's, likewise
    reply_seq: int = 0
    # Bytes of replies waiting to be sent
    backlog: int = 0


# Signed with each browser message, so a signature means nothing elsewhere
MESSAGE_SIGNATURE_CONTEXT = "calkit-machine-message"
# Likewise for each reply, which browsers check
REPLY_SIGNATURE_CONTEXT = "calkit-machine-reply"
# How many of its channels' sign-ins a check-in can ask about
MAX_CHANNEL_SESSIONS = 100


def _b64url_decode(value: str) -> bytes:
    import base64

    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def check_grant(
    cfg: dict, grant: Any, used: dict[str, float]
) -> ChannelAuth | None:
    """What a channel may do, if its grant is one the hub signed for this
    machine's owner, and hasn't been used or expired, nor has the second
    factor it was issued with.

    This, rather than the relay's word, is what decides who opened a
    channel, so the relay alone can't run anything here. The grant names
    the browser's public key, which every message must be signed with, so
    the relay, which carries the grant, can't use it either.
    """
    import base64
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )

    key = cfg.get("grant_public_key")
    if not isinstance(grant, str) or not key:
        return None
    try:
        payload = jwt.decode(
            grant,
            Ed25519PublicKey.from_public_bytes(base64.b64decode(key)),
            algorithms=["EdDSA"],
            audience=str(cfg["id"]),
            options={
                "require": [
                    "exp",
                    "iat",
                    "aud",
                    "sub",
                    "jti",
                    "cnf",
                    "sid",
                    "tfa_exp",
                ]
            },
            # For clocks that disagree with the hub's
            leeway=60,
        )
        jwk = payload["cnf"]["jwk"]
        if jwk["kty"] != "EC" or jwk["crv"] != "P-256":
            return None
        browser_key = ec.EllipticCurvePublicNumbers(
            int.from_bytes(_b64url_decode(jwk["x"]), "big"),
            int.from_bytes(_b64url_decode(jwk["y"]), "big"),
            ec.SECP256R1(),
        ).public_key()
    except (jwt.InvalidTokenError, ValueError, KeyError, TypeError):
        return None
    now = time.time()
    tfa_exp = payload["tfa_exp"]
    if (
        not isinstance(tfa_exp, int)
        or isinstance(tfa_exp, bool)
        or tfa_exp < now
    ):
        return None
    for jti, exp in list(used.items()):
        if exp + 60 < now:
            del used[jti]
    jti = payload["jti"]
    if (
        payload["sub"] != str(cfg["user_id"])
        or not isinstance(jti, str)
        or jti in used
    ):
        return None
    used[jti] = float(payload["exp"])
    return ChannelAuth(
        key=browser_key,
        session_id=str(payload["sid"]),
        grant_id=jti,
        tfa_exp=float(tfa_exp),
        grant=grant,
    )


def open_signed_message(auth: ChannelAuth, msg: Any) -> dict | None:
    """The message a browser sent, if it's signed with its channel's key
    and comes right after the last one, so the relay can neither forge,
    replay, nor drop one, e.g., a keystroke.

    Browsers send ``{"seq": ..., "body": ..., "sig": ...}``, where ``body``
    is the message as JSON text, signed as sent, so neither end has to
    encode it the same way.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import (
        encode_dss_signature,
    )

    if not isinstance(msg, dict):
        return None
    seq, body, sig = msg.get("seq"), msg.get("body"), msg.get("sig")
    if (
        not isinstance(seq, int)
        or isinstance(seq, bool)
        or seq != auth.seq + 1
        or not isinstance(body, str)
        or not isinstance(sig, str)
    ):
        return None
    try:
        # WebCrypto signs as r and s side by side, not DER
        raw = _b64url_decode(sig)
        if len(raw) != 64:
            return None
        auth.key.verify(
            encode_dss_signature(
                int.from_bytes(raw[:32], "big"),
                int.from_bytes(raw[32:], "big"),
            ),
            f"{MESSAGE_SIGNATURE_CONTEXT}\n{seq}\n{body}".encode(),
            ec.ECDSA(hashes.SHA256()),
        )
        inner = json.loads(body)
    except (InvalidSignature, ValueError):
        return None
    if not isinstance(inner, dict):
        return None
    auth.seq = seq
    return inner


def sign_reply(key: Any, auth: ChannelAuth, msg: dict) -> dict:
    """A message for a browser, signed with this link's key as WebCrypto
    would, for its channel, next in order, so the relay can neither forge,
    reorder, nor drop one, e.g., to swap the SSH key a user is shown.
    """
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import (
        decode_dss_signature,
    )

    seq = auth.reply_seq + 1
    # Unescaped, since escaping makes each non-ASCII character, e.g., a
    # TUI's box drawing, 6 to 12 bytes, which can push a chunk of output
    # past the relay's message limit
    body = json.dumps(msg, ensure_ascii=False)
    text = f"{REPLY_SIGNATURE_CONTEXT}\n{auth.grant_id}\n{seq}\n{body}"
    r, s = decode_dss_signature(
        key.sign(text.encode(), ec.ECDSA(hashes.SHA256()))
    )
    sig = base64.urlsafe_b64encode(
        r.to_bytes(32, "big") + s.to_bytes(32, "big")
    )
    return {"seq": seq, "body": body, "sig": sig.decode().rstrip("=")}


def get_shell() -> str:
    shell = os.environ.get("SHELL")
    if shell:
        return shell
    try:
        import pwd

        return pwd.getpwuid(os.getuid()).pw_shell or "/bin/sh"
    except (ImportError, KeyError):
        return "/bin/sh"


def child_env() -> dict[str, str]:
    """The environment for what runs in workspaces, without the link's
    own hub, so commands use the project's, as in any terminal.
    """
    env = dict(os.environ)
    if _inherited_hub is None:
        env.pop("CALKIT_HUB", None)
    else:
        env["CALKIT_HUB"] = _inherited_hub
    return env


def no_prompt_env(wdir: str, accept_new_hosts: bool = False) -> dict[str, str]:
    """The environment for what the hub runs here without a session, so Git
    and SSH fail rather than wait for a password nobody can type, e.g., on
    the terminal a link started in the foreground runs in.
    """
    env = dict(child_env(), GIT_TERMINAL_PROMPT="0")
    if "GIT_SSH_COMMAND" in env:
        return env
    # Unless the user chose how Git runs SSH
    try:
        ssh_command = subprocess.run(
            ["git", "config", "--get", "core.sshCommand"],
            cwd=wdir,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        ssh_command = ""
    if not ssh_command:
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=15"
        if accept_new_hosts:
            env["GIT_SSH_COMMAND"] += " -o StrictHostKeyChecking=accept-new"
    return env


def get_workspace_repo(wdir: str) -> git.Repo:
    """A workspace's repo, which runs Git so it can't prompt."""
    repo = calkit.git.get_repo(wdir)
    env = no_prompt_env(wdir)
    repo.git.update_environment(
        **{
            k: env[k]
            for k in ("GIT_TERMINAL_PROMPT", "GIT_SSH_COMMAND")
            if k in env
        }
    )
    return repo


# The link's own Calkit, since "-m calkit" would import modules in the
# working directory first, e.g., a calkit package in a checkout of Calkit
# itself, or a pty.py in the home folder a service starts in. On one line
# without quotes, so it goes in a crontab, systemd unit, or VBScript as is.
CALKIT_COMMAND = [
    sys.executable,
    "-c",
    "import sys; sys.path[0] or sys.path.pop(0); import calkit.cli; "
    "sys.argv[0] = calkit.__name__; calkit.cli.run()",
]


def _calkit(args: list[str], wdir: str) -> None:
    """Run Calkit in the link's interpreter, raising with its output if
    it fails.
    """
    result = subprocess.run(
        [*CALKIT_COMMAND, *args],
        cwd=wdir,
        env=no_prompt_env(wdir),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            (result.stderr or result.stdout).strip() or "Calkit failed"
        )


def get_workspace_git_status(wdir: str, fetch: bool = True) -> dict:
    """The Git part of a workspace's status and how far it is from its
    remote, which is quick, unlike the rest, so the hub shows it first.
    """
    errors = []
    git_repo = get_workspace_repo(wdir)
    if fetch:
        try:
            git_repo.git.fetch()
        except Exception as e:
            errors.append(dict(type="fetch", info=str(e)))
    ahead = behind = 0
    repo_status = git_repo.git.status(porcelain="v2", branch=True)
    # No remote or a detached HEAD means there's no ahead or behind
    match = re.search(r"#\sbranch\.ab\s\+(\d+)\s-(\d+)", repo_status)
    if match:
        ahead, behind = int(match.group(1)), int(match.group(2))
    return {
        "git": {
            "branch": None
            if git_repo.head.is_detached
            else git_repo.active_branch.name,
            "changed_files": calkit.git.get_changed_files(repo=git_repo),
            "staged_files": calkit.git.get_staged_files(repo=git_repo),
            "untracked_files": calkit.git.get_untracked_files(repo=git_repo),
        },
        "commits_ahead": ahead,
        "commits_behind": behind,
        "errors": errors,
    }


def get_stage_list(wdir: str, status: dict | None) -> list[dict]:
    """Every stage in a workspace's pipeline, in order, with its state and
    the questions whose answers rest on it, as evidence or upstream of it.

    Read from the DVC pipeline ``calkit status`` compiled, with the state and
    the questions' evidence from what it reported, if anything, else with no
    state.
    """
    from calkit.core import _load_yaml_readonly

    try:
        with _open_in_workspace(wdir, "dvc.yaml") as f:
            dvc_stages = (_load_yaml_readonly(f) or {}).get("stages") or {}
        with _open_in_workspace(wdir, "calkit.yaml") as f:
            ck_stages = (
                (_load_yaml_readonly(f) or {}).get("pipeline") or {}
            ).get("stages") or {}
    except Exception:
        return []
    if not isinstance(dvc_stages, dict):
        return []

    def paths(items: Any) -> list[tuple[str, bool]]:
        # Paths, and whether they're templated, e.g., per matrix item, in
        # which case only what comes before the template is known
        result = []
        for item in items or []:
            path = next(iter(item)) if isinstance(item, dict) else item
            if isinstance(path, str):
                prefix = path.split("${")[0].rstrip("/")
                result.append((prefix, "${" in path))
        return result

    outs = {
        name: paths(stage.get("outs"))
        for name, stage in dvc_stages.items()
        if isinstance(stage, dict)
    }
    # Who makes each path, and each folder something is made in, so an
    # input can be matched to what makes it, inside it, or around it
    makers: dict[str, set[str]] = {}
    makers_within: dict[str, set[str]] = {}
    templated = []
    for name, stage_outs in outs.items():
        for path, is_templated in stage_outs:
            if not path:
                continue
            if is_templated:
                templated.append((path, name))
            makers.setdefault(path, set()).add(name)
            parts = path.split("/")
            for i in range(1, len(parts)):
                makers_within.setdefault("/".join(parts[:i]), set()).add(name)

    def get_makers(dep: tuple[str, bool]) -> set[str]:
        path, is_templated = dep
        if not path:
            return set()
        found = set(makers.get(path, ())) | makers_within.get(path, set())
        parts = path.split("/")
        for i in range(1, len(parts)):
            found |= makers.get("/".join(parts[:i]), set())
        for prefix, name in templated:
            if path.startswith(prefix):
                found.add(name)
        # Templated inputs match what's made under what's known of them
        if is_templated:
            found |= {
                name
                for out, names in makers.items()
                if out.startswith(path)
                for name in names
            }
        return found

    # What each stage needs run first
    upstream = {
        name: set().union(
            *[get_makers(dep) for dep in paths(stage.get("deps"))]
        )
        - {name}
        for name, stage in dvc_stages.items()
        if isinstance(stage, dict)
    }

    def with_upstream(names: set[str]) -> set[str]:
        found, todo = set(), list(names)
        while todo:
            name = todo.pop()
            if name not in found:
                found.add(name)
                todo.extend(upstream.get(name, ()))
        return found

    pipeline = (status or {}).get("pipeline") or {}
    # DVC names matrix items stage@item, while both pipelines name the stage
    stale = {n.split("@")[0] for n in pipeline.get("stale_stage_names") or []}
    running = {n.split("@")[0] for n in pipeline.get("running_stages") or []}
    # Questions whose evidence a stage makes, and ones it only feeds
    questions: dict[str, list[int]] = {}
    feeds: dict[str, list[int]] = {}
    for question in ((status or {}).get("questions") or {}).get(
        "questions"
    ) or []:
        evidence = {
            ev["stage"].split("@")[0]
            for ev in question.get("evidence") or []
            if ev.get("stage")
        }
        for name in evidence:
            questions.setdefault(name, []).append(question["index"])
        for name in with_upstream(evidence) - evidence:
            feeds.setdefault(name, []).append(question["index"])
    stages = []
    for name in outs:
        ck_stage = ck_stages.get(name) if isinstance(ck_stages, dict) else None
        stages.append(
            dict(
                name=name,
                kind=ck_stage.get("kind")
                if isinstance(ck_stage, dict)
                else None,
                state=None
                if status is None
                else "running"
                if name in running
                else "stale"
                if name in stale
                else "ok",
                questions=questions.get(name, []),
                feeds_questions=feeds.get(name, []),
            )
        )
    return stages


def get_workspace_stages(wdir: str) -> dict:
    """The stage list without the status, which is quick to read, so it
    shows while the status is on its way.
    """
    return {"stages": get_stage_list(wdir, None)}


def trim_status(
    status: dict, max_bytes: int = MAX_SEND_BYTES - 50_000
) -> None:
    """Drop what the hub doesn't show from ``calkit status --json`` and
    shorten long path lists to their first few and a count, dropping why
    stages are stale altogether if it's still too large for one message.
    """

    def shorten(d: dict, key: str, limit: int) -> None:
        paths = d.get(key)
        if isinstance(paths, list) and len(paths) > limit:
            d[key] = paths[:limit]
            d[f"{key}_count"] = len(paths)

    pipeline = status.get("pipeline")
    stale = (
        pipeline.get("stale_stages") if isinstance(pipeline, dict) else None
    )
    if isinstance(stale, dict):
        for detail in stale.values():
            if not isinstance(detail, dict):
                continue
            detail.pop("raw_status", None)
            detail.pop("ignored_files_in_inputs", None)
            for key in (
                "modified_inputs",
                "modified_outputs",
                "stale_outputs",
            ):
                shorten(detail, key, MAX_STALE_PATHS)
    dvc = status.get("dvc")
    if isinstance(dvc, dict):
        dvc.pop("unchanged", None)
        # Only whether there are any is shown
        for key in ("not_in_cache", "not_in_remote"):
            shorten(dvc, key, MAX_STALE_PATHS)
        for key in ("uncommitted", "committed"):
            if isinstance(dvc.get(key), dict):
                for kind in list(dvc[key]):
                    shorten(dvc[key], kind, MAX_CHANGED_PATHS)
    if (
        isinstance(stale, dict)
        and len(json.dumps(status).encode()) > max_bytes
    ):
        pipeline["stale_stages"] = {}


def get_workspace_status(wdir: str, fetch: bool = True) -> dict:
    """A workspace's status as ``calkit status --json`` reports it, the same
    as the VS Code extension shows, plus how far it is from its remote.

    This is too expensive to run at every check-in, so the hub asks for it
    when someone is looking at the workspace, along with the Git part on its
    own, which a large pipeline can't hold up.
    """
    git_status = get_workspace_git_status(wdir, fetch=fetch)
    errors = git_status["errors"]
    result = subprocess.run(
        # Checking environments can build them, running whatever a repo's
        # specs say, which viewing status shouldn't do; the record of their
        # last checks is reported instead
        [*CALKIT_COMMAND, "status", "--json", "--no-env-check"],
        cwd=wdir,
        env=no_prompt_env(wdir),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        errors="replace",
    )
    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError:
        status = None
        errors.append(
            dict(
                type="status",
                info=(result.stderr or result.stdout).strip()
                or "Failed to get status",
            )
        )
    stages = get_stage_list(wdir, status)
    if isinstance(status, dict):
        trim_status(status)
    return {
        "status": status,
        "stages": stages,
        "commits_ahead": git_status["commits_ahead"],
        "commits_behind": git_status["commits_behind"],
        "errors": errors,
    }


def _agent_tool(cmdline: list[str]) -> str | None:
    """Which coding agent a command line runs, if any, e.g., 'claude'."""
    names = [os.path.basename(arg) for arg in cmdline[:2]]
    if names and names[0] in AGENT_TOOLS:
        return names[0]
    # Ones run as scripts, e.g., with Node
    if len(names) == 2 and names[0] in ("node", "bun"):
        name = names[1].removesuffix(".js")
        if name in AGENT_TOOLS:
            return name
    return None


def find_agents(paths: list[str]) -> dict[str, list[dict]]:
    """Coding agents running in workspaces, by workspace, however they were
    started, e.g., in an editor's terminal, tmux, or a session.
    """
    from datetime import datetime, timezone

    import psutil

    found: dict[str, list[dict]] = {}
    # Each process is read inside the try, since one that exits meanwhile
    # can make psutil raise SystemError, which would end the whole scan
    for proc in psutil.process_iter():
        try:
            tool = _agent_tool(proc.cmdline())
            if tool is None:
                continue
            cwd = os.path.realpath(proc.cwd())
            parents = proc.parents()
        except (psutil.Error, OSError, SystemError):
            continue

        def runs_tool(p: Any) -> bool:
            try:
                return _agent_tool(p.cmdline()) == tool
            except (psutil.Error, OSError, SystemError):
                return False

        # An agent's own helpers, e.g., subagents, aren't others
        if any(runs_tool(p) for p in parents):
            continue
        wdir = next(
            (p for p in paths if cwd == p or cwd.startswith(p + os.sep)), None
        )
        if wdir is None:
            continue
        try:
            env = proc.environ()
        except (psutil.Error, OSError, SystemError):
            env = {}
        # tmux names its socket and the pane in what it starts
        tmux = None
        if env.get("TMUX") and env.get("TMUX_PANE"):
            tmux = dict(
                socket=env["TMUX"].split(",")[0], pane=env["TMUX_PANE"]
            )
        if any(p.pid == os.getpid() for p in parents):
            where = "session"
        elif tmux is not None:
            where = "tmux"
        else:
            where = "terminal"
        # What it was started from, e.g., 'Code' or 'Terminal', is the
        # furthest ancestor short of the system's own
        apps = [p for p in parents if p.pid > 1]
        try:
            app = apps[-1].name()[:256] if apps else None
        except (psutil.Error, SystemError):
            app = None
        agent: dict[str, Any] = dict(
            tool=tool,
            pid=proc.pid,
            started=datetime.fromtimestamp(
                proc.create_time(), timezone.utc
            ).isoformat(),
            where=where,
            app=app,
            name=None,
            status=None,
            tmux=tmux,
            cwd=cwd,
        )
        # Claude Code keeps a record of each process, with its
        # conversation, the name it was given, and what it's doing
        if tool == "claude":
            try:
                with open(
                    os.path.join(
                        config.get_user_home(),
                        ".claude",
                        "sessions",
                        f"{proc.pid}.json",
                    )
                ) as f:
                    record = json.load(f)
                # Within what the hub takes, which refuses the whole
                # check-in otherwise
                for key, limit in (("name", 256), ("status", 64)):
                    value = record.get(key)
                    if isinstance(value, str):
                        agent[key] = value[:limit]
                agent["conversation"] = record.get("sessionId")
                agent["cwd"] = record.get("cwd") or cwd
            except (OSError, ValueError, AttributeError):
                pass
        found.setdefault(wdir, []).append(agent)
    return found


def _get_agent(wdir: str, pid: int) -> dict:
    agent = next(
        (a for a in find_agents([wdir]).get(wdir, []) if a["pid"] == pid),
        None,
    )
    if agent is None:
        raise ValueError("No agent with that PID is running in this workspace")
    return agent


def get_agent_log(wdir: str, pid: int, limit: int = 40) -> dict:
    """The end of a running agent's conversation, from the log it keeps,
    which is how one that can't be attached to can be followed.
    """
    from datetime import datetime

    agent = _get_agent(wdir, pid)
    home = config.get_user_home()
    path = None
    if agent["tool"] == "claude" and agent.get("conversation"):
        # Logs are kept by folder, named for it with anything but letters
        # and digits as dashes
        path = os.path.join(
            home,
            ".claude",
            "projects",
            re.sub(r"[^A-Za-z0-9]", "-", agent["cwd"]),
            f"{agent['conversation']}.jsonl",
        )
    elif agent["tool"] == "codex":
        # Kept by day, each saying where it was started first, so the
        # latest from here since the process started is its own
        started = datetime.fromisoformat(agent["started"])
        candidates = []
        sessions_dir = os.path.join(home, ".codex", "sessions")
        for root, _, files in os.walk(sessions_dir):
            for name in files:
                full = os.path.join(root, name)
                try:
                    if (
                        name.endswith(".jsonl")
                        and os.path.getmtime(full) >= started.timestamp()
                    ):
                        candidates.append(full)
                except OSError:
                    pass
        for full in sorted(candidates, key=os.path.getmtime, reverse=True):
            try:
                with open(full) as f:
                    meta = json.loads(f.readline())
            except (OSError, ValueError):
                continue
            cwd = (meta.get("payload") or {}).get("cwd")
            if cwd and os.path.realpath(cwd) == agent["cwd"]:
                path = full
                break
    if path is None or not os.path.isfile(path):
        return {"entries": None, "tool": agent["tool"]}
    # Logs can be large, so only the end is read
    with open(path, "rb") as log_file:
        log_file.seek(0, os.SEEK_END)
        size = log_file.tell()
        log_file.seek(max(0, size - 2_000_000))
        lines = log_file.read().decode("utf-8", errors="replace").splitlines()
    if size > 2_000_000:
        lines = lines[1:]
    entries = []

    def add(role: str, text: Any, time: str | None) -> None:
        if isinstance(text, str) and text.strip():
            entries.append(
                dict(role=role, text=text.strip()[:4000], time=time)
            )

    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        time = item.get("timestamp")
        if agent["tool"] == "claude":
            if item.get("type") not in ("user", "assistant"):
                continue
            content = (item.get("message") or {}).get("content")
            if isinstance(content, str):
                content = [dict(type="text", text=content)]
            for part in content or []:
                if part.get("type") == "tool_use":
                    tool_input = part.get("input") or {}
                    detail = tool_input.get("description") or (
                        tool_input.get("command")
                        or tool_input.get("file_path")
                        or ""
                    )
                    add("tool", f"{part.get('name')}: {detail}", time)
                    continue
                text = part.get("text")
                if part.get("type") != "text" or not isinstance(text, str):
                    continue
                # What Claude Code adds itself comes as tagged user text,
                # e.g., notices of background tasks and slash commands
                tag = re.match(r"<([\w-]+)>", text.lstrip())
                if item["type"] == "assistant" or tag is None:
                    add(item["type"], text, time)
                elif tag[1] == "task-notification":
                    summary = re.search(
                        r"<summary>(.*?)</summary>", text, re.S
                    )
                    if summary:
                        add("event", summary[1], time)
                elif tag[1] == "command-name":
                    command = re.search(r"<command-name>(.*?)</", text, re.S)
                    args = re.search(r"<command-args>(.*?)</", text, re.S)
                    add(
                        "user",
                        " ".join(m[1].strip() for m in (command, args) if m),
                        time,
                    )
                elif tag[1] == "local-command-stdout":
                    stdout = re.search(r">(.*)</", text, re.S)
                    if stdout:
                        add(
                            "event",
                            re.sub(r"\x1b\[[0-9;]*m", "", stdout[1]),
                            time,
                        )
                elif tag[1] not in ("local-command-caveat", "system-reminder"):
                    add("user", text, time)
        else:
            payload = item.get("payload") or {}
            if item.get("type") != "response_item":
                continue
            if payload.get("type") == "message" and payload.get("role") in (
                "user",
                "assistant",
            ):
                for part in payload.get("content") or []:
                    text = part.get("text")
                    # Context Codex adds itself comes as tagged user text
                    if payload["role"] == "user" and str(text).startswith("<"):
                        continue
                    add(payload["role"], text, time)
            elif payload.get("type") in ("function_call", "custom_tool_call"):
                add("tool", str(payload.get("name")), time)
    return {"entries": entries[-limit:], "tool": agent["tool"]}


def get_run_state(wdir: str) -> dict:
    """What the pipeline is doing, or last did, from the files a run leaves,
    which are cheap enough to read at every check-in.

    The running part is what `calkit status` reports during a run, and
    `calkit run` records how each run ended.
    """
    from calkit.cli.main.core import _get_running_pipeline_status

    state: dict[str, Any] = dict(
        running=False, running_stages=[], running_since=None, last_run=None
    )
    running = _get_running_pipeline_status(wdir)
    if running is not None:
        state["running"] = True
        stages = running["running_stages"]
        state["running_stages"] = [s[:256] for s in stages[:50]]
        starts = [
            running["stages"][name]["start_time"]
            for name in stages
            if "start_time" in running["stages"].get(name, {})
        ]
        if starts:
            # Logged in UTC, without saying so
            state["running_since"] = min(starts) + "+00:00"
    runs_dir = os.path.join(wdir, ".calkit", "local", "runs")
    try:
        names = [f for f in os.listdir(runs_dir) if f.endswith(".json")]
    except OSError:
        names = []
    # Named by start time, so the latest sorts last
    record = os.path.join(runs_dir, max(names)) if names else None
    if record is not None:
        try:
            with _open_in_workspace(wdir, os.path.relpath(record, wdir)) as f:
                run = json.load(f)
            state["last_run"] = dict(
                status=run["status"],
                started=run["start_time"],
                ended=run["end_time"],
                failed_stages=[
                    name[:256]
                    for name, i in (run.get("stages") or {}).items()
                    if i.get("status") == "failed"
                ][:50],
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
    return state


def pull_workspace(wdir: str, merge: bool = False) -> dict:
    """Pull with Git, then with DVC.

    Only fast-forwards unless asked to merge, saying when the branches have
    diverged so that can be asked. A merge with conflicts is undone, since
    resolving them takes a session.
    """
    from git.exc import GitCommandError

    git_repo = get_workspace_repo(wdir)
    if not merge:
        try:
            git_repo.git.pull("--ff-only")
        except GitCommandError as e:
            if "Not possible to fast-forward" in str(e):
                return {"diverged": True}
            raise
    else:
        try:
            git_repo.git.pull("--no-rebase", "--no-edit")
        except GitCommandError:
            conflicts = git_repo.git.diff(
                "--name-only", "--diff-filter=U"
            ).split()
            if not conflicts:
                raise
            git_repo.git.merge("--abort")
            raise ValueError(
                "Merging would conflict in "
                + ", ".join(conflicts[:10])
                + (", ..." if len(conflicts) > 10 else "")
                + "; resolve it in a session"
            )
    _calkit(["dvc", "pull"], wdir)
    return {"diverged": False}


def push_workspace(wdir: str) -> None:
    """Push with DVC, then with Git."""
    _calkit(["dvc", "push"], wdir)
    git_repo = get_workspace_repo(wdir)
    git_repo.git.push("origin", git_repo.active_branch.name)


def check_workspace_path(wdir: str, path: str) -> str:
    """Refuse a path from the hub that isn't a plain one inside the
    workspace, e.g., one Git or Calkit would take as an option.
    """
    if (
        not isinstance(path, str)
        or not path
        or path.startswith("-")
        or any(c in path for c in "\n\r\0")
        or os.path.isabs(path)
    ):
        raise ValueError(f"Invalid path '{path}'")
    root = os.path.realpath(wdir)
    full = os.path.realpath(os.path.join(root, path))
    if full != root and not full.startswith(root + os.sep):
        raise ValueError(f"{path} is outside the workspace")
    return path


def save_workspace(
    wdir: str,
    paths: list[str],
    message: str | None = None,
    to: str | None = None,
    push: bool = False,
) -> None:
    """Add and commit paths, to Git or DVC as Calkit decides unless told,
    and optionally push.
    """
    if not paths:
        raise ValueError("No paths to save")
    for path in paths:
        check_workspace_path(wdir, path)
    repo = get_workspace_repo(wdir)
    # Credentials a repo's own .gitignore can let through, e.g., the hub's
    # token in .dvc/config.local, never go in a commit, which the hub would
    # then offer to push
    candidates = repo.git.ls_files(
        "-z", "--cached", "--others", "--exclude-standard", "--", *paths
    ).split("\0")
    for fpath in [*paths, *candidates]:
        parts = os.path.normpath(fpath).replace(os.sep, "/").lower()
        if re.search(r"(^|/)(\.dvc/config\.local|\.calkit/local)(/|$)", parts):
            raise ValueError(f"{fpath} holds this machine's credentials")
    # Only what was asked for goes in the commit, so what the user staged is
    # set aside and put back after, except for what was committed
    from git.exc import GitCommandError

    try:
        staged = repo.git.write_tree()
    except GitCommandError:
        raise ValueError("Finish the merge in a session first")
    before = repo.head.commit.hexsha if repo.head.is_valid() else None
    repo.git.reset()
    args = ["add", *paths, "--commit-message"]
    args.append(message or f"Update {', '.join(paths)}")
    if to is not None:
        args += ["--to", to]
    if push:
        args.append("--push")
    try:
        _calkit(args, wdir)
    finally:
        after = repo.head.commit.hexsha if repo.head.is_valid() else None
        repo.git.read_tree(staged)
        if after is not None and after != before:
            if before is None:
                committed = repo.git.ls_tree("-r", "--name-only", "-z", after)
            else:
                committed = repo.git.diff("--name-only", "-z", before, after)
            committed_paths = [p for p in committed.split("\0") if p]
            if committed_paths:
                repo.git.reset(
                    "-q",
                    after,
                    "--",
                    *[f":(literal){p}" for p in committed_paths],
                )


def ignore_path(
    wdir: str,
    path: str,
    commit: bool = True,
    message: str | None = None,
    push: bool = False,
) -> None:
    check_workspace_path(wdir, path)
    git_repo = get_workspace_repo(wdir)
    if git_repo.ignored(path):
        return
    txt = ""
    if os.path.lexists(os.path.join(wdir, ".gitignore")):
        with _open_in_workspace(wdir, ".gitignore") as f:
            txt = f.read()
    if txt and not txt.endswith("\n"):
        txt += "\n"
    with _open_in_workspace(wdir, ".gitignore", "w") as f:
        f.write(txt + path + "\n")
    if commit:
        git_repo.git.add(".gitignore")
        # Only that file, leaving anything else the user staged
        git_repo.git.commit(
            ["-m", message or f"Ignore {path}", "--", ".gitignore"]
        )
        if push:
            git_repo.git.push("origin", git_repo.active_branch.name)


def discard_changes(wdir: str) -> dict:
    """Put a workspace back to its last commit with ``calkit stash``, so
    ``calkit stash pop`` brings back what was discarded, DVC-tracked data
    included. New files are left alone.
    """
    repo = get_workspace_repo(wdir)

    def stash_count() -> int:
        return len(repo.git.stash("list").splitlines())

    before = stash_count()
    stamp = calkit.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    _calkit(["stash", "-m", f"Discarded from the hub at {stamp}"], wdir)
    return {"stashed": stash_count() > before}


def add_stage(
    wdir: str,
    name: str,
    cmd: str,
    deps: list[str] | None = None,
    outs: list[str] | None = None,
    calkit_type: str | None = None,
    calkit_object: dict | None = None,
    push: bool = False,
) -> None:
    """Add a stage to the DVC pipeline and commit it, along with a Calkit
    object for its output if given one.
    """
    for path in [*(deps or []), *(outs or [])]:
        check_workspace_path(wdir, path)
    # Both are written back, which mustn't go through a link
    for fname in ("dvc.yaml", "calkit.yaml"):
        if os.path.islink(os.path.join(wdir, fname)):
            raise ValueError(f"{fname} is a link, which won't be followed")
    if calkit_type is not None:
        if calkit_type not in ("figure", "dataset", "publication"):
            raise ValueError(f"Unknown object type '{calkit_type}'")
        if calkit_object is None or not outs or len(outs) != 1:
            raise ValueError("An object needs its info and one output")
        # Checked before anything is written, so a refusal leaves nothing
        # behind
        ck_info = calkit.load_calkit_info(wdir=wdir)
        objs = ck_info.get(calkit_type + "s", [])
        if outs[0] in [obj.get("path") for obj in objs]:
            raise ValueError(f"A {calkit_type} already exists at {outs[0]}")
    pipeline: dict = {}
    if os.path.lexists(os.path.join(wdir, "dvc.yaml")):
        with _open_in_workspace(wdir, "dvc.yaml") as f:
            pipeline = calkit.ryaml.load(f) or {}
    stages = pipeline.get("stages", {})
    if name in stages:
        raise ValueError(f"A stage named '{name}' already exists")
    existing_outs = [
        out for stage in stages.values() for out in stage.get("outs", [])
    ]
    for out in outs or []:
        if out in existing_outs:
            raise ValueError(f"{out} is already another stage's output")
    stage: dict = {"cmd": cmd}
    if deps:
        stage["deps"] = deps
    if outs:
        stage["outs"] = outs
    stages[name] = stage
    pipeline["stages"] = stages
    with _open_in_workspace(wdir, "dvc.yaml", "w") as f:
        calkit.ryaml.dump(pipeline, f)
    repo = get_workspace_repo(wdir)
    changed = ["dvc.yaml"]
    if calkit_type is not None:
        assert outs is not None and calkit_object is not None
        objs.append(dict(path=outs[0], stage=name) | calkit_object)
        ck_info[calkit_type + "s"] = objs
        with _open_in_workspace(wdir, "calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        changed.append("calkit.yaml")
    repo.git.add(changed)
    # Only those files, leaving anything else the user staged
    repo.git.commit(["-m", f"Add pipeline stage {name}", "--", *changed])
    if push:
        repo.git.push(["origin", repo.active_branch.name])


# Runs the hub started, by workspace, so they can be stopped
_runs: dict[str, subprocess.Popen] = {}


def run_pipeline(wdir: str, stages: list[str] | None = None) -> dict:
    """Run the pipeline, or some of its stages, without a terminal,
    returning whether it succeeded and the end of its output.

    The hub follows it meanwhile through its log, as it does runs started
    any other way.
    """
    # Stage names become arguments, so they can't be options
    for stage in stages or []:
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:/-]*", str(stage)):
            raise ValueError(f"Invalid stage name '{stage}'")
    proc = subprocess.Popen(
        [*CALKIT_COMMAND, "run", *(stages or [])],
        cwd=wdir,
        env=no_prompt_env(wdir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        # Stages can print anything, and a decoding error would leave the
        # run blocked on a pipe nobody reads
        errors="replace",
        # Its own process group, so stopping it reaches its stages too
        start_new_session=sys.platform != "win32",
    )
    _runs[wdir] = proc
    # Only the end is kept, however much it prints, which is all that's
    # sent, kept well under the relay's message limit
    output = ""
    try:
        assert proc.stdout is not None
        while chunk := proc.stdout.read(65536):
            output = (output + chunk)[-50_000:]
        proc.wait()
    finally:
        _runs.pop(wdir, None)
    return {"ok": proc.returncode == 0, "output": output}


def stop_run(wdir: str) -> dict:
    """Stop the run in progress, as Ctrl+C would, whether the hub or
    someone in a terminal started it.
    """
    import signal

    import psutil

    proc = _runs.get(wdir)
    if proc is not None:
        pids = [proc.pid]
    else:
        pids = [
            p["pid"]
            for p in calkit.dvc.get_running_pipeline_processes(wdir)
            if p.get("pid")
        ]
    if not pids:
        raise ValueError("No run is in progress")
    for pid in pids:
        try:
            if sys.platform == "win32":
                psutil.Process(pid).terminate()
            elif proc is not None:
                os.killpg(pid, signal.SIGINT)
            else:
                os.kill(pid, signal.SIGINT)
        except (OSError, psutil.Error):
            pass
    return {}


def get_run_log(wdir: str) -> dict:
    """The latest run's log, as far as it has got, for following a run."""
    from calkit.cli.main.core import _get_latest_run_log_path

    fpath = _get_latest_run_log_path(wdir)
    if fpath is None:
        return {"name": None, "log": None}
    # Only the end, since a log can be large
    try:
        with open(
            fpath, "rb", opener=lambda p, f: os.open(p, f | NOFOLLOW)
        ) as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 200_000))
            log = f.read().decode("utf-8", errors="replace")
    except OSError:
        return {"name": None, "log": None}
    # Named by when it started
    return {"name": os.path.basename(fpath), "log": log[-50_000:]}


def _check_repo_url(git_repo_url: Any) -> None:
    # Only the kinds of URL projects have, so nothing else Git can fetch
    # from, e.g., local paths or other transports, can be named, and only
    # the host it names is contacted
    host = r"[A-Za-z0-9][A-Za-z0-9.-]*"
    path = r"[A-Za-z0-9][A-Za-z0-9._~/-]*"
    if not isinstance(git_repo_url, str) or not re.fullmatch(
        rf"https://{host}(:[0-9]{{1,5}})?/{path}|git@{host}:{path}",
        git_repo_url,
    ):
        raise ValueError(f"Can't clone {git_repo_url}")


def clone_project(git_repo_url: str, path: str | None = None) -> str:
    """Clone a project into a new workspace, by default ``~/calkit/<name>``,
    returning its path.

    The clone uses this machine's own Git credentials. Another path must be
    in the user's home folder, outside hidden folders, e.g., ``~/.ssh``.
    """
    _check_repo_url(git_repo_url)
    home = os.path.realpath(config.get_user_home())
    name = git_repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name.startswith("."):
        raise ValueError(f"Can't clone {git_repo_url}")
    path = (path or "").strip()
    if not path:
        dest = os.path.join(home, "calkit", name)
    else:
        if path == "~" or path.startswith("~/"):
            path = home + path[1:]
        if not os.path.isabs(path):
            raise ValueError(
                f"{path} isn't a full path, e.g., ~/calkit/{name}"
            )
        dest = os.path.normpath(path)
    # Through any links, so the checks below are on where it really goes
    dest = os.path.join(
        os.path.realpath(os.path.dirname(dest)), os.path.basename(dest)
    )
    if dest == home or os.path.commonpath([home, dest]) != home:
        raise ValueError(f"{dest} isn't in your home folder")
    parts = os.path.relpath(dest, home).split(os.sep)
    if any(part.startswith(".") for part in parts) or not re.fullmatch(
        r"[A-Za-z0-9._-]+", parts[-1]
    ):
        raise ValueError(f"Can't clone into {dest}")
    if os.path.exists(dest):
        raise ValueError(f"{dest} already exists")
    parent = os.path.dirname(dest)
    os.makedirs(parent, exist_ok=True)
    # Pulling data can be slow or need credentials, so it's left to an
    # explicit pull
    _calkit(["clone", git_repo_url, dest, "--no-dvc-pull"], parent)
    return dest


def check_machine_setup(git_repo_url: str) -> dict:
    """What this machine needs before a project is cloned onto it: Git's name
    and email for commits, access to the project's repository, and a Calkit
    token for the hub, which pulling and pushing data use.
    """
    _check_repo_url(git_repo_url)
    home = config.get_user_home()

    def get_git_config(key: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", "config", "--get", key],
                cwd=home,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
        except (subprocess.SubprocessError, OSError):
            return None
        return out or None

    # A new host's key is accepted, as someone answering yes would, so the
    # clone after this knows it
    env = no_prompt_env(home, accept_new_hosts=True)
    error = None
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--exit-code", git_repo_url, "HEAD"],
            cwd=home,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=45,
        )
        # 2 means it was reached but has no commits yet
        if result.returncode not in (0, 2):
            lines = result.stderr.strip().splitlines()
            error = lines[-1] if lines else "Git couldn't reach it"
    except subprocess.TimeoutExpired:
        error = "Timed out"
    except OSError as e:
        error = str(e)
    if git_repo_url.startswith("git@"):
        host = git_repo_url[4:].split(":")[0]
    else:
        host = git_repo_url.split("/")[2]
    return {
        "git_name": get_git_config("user.name"),
        "git_email": get_git_config("user.email"),
        "repo": {
            "host": host,
            "ssh": git_repo_url.startswith("git@"),
            "error": error,
        },
        # This link's hub's, which the project is on
        "token": bool(config.read().token),
    }


def get_ssh_public_key() -> dict:
    """This machine's SSH public key, made first if it has none, for the
    owner to add to their Git host, as 'calkit config github-ssh' does.

    A new key has no passphrase, since the link runs Git with nobody
    there to type one.
    """
    ssh_dir = os.path.join(config.get_user_home(), ".ssh")
    # The ones SSH tries by default, in its order
    for name in ("id_ed25519", "id_ecdsa", "id_rsa"):
        key = os.path.join(ssh_dir, name)
        if os.path.isfile(key) and os.path.isfile(key + ".pub"):
            with open(key + ".pub") as f:
                return {"public_key": f.read().strip(), "created": False}
    os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
    key = os.path.join(ssh_dir, "id_ed25519")
    try:
        email = subprocess.run(
            ["git", "config", "--get", "user.email"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        email = ""
    subprocess.run(
        [
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            email or f"calkit-hub-link@{socket.gethostname()}",
            "-f",
            key,
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=True,
    )
    with open(key + ".pub") as f:
        return {"public_key": f.read().strip(), "created": True}


def request_cli_token(cfg: dict) -> str:
    """A token for Calkit here, which the owner just asked the hub for, from
    the hub over HTTPS, so it never passes through the relay.
    """
    from requests.exceptions import HTTPError

    from calkit.hub import core as hub

    try:
        resp = hub._request(
            "post",
            "/machines/cli-token",
            headers={"Authorization": f"Bearer {cfg['token']}"},
            auth=False,
            allow_login=False,
            base_url=cfg["api_url"],
            max_retries=2,
        )
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            raise ValueError("The hub didn't ask for a token; try again")
        raise
    token = resp.get("token") if isinstance(resp, dict) else None
    if not isinstance(token, str) or not re.fullmatch(
        r"ckp_[0-9a-f]{16,128}", token
    ):
        raise ValueError("The hub sent an invalid token")
    return token


def request_session_credential(cfg: dict, route: str, grant: str) -> str:
    """A credential for one of this link's sessions from the hub, over
    HTTPS: a token for Calkit (``session-token``) or the owner's GitHub
    token (``github-token``), for the grant that opened the session.
    """
    from requests.exceptions import HTTPError

    from calkit.hub import core as hub

    try:
        resp = hub._request(
            "post",
            f"/machines/{route}",
            json={"grant": grant},
            headers={"Authorization": f"Bearer {cfg['token']}"},
            auth=False,
            allow_login=False,
            base_url=cfg["api_url"],
            max_retries=2,
        )
    except HTTPError as e:
        # With the hub's reason, e.g., that the sign-in ended
        raise ValueError(str(e))
    token = resp.get("token") if isinstance(resp, dict) else None
    if not isinstance(token, str) or not re.fullmatch(r"[\x21-\x7e]+", token):
        raise ValueError("The hub sent an invalid token")
    return token


def configure_machine(
    git_name: str | None = None,
    git_email: str | None = None,
    token: bool = False,
    cfg: dict | None = None,
) -> dict:
    """Set up what ``check_machine_setup`` found missing, as the owner asked
    from the hub, which asks it for a token for Calkit here, if one's wanted.
    """
    import keyring.errors

    if not isinstance(token, bool):
        raise ValueError("Invalid token request")
    home = config.get_user_home()
    for key, value in [("user.name", git_name), ("user.email", git_email)]:
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"Invalid {key.removeprefix('user.')}")
        value = value.strip()
        if (
            not value
            or len(value) > 256
            or any(c in value for c in "\n\r\0")
            or (key == "user.email" and "@" not in value)
        ):
            raise ValueError(f"Invalid {key.removeprefix('user.')}")
        subprocess.run(
            ["git", "config", "--global", key, value],
            cwd=home,
            capture_output=True,
            timeout=10,
            check=True,
        )
    if token:
        if cfg is None:
            raise ValueError("Invalid token request")
        new_token = request_cli_token(cfg)
        try:
            settings = config.read()
            settings = config.Settings.model_validate(
                settings.model_dump() | {"token": new_token}
            )
            settings.write()
        except keyring.errors.KeyringError:
            # E.g., a service started at boot, before the user unlocked it
            raise RuntimeError(
                "Couldn't store the token in this machine's keyring; run "
                "'calkit config set token' there instead"
            )
    return {}


def new_workspace(wdir: str, branch: str) -> dict:
    """Create another workspace for the project in ``wdir`` on ``branch``,
    as a worktree sharing its DVC cache, returning its path.

    It goes beside ``wdir`` if that's in a folder workspaces are found in,
    else in ``~/calkit``.
    """
    # A branch name, which can't be an option or climb out of the folder
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch) or (
        ".." in branch
    ):
        raise ValueError(f"Invalid branch name '{branch}'")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-.")
    home = config.get_user_home()
    roots = [os.path.realpath(os.path.join(home, r)) for r in WORKSPACE_ROOTS]
    import git

    # Named after the main checkout when this is a worktree itself
    main = wdir
    try:
        repo = git.Repo(wdir)
        main = os.path.dirname(os.path.abspath(repo.common_dir))
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        pass
    parent = os.path.dirname(os.path.realpath(main))
    if parent not in roots:
        parent = roots[0]
    path = os.path.join(parent, f"{os.path.basename(main)}-{name}")
    _calkit(["new", "workspace", branch, "--path", path], wdir)
    return {"path": path}


# Browser requests that act on a workspace, run off the event loop since
# they wait on Git, DVC, and the network
WORKSPACE_ACTIONS: dict[str, Any] = {
    "workspace.status": get_workspace_status,
    "workspace.git_status": get_workspace_git_status,
    "workspace.stages": get_workspace_stages,
    "workspace.agent_log": get_agent_log,
    "workspace.pull": pull_workspace,
    "workspace.push": push_workspace,
    "workspace.save": save_workspace,
    "workspace.ignore": ignore_path,
    "workspace.discard": discard_changes,
    "workspace.add_stage": add_stage,
    "workspace.run": run_pipeline,
    "workspace.stop": stop_run,
    "workspace.run_log": get_run_log,
    "workspace.new": new_workspace,
}
# Browser requests about the machine rather than a workspace, also run off
# the event loop
MACHINE_ACTIONS = {
    "workspaces.clone",
    "machine.check",
    "machine.configure",
    "machine.ssh_key",
}
# Actions that change nothing, so needn't take the workspace from other
# hubs' links, and may act on managed workspaces too
READ_ONLY_ACTIONS = {
    "workspace.status",
    "workspace.git_status",
    "workspace.stages",
    "workspace.run_log",
    "workspace.agent_log",
}
# Ones quick and harmless enough to not wait on what else is going on there,
# e.g., the rest of the status, which can take a while for a large pipeline
LOCK_FREE_ACTIONS = {
    "workspace.git_status",
    "workspace.stages",
    "workspace.run_log",
    "workspace.agent_log",
}


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
    # Input the terminal couldn't take yet, e.g., the rest of a long paste
    input_buffer: bytearray = field(default_factory=bytearray)
    decoder: Any = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")(
            errors="replace"
        )
    )
    # The channel whose grant it gets credentials with, and where it asks
    # for them: a socket in a folder only the user can open, with a secret
    # only the session is told, and what's been got, by hub route, with
    # when to get it again
    auth: ChannelAuth | None = None
    cred_dir: str | None = None
    cred_sock: Any = None
    cred_server: asyncio.Task | None = None
    cred_secret: str = ""
    credentials: dict[str, tuple[str, float]] = field(default_factory=dict)
    cred_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def label(self) -> str:
        """What's running in the foreground, e.g., 'bash' or 'claude'."""
        import psutil

        try:
            proc = psutil.Process(os.tcgetpgrp(self.fd))
            name = str(proc.name())
            # Some name their process for their version, e.g., Claude Code
            if name[:1].isdigit():
                name = os.path.basename(proc.cmdline()[0]) or name
            return name
        except (OSError, IndexError, SystemError, psutil.Error):
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


class HubLink:
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
        # Browser channels, which are all the owner's, and what each may do
        self.channels: dict[str, ChannelAuth] = {}
        # IDs of grants channels were opened with, and when they expire,
        # read from where they're kept across restarts when first needed
        self.used_grants: dict[str, float] | None = None
        # The key replies are signed with, likewise
        self.key: Any = None
        self.workspaces: list[dict] = []
        self.ws: Any = None
        # What's waiting to go to the relay, in order, and what sends it
        self.outbox: deque[tuple[str | None, str]] = deque()
        self.writer: asyncio.Task | None = None
        # When it last heard from the hub, by the monotonic clock
        self.last_check_in: float | None = None
        self.check_in_interval = 60
        # One Git or DVC operation at a time per workspace, and which
        self.workspace_locks: dict[str, asyncio.Lock] = {}
        self.workspace_actions: dict[str, str] = {}
        # Workspaces this link holds the lock for, against other hubs'
        self.claimed: set[str] = set()
        self.connected_check_in: asyncio.Task | None = None
        # Asked for by the hub or 'calkit upgrade', and done once idle
        self.restart_requested = False
        self.stop_requested = False
        self.restarting = False

    def send_soon(self, ch: str, msg: dict) -> None:
        """Sign a message for a browser's channel and queue it for the relay,
        which only passes it on, in the order they were queued.
        """
        auth = self.channels.get(ch)
        if auth is None or self.ws is None:
            return
        if self.key is None:
            self.key = get_link_key()
        signed = sign_reply(self.key, auth, msg)
        text = json.dumps({"ch": ch, "msg": signed}, ensure_ascii=False)
        size = len(text.encode())
        if size > MAX_SEND_BYTES:
            # The relay would close the connection over it, so a request
            # hears why instead
            logger.warning("Dropped a reply too large to send")
            if "id" not in msg:
                return
            msg = {
                "type": "error",
                "id": msg.get("id"),
                "error": "The reply was too large to send",
            }
            signed = sign_reply(self.key, auth, msg)
            text = json.dumps({"ch": ch, "msg": signed}, ensure_ascii=False)
            size = len(text.encode())
        auth.reply_seq = signed["seq"]
        auth.backlog += size
        if auth.backlog > MAX_CHANNEL_BACKLOG_BYTES:
            logger.warning("Closed a channel too far behind on its replies")
            self.close_channel(ch)
            return
        self._queue(ch, text)

    async def send(self, ch: str, msg: dict) -> None:
        self.send_soon(ch, msg)

    def send_to_relay(self, msg: dict) -> None:
        """Queue a message for the relay itself, e.g., to close a channel."""
        if self.ws is not None:
            self._queue(None, json.dumps(msg))

    def _queue(self, ch: str | None, text: str) -> None:
        self.outbox.append((ch, text))
        if self.writer is None:
            self.writer = asyncio.get_running_loop().create_task(
                self._write_out()
            )

    async def _write_out(self) -> None:
        """Send what's queued for the relay, one message at a time, so they
        arrive in the order they were signed.
        """
        try:
            while self.outbox:
                ch, text = self.outbox.popleft()
                auth = self.channels.get(ch) if ch is not None else None
                ws = self.ws
                try:
                    if ws is not None:
                        await ws.send(text)
                except Exception as e:
                    logger.debug(f"Dropped a message to the relay: {e}")
                finally:
                    if auth is not None:
                        auth.backlog -= len(text.encode())
        finally:
            self.writer = None

    def get_workspace(self, path: str, personal: bool = True) -> str:
        """Resolve a workspace the hub may use, refusing anything else.

        Managed workspaces are checked out with ``--force`` to run stages,
        so only their status may be read, not changed.
        """
        path = os.path.realpath(path)
        for ws in self.workspaces:
            if ws["path"] == path:
                if personal and ws["kind"] != "personal":
                    raise ValueError("Managed workspaces can't be changed")
                return path
        raise ValueError("Not a workspace this hub link allows")

    def open_session(
        self,
        workspace: str,
        cols: int,
        rows: int,
        command: str | None = None,
        attach: int | None = None,
        auth: ChannelAuth | None = None,
    ) -> Session:
        """Start a shell in a workspace, running a command first if given,
        or attaching to the tmux pane of an agent running there.

        Calkit and Git there get credentials from this link, which gets
        them from the hub with the grant of the channel that opened it,
        ``auth``, since a link started at boot can't reach the user's
        keychain.
        """
        if platform.system() == "Windows":
            raise ValueError("Sessions aren't supported on Windows yet")
        import pty

        workspace = self.get_workspace(workspace)
        if attach is not None:
            tmux = _get_agent(workspace, attach).get("tmux")
            if tmux is None:
                raise ValueError("Only agents running in tmux can be attached")
            # Unset, in case the link itself runs in tmux, which won't
            # attach inside itself
            command = shlex.join(
                [
                    "env",
                    "-u",
                    "TMUX",
                    "tmux",
                    "-S",
                    tmux["socket"],
                    "attach-session",
                    "-t",
                    tmux["pane"],
                ]
            )
        claim_workspace(workspace)
        self.claimed.add(workspace)
        # Everything the child needs is prepared here, since it's forked
        # from a process with threads: between fork and exec it may only
        # make system calls, not run code that could wait on a lock held
        # by a thread that no longer exists in it
        shell = shutil.which(get_shell()) or "/bin/sh"
        env = dict(child_env(), TERM="xterm-256color")
        import functools
        import secrets
        import tempfile

        from calkit.hub import core as hub

        # Where it asks for credentials, which the user's runtime folder
        # keeps from temporary file cleanup, where there is one
        cred_dir = cred_sock = None
        cred_secret = secrets.token_urlsafe(32)
        if auth is not None:
            runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
            try:
                cred_dir = tempfile.mkdtemp(
                    prefix="calkit-link-",
                    dir=runtime_dir
                    if runtime_dir and os.path.isdir(runtime_dir)
                    else None,
                )
                cred_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                cred_sock.bind(os.path.join(cred_dir, "creds.sock"))
                cred_sock.listen(16)
            except OSError as e:
                logger.warning(f"The session won't have credentials: {e}")
                if cred_sock is not None:
                    cred_sock.close()
                if cred_dir is not None:
                    shutil.rmtree(cred_dir, ignore_errors=True)
                cred_dir = cred_sock = None
        if cred_dir is not None:
            env[hub.LINK_SOCKET_ENV] = os.path.join(cred_dir, "creds.sock")
            env[hub.LINK_SECRET_ENV] = cred_secret
            env[hub.LINK_API_URL_ENV] = self.cfg["api_url"]
            # Git asks this link for GitHub's, after any helper of the
            # user's, which may work, e.g., one with a token in a file
            try:
                n = int(env.get("GIT_CONFIG_COUNT") or 0)
            except ValueError:
                n = 0
            env[f"GIT_CONFIG_KEY_{n}"] = "credential.https://github.com.helper"
            env[f"GIT_CONFIG_VALUE_{n}"] = "!" + shlex.join(
                [*CALKIT_COMMAND, "hub", "link", "git-credential"]
            )
            env["GIT_CONFIG_COUNT"] = str(n + 1)
        argv = [os.fsencode(shell), b"-l"]
        envb = {os.fsencode(k): os.fsencode(v) for k, v in env.items()}
        cwd = os.fsencode(workspace)
        try:
            max_fd = min(os.sysconf("SC_OPEN_MAX"), 65536)
        except (OSError, ValueError):
            max_fd = 4096
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            pid, fd = pty.fork()
        if pid == 0:
            # Child: a login shell in the workspace, as over SSH, without
            # anything of the link's, e.g., other sessions' terminals
            try:
                os.closerange(3, max_fd)
                os.chdir(cwd)
                os.execve(argv[0], argv, envb)
            finally:
                os._exit(127)
        # Nor does anything started later get this one's
        os.set_inheritable(fd, False)
        os.set_blocking(fd, False)
        session = Session(
            id=uuid.uuid4().hex[:12], workspace=workspace, pid=pid, fd=fd
        )
        self.sessions[session.id] = session
        if cred_dir is not None:
            session.auth = auth
            session.cred_dir = cred_dir
            session.cred_sock = cred_sock
            session.cred_secret = cred_secret
            session.cred_server = asyncio.get_running_loop().create_task(
                asyncio.start_unix_server(
                    functools.partial(self.serve_credentials, session),
                    sock=cred_sock,
                )
            )
        self.resize(session, cols, rows)
        asyncio.get_running_loop().add_reader(fd, self._on_output, session)
        # Typed ahead, so the shell runs it once it has started, and the
        # session carries on as a shell afterwards
        if command:
            self.write_input(session, command.encode() + b"\n")
        return session

    def write_input(self, session: Session, data: bytes) -> None:
        """Write to a session's terminal, keeping what it can't take yet and
        writing that as it drains, since a terminal only buffers a little,
        e.g., about 1 KiB on macOS.
        """
        if len(session.input_buffer) + len(data) > MAX_INPUT_BUFFER_BYTES:
            raise ValueError("Too much input waiting for the terminal")
        session.input_buffer += data
        self._drain_input(session)

    def _drain_input(self, session: Session) -> None:
        loop = asyncio.get_running_loop()
        while session.input_buffer:
            try:
                written = os.write(session.fd, session.input_buffer)
            except BlockingIOError:
                break
            except OSError:
                # The terminal is gone, which its reader handles
                session.input_buffer.clear()
                break
            del session.input_buffer[:written]
        if session.input_buffer:
            loop.add_writer(session.fd, self._drain_input, session)
        else:
            loop.remove_writer(session.fd)

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
        # A channel too far behind is closed while this goes
        for ch in list(session.channels):
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
        loop.remove_writer(session.fd)
        self._flush(session)
        try:
            os.close(session.fd)
        except OSError:
            pass
        self.sessions.pop(session.id, None)
        self.stop_credentials(session)
        self._release_if_unused(session.workspace)
        reported = False

        def report(code: int | None) -> None:
            nonlocal reported
            reported = True
            for ch in list(session.channels):
                self.send_soon(
                    ch,
                    {
                        "type": "sessions.exit",
                        "session": session.id,
                        "code": code,
                    },
                )
            logger.info(f"Session {session.id} exited with code {code}")

        def reap(tries: int = 0) -> None:
            # Never blocking the loop, since what closed the terminal can
            # keep running, e.g., a daemon the shell was replaced with,
            # which is reported as ended after a moment and reaped later
            try:
                pid, status = os.waitpid(session.pid, os.WNOHANG)
            except ChildProcessError:
                pid, status = session.pid, None
            if pid:
                if not reported:
                    report(
                        None
                        if status is None
                        else os.waitstatus_to_exitcode(status)
                    )
                return
            if tries == 20 and not reported:
                report(None)
            loop.call_later(0.05 if tries < 20 else 5, reap, tries + 1)

        reap()

    def attach(self, session: Session, ch: str) -> None:
        session.channels.add(ch)
        # Replay recent output so a reattaching browser sees the screen. The
        # first chunk says to clear it first, which also drops any live
        # output that reached the browser before the replay did
        text = bytes(session.scrollback).decode("utf-8", errors="replace")
        for i, chunk in enumerate(_chunks(text)):
            msg: dict[str, Any] = {"type": "sessions.output"}
            msg["session"] = session.id
            msg["data"] = chunk
            # So the browser doesn't answer queries in it again, e.g., for
            # the cursor position, which would reach the shell as text
            msg["replay"] = True
            if i == 0:
                msg["reset"] = True
            self.send_soon(ch, msg)

    def close_session(self, session: Session) -> None:
        import signal

        try:
            os.kill(session.pid, signal.SIGHUP)
        except ProcessLookupError:
            pass

    def close_all(self) -> None:
        for session in list(self.sessions.values()):
            self.close_session(session)
            self.stop_credentials(session)
        # Stopping, so nothing here is being used any more
        for wdir in list(self.claimed):
            release_workspace(wdir)
        self.claimed.clear()

    async def serve_credentials(
        self, session: Session, reader: Any, writer: Any
    ) -> None:
        """Answer a request from a session for a credential, one per
        connection, as a line of JSON each way.
        """
        import hmac

        try:
            line = await asyncio.wait_for(reader.readline(), 10)
            req = json.loads(line)
            if not isinstance(req, dict) or not hmac.compare_digest(
                str(req.get("secret", "")), session.cred_secret
            ):
                raise ValueError("Not this session's secret")
            reply = await self.get_session_credential(session, req)
        except Exception as e:
            reply = {"error": str(e) or type(e).__name__}
        try:
            writer.write((json.dumps(reply) + "\n").encode())
            await writer.drain()
        except OSError:
            pass
        finally:
            writer.close()

    async def get_session_credential(
        self, session: Session, req: dict
    ) -> dict:
        """A credential a session asked for, while it lasts: a token for
        this link's hub, and no other, or GitHub's for Git, from the hub,
        kept until shortly before it expires.

        ``fresh`` gets another, e.g., after the last was refused, and
        ``forget`` only drops the one kept.
        """
        import time

        from calkit.hub import core as hub

        if session.id not in self.sessions or session.auth is None:
            raise ValueError("The session has ended")
        kind = req.get("type")
        if kind == "hub.token":
            api_url = req.get("api_url")
            if not isinstance(api_url, str) or (
                api_url.rstrip("/") != self.cfg["api_url"].rstrip("/")
            ):
                raise ValueError(
                    f"This session only has tokens for {self.cfg['api_url']}"
                )
            route = "session-token"
        elif kind == "github.token":
            route = "github-token"
        else:
            raise ValueError("Unknown request")
        if req.get("fresh") or req.get("forget"):
            session.credentials.pop(route, None)
        if req.get("forget"):
            return {}
        async with session.cred_lock:
            cached = session.credentials.get(route)
            # Nothing past the second factor the session opened with
            if (
                cached is not None
                and time.time() < cached[1]
                and time.time() < session.auth.tfa_exp
            ):
                return {"token": cached[0]}
            token = await asyncio.to_thread(
                request_session_credential,
                self.cfg,
                route,
                session.auth.grant,
            )
            if route == "session-token":
                expires = (
                    hub._jwt_exp(token) or 0
                ) - SESSION_TOKEN_MARGIN_SECONDS
            else:
                expires = time.time() + GITHUB_TOKEN_CACHE_SECONDS
            # Unless it ended while this waited on the hub
            if session.id in self.sessions:
                session.credentials[route] = (token, expires)
        return {"token": token}

    def stop_credentials(self, session: Session) -> None:
        """Stop answering a session's requests for credentials, and forget
        the ones it got.
        """
        task = session.cred_server
        if task is not None:
            task.cancel()
            if (
                task.done()
                and not task.cancelled()
                and task.exception() is None
            ):
                task.result().close()
        if session.cred_sock is not None:
            session.cred_sock.close()
        if session.cred_dir is not None:
            shutil.rmtree(session.cred_dir, ignore_errors=True)
        session.credentials.clear()

    def _release_if_unused(self, wdir: str) -> None:
        """Release a workspace once no session or action is using it."""
        if wdir not in self.claimed or wdir in self.workspace_actions:
            return
        if any(s.workspace == wdir for s in self.sessions.values()):
            return
        release_workspace(wdir)
        self.claimed.discard(wdir)

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
                msg["workspace"],
                msg.get("cols", 80),
                msg.get("rows", 24),
                msg.get("command"),
                msg.get("attach"),
                auth=self.channels.get(ch),
            )
            self.attach(session, ch)
            return {"session": session.id}
        if kind == "sessions.attach":
            session = self._get_session(msg)
            # Credentials then last as long as this channel's second
            # factor, if that's longer
            auth = self.channels.get(ch)
            if (
                auth is not None
                and session.auth is not None
                and auth.tfa_exp >= session.auth.tfa_exp
            ):
                session.auth = auth
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
                self.write_input(self._get_session(msg), data.encode())
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
        # The relay names channels, and they're logged
        if not isinstance(ch, str) or not re.fullmatch(CHANNEL_ID_PATTERN, ch):
            logger.warning("Ignored a relay message with an invalid channel")
            return
        if kind == "channel.open":
            # Only the owner may use this machine, as the hub vouches with
            # a grant it signed, whatever the relay says, and only while it
            # can hear from the hub which sign-ins have ended
            auth = None
            if self.hub_reachable():
                if self.used_grants is None:
                    self.used_grants = load_used_grants()
                auth = check_grant(
                    self.cfg, frame.get("grant"), self.used_grants
                )
            # Kept, so it can't be used again after a restart either
            try:
                if auth is not None:
                    save_used_grants(self.used_grants or {})
            except OSError:
                auth = None
            if auth is None:
                logger.warning("Refused a channel without a valid grant")
                self.send_to_relay({"type": "channel.close", "ch": ch})
                return
            self.channels[ch] = auth
            # Browsers send nothing before this, which shows it's this
            # machine they reached
            self.send_soon(ch, {"type": "channel.ready"})
            return
        if kind == "channel.close":
            self.drop_channel(ch)
            return
        if kind != "channel.message" or ch not in self.channels:
            return
        msg = open_signed_message(self.channels[ch], frame.get("msg"))
        if msg is None:
            # One missing or out of order could change what the rest mean,
            # e.g., a dropped keystroke, so the channel can't go on
            logger.warning(
                "Closed a channel over a message that wasn't signed or in "
                "order"
            )
            self.close_channel(ch)
            return
        msg_type = msg.get("type")
        req_id = msg.get("id")
        if not isinstance(msg_type, str):
            if req_id is not None:
                self.send_soon(
                    ch,
                    {"type": "error", "id": req_id, "error": "Invalid type"},
                )
            return
        if msg_type in WORKSPACE_ACTIONS or msg_type in MACHINE_ACTIONS:
            asyncio.get_running_loop().create_task(self.run_action(ch, msg))
            return
        try:
            result = self.handle(ch, msg)
        except Exception as e:
            if req_id is not None:
                self.send_soon(
                    ch, {"type": "error", "id": req_id, "error": str(e)}
                )
            else:
                logger.warning(f"Failed to handle a message: {e}")
            return
        if req_id is not None:
            self.send_soon(
                ch, {"type": "result", "id": req_id, "result": result}
            )

    def drop_channel(self, ch: str) -> None:
        """Forget a channel, leaving any sessions it was attached to
        running.
        """
        self.channels.pop(ch, None)
        for session in self.sessions.values():
            session.channels.discard(ch)

    def close_channel(self, ch: str) -> None:
        """Forget a channel and have the relay close its browser, which
        reconnects if it's still wanted.
        """
        self.drop_channel(ch)
        self.send_to_relay({"type": "channel.close", "ch": ch})

    def close_ended_channels(self, ended: list[str]) -> None:
        """Close the channels opened from sign-ins that have since ended,
        e.g., with a password change, leaving their sessions running.
        """
        for ch, auth in list(self.channels.items()):
            if auth.session_id in ended:
                self.close_channel(ch)
                logger.info(f"Closed channel {ch}, since its sign-in ended")
        # The hub gives sessions opened from them no more credentials
        for session in self.sessions.values():
            if session.auth is not None and session.auth.session_id in ended:
                session.credentials.clear()

    def hub_reachable(self) -> bool:
        """Whether the hub was heard from lately enough for this link to
        know which sign-ins have ended.
        """
        import time

        return (
            self.last_check_in is not None
            and time.monotonic() - self.last_check_in < CHECK_IN_GRACE_SECONDS
        )

    def expire_channels(self) -> None:
        """Close channels whose second factor has expired, and all of them
        while the hub can't be reached, leaving sessions running.
        """
        import time

        if self.channels and not self.hub_reachable():
            logger.warning(
                "Closed all channels, since the hub hasn't been reachable "
                "for a while"
            )
            for ch in list(self.channels):
                self.close_channel(ch)
        now = time.time()
        for ch, auth in list(self.channels.items()):
            if now > auth.tfa_exp:
                self.close_channel(ch)
                logger.info(
                    f"Closed channel {ch}, since its second factor expired"
                )

    async def watch_channels(self) -> None:
        while True:
            await asyncio.sleep(CHANNEL_CHECK_SECONDS)
            self.expire_channels()

    async def run_action(self, ch: str, msg: dict) -> None:
        """Run a request that waits on Git, DVC, or the network in a thread,
        replying when it's done.
        """
        kind = msg["type"]
        req_id = msg.get("id")
        try:
            if kind == "workspaces.clone":
                path = await asyncio.to_thread(
                    clone_project, msg["git_repo_url"], msg.get("path")
                )
                # One outside the folders workspaces are found in, or that
                # doesn't say it's on this hub, has to be added, as with
                # 'calkit hub link add-workspace'
                home = config.get_user_home()
                roots = [
                    os.path.realpath(os.path.join(home, r))
                    for r in WORKSPACE_ROOTS
                ]
                # From the file, which 'add-workspace' may have added to
                saved = load_config() or {}
                workspaces = saved.get("workspaces") or []
                self.cfg["workspaces"] = workspaces
                if (
                    os.path.dirname(path) not in roots
                    or not is_on_this_hub(path)
                ) and path not in workspaces:
                    workspaces.append(path)
                    save_config(self.cfg)
                # So the hub lists it right away, though the clone stands
                # either way
                try:
                    await self.check_in()
                except Exception as e:
                    logger.warning(f"Check-in after cloning failed: {e}")
                result: Any = {"path": path}
            elif kind == "machine.check":
                result = await asyncio.to_thread(
                    check_machine_setup, msg["git_repo_url"]
                )
            elif kind == "machine.ssh_key":
                result = await asyncio.to_thread(get_ssh_public_key)
            elif kind == "machine.configure":
                result = await asyncio.to_thread(
                    configure_machine,
                    git_name=msg.get("git_name"),
                    git_email=msg.get("git_email"),
                    token=msg.get("token", False),
                    cfg=self.cfg,
                )
            else:
                wdir = self.get_workspace(
                    msg.get("workspace", ""),
                    personal=kind not in READ_ONLY_ACTIONS,
                )
                kwargs = {
                    k: v
                    for k, v in msg.items()
                    if k not in ("type", "id", "workspace")
                }
                lock = self.workspace_locks.setdefault(wdir, asyncio.Lock())
                action = WORKSPACE_ACTIONS[kind]
                # Fetching alongside a pull, push, or status would race it
                # for Git's ref locks
                if (
                    kind == "workspace.git_status"
                    and self.workspace_actions.get(wdir)
                    not in (None, "workspace.run")
                ):
                    kwargs["fetch"] = False
                # A run holds the workspace for as long as it goes, so what
                # follows or stops it can't wait for it to finish
                if kind in LOCK_FREE_ACTIONS or (
                    kind in READ_ONLY_ACTIONS | {"workspace.stop"}
                    and self.workspace_actions.get(wdir) == "workspace.run"
                ):
                    result = await asyncio.to_thread(action, wdir, **kwargs)
                else:
                    async with lock:
                        # Reading status changes nothing, but anything else
                        # takes the workspace from other hubs' links
                        if kind not in READ_ONLY_ACTIONS:
                            claim_workspace(wdir)
                            self.claimed.add(wdir)
                        self.workspace_actions[wdir] = kind
                        try:
                            result = await asyncio.to_thread(
                                action, wdir, **kwargs
                            )
                        finally:
                            self.workspace_actions.pop(wdir, None)
                            self._release_if_unused(wdir)
        except Exception as e:
            logger.warning(f"{kind} failed: {e}")
            if req_id is not None:
                await self.send(
                    ch, {"type": "error", "id": req_id, "error": str(e)}
                )
            return
        # So the hub lists a new workspace right away
        if kind == "workspace.new":
            await self.check_in_quietly()
        if req_id is not None:
            await self.send(
                ch, {"type": "result", "id": req_id, "result": result}
            )

    async def check_in(self) -> dict:
        import time

        # Including ones added with 'add-workspace' since it started
        saved = await asyncio.to_thread(load_config)
        if saved is not None:
            self.cfg["workspaces"] = saved.get("workspaces") or []
        self.workspaces = await asyncio.to_thread(
            discover_workspaces, self.cfg
        )
        grant_key = self.cfg.get("grant_public_key")
        # Whether browsers can reach it now, so the hub doesn't show it
        # online while it's reconnecting
        resp = await asyncio.to_thread(
            check_in,
            self.cfg,
            self.workspaces,
            self.mode,
            self.ws is not None,
            self.restart_pending(),
            # As many as the hub takes, which is far more than one person
            # signs in from
            sorted({auth.session_id for auth in self.channels.values()})[
                :MAX_CHANNEL_SESSIONS
            ],
        )
        self.last_check_in = time.monotonic()
        self.check_in_interval = resp.get("check_in_interval", 60)
        # Grants checked with the old key can't be trusted with the new one
        if grant_key and self.cfg.get("grant_public_key") != grant_key:
            for ch in list(self.channels):
                self.close_channel(ch)
        self.close_ended_channels(
            [str(s) for s in resp.get("ended_sessions") or []]
        )
        self.expire_channels()
        # The relay closes the connection once its token expires otherwise,
        # so one that stops checking in, e.g., once revoked, is cut off
        if self.ws is not None and resp.get("relay_token"):
            self.send_to_relay(
                {"type": "auth.refresh", "token": resp["relay_token"]}
            )
        if resp.get("restart"):
            self.restart_requested = True
        return resp

    def restart_pending(self) -> bool:
        """Whether this link should restart or stop once idle, because
        it was asked to or Calkit was upgraded under it.
        """
        try:
            with open(_restart_request_path()) as f:
                request = f.read().strip()
            os.remove(_restart_request_path())
        except OSError:
            request = None
        if request == "stop":
            self.stop_requested = True
        elif request is not None:
            self.restart_requested = True
        installed = get_installed_version()
        upgraded = installed is not None and installed != calkit.__version__
        return self.restart_requested or self.stop_requested or upgraded

    async def wait_to_restart(self) -> None:
        """Return once a restart is pending and nothing is using this
        link, so no session or run is cut off.
        """
        while True:
            await asyncio.sleep(RESTART_CHECK_SECONDS)
            if not self.restart_pending():
                continue
            if self.sessions or self.workspace_actions:
                continue
            self.restarting = not self.stop_requested
            logger.info("Restarting" if self.restarting else "Stopping")
            return

    async def check_in_quietly(self) -> None:
        try:
            await self.check_in()
        except Exception as e:
            logger.warning(f"Check-in failed: {e}")

    async def keep_checking_in(self) -> None:
        while True:
            await asyncio.sleep(self.check_in_interval)
            trim_log()
            try:
                await self.check_in()
            except LinkRevoked:
                raise
            except Exception as e:
                logger.warning(f"Check-in failed: {e}")

    async def connect(self, resp: dict) -> None:
        from websockets.asyncio.client import connect

        url = f"{resp['relay_url']}/machine"
        check_secure_url(url)
        async with connect(url, max_size=MAX_FRAME_BYTES) as ws:
            # Sent in a message rather than the URL to stay out of logs
            await ws.send(
                json.dumps({"type": "auth", "token": resp["relay_token"]})
            )
            self.ws = ws
            logger.info(f"Connected to relay as {self.cfg['name']}")
            # The check-in before connecting said it wasn't, so the hub
            # would show it offline until the next one
            self.connected_check_in = asyncio.create_task(
                self.check_in_quietly()
            )
            watcher = asyncio.create_task(self.watch_channels())
            try:
                async for text in ws:
                    try:
                        frame = json.loads(text)
                    except ValueError:
                        continue
                    if not isinstance(frame, dict):
                        continue
                    # One bad message mustn't end the connection
                    try:
                        self.on_relay_message(frame)
                    except Exception as e:
                        logger.warning(
                            f"Failed to handle a relay message: {e}"
                        )
            finally:
                watcher.cancel()
                self.ws = None
                self.outbox.clear()
                self.channels.clear()
                for session in self.sessions.values():
                    session.channels.clear()

    async def wait_until_idle(self) -> None:
        """Return once nothing has used this link for its idle limit."""
        assert self.idle_exit_seconds is not None
        loop = asyncio.get_running_loop()
        last_used = loop.time()
        while True:
            await asyncio.sleep(min(30, self.idle_exit_seconds))
            # Anything running or watching keeps it up, e.g., a pipeline
            # run with no browser left, or loops once links run them (see
            # the ADR)
            if self.sessions or self.channels or self.workspace_actions:
                last_used = loop.time()
            elif loop.time() - last_used >= self.idle_exit_seconds:
                logger.info("Idle, so stopping until the hub asks again")
                return

    async def run(self) -> None:
        checker: asyncio.Task | None = None
        idle: asyncio.Task | None = None
        if self.idle_exit_seconds is not None:
            idle = asyncio.create_task(self.wait_until_idle())
        restart = asyncio.create_task(self.wait_to_restart())
        delay = 1.0
        try:
            while True:
                try:
                    resp = await self.check_in()
                    if checker is None:
                        checker = asyncio.create_task(self.keep_checking_in())
                    delay = 1.0
                    connection = asyncio.create_task(self.connect(resp))
                    waiting = [connection, checker, restart]
                    if idle is not None:
                        waiting.append(idle)
                    done, _ = await asyncio.wait(
                        waiting, return_when=asyncio.FIRST_COMPLETED
                    )
                    if idle in done or restart in done:
                        connection.cancel()
                        return
                    if checker in done:
                        connection.cancel()
                        checker.result()
                    connection.result()
                    logger.info("Relay connection closed")
                except LinkRevoked:
                    raise
                except Exception as e:
                    logger.warning(f"Connection failed: {e}")
                    delay = min(delay * 2, RECONNECT_MAX_DELAY_SECONDS)
                await asyncio.sleep(delay)
        finally:
            for task in [checker, idle, restart]:
                if task is not None:
                    task.cancel()
            self.close_all()
            # So the hub shows it offline now rather than minutes from now,
            # unless it's coming right back
            if not self.restarting:
                try:
                    await asyncio.to_thread(
                        check_in, self.cfg, self.workspaces, self.mode, False
                    )
                except Exception:
                    pass


def acquire_lock() -> Any:
    """Take the lock that keeps one link running per machine, user, and
    hub, returning its file, or None if another link holds it.

    Two would each replace the other's relay connection, and in cron mode
    cron starts one every few minutes regardless.
    """
    fpath = os.path.join(_private_dir(link_dir()), "link.lock")
    f = open(fpath, "w")
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    # Beside the lock, since on Windows a locked file can't be read
    with open(_pid_path(), "w") as pid_file:
        pid_file.write(str(os.getpid()))
    return f


def _pid_path(key: str | None = None) -> str:
    return os.path.join(link_dir(key), "link.pid")


def _restart_request_path(key: str | None = None) -> str:
    return os.path.join(link_dir(key), "restart")


def request_restarts(stop: bool = False) -> list[tuple[str, int]]:
    """Ask every link running on this machine to restart, or to stop,
    once nothing is using it, returning their hub keys and process IDs.
    """
    root = os.path.join(config.get_user_home(), ".calkit", "hubs")
    running = []
    for key in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        pid = get_running_pid(key)
        if pid is not None:
            request = "stop" if stop else "restart"
            _write_private(_restart_request_path(key), request)
            running.append((key, pid))
    return running


def get_installed_version() -> str | None:
    """The Calkit version installed now, which an upgrade can change
    under a running link.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("calkit-python")
    except PackageNotFoundError:
        return None


def restart_process(mode: str) -> None:
    """Replace this process with a link running the Calkit installed
    now.

    Exec keeps the process ID, so the service manager that started it still
    tracks it; Windows has no exec, so a new process is started instead.
    """
    cmd = _service_command(mode)
    if logger.isEnabledFor(logging.DEBUG):
        cmd.append("--verbose")
    if _logs_to_file:
        cmd.append("--log-file")
    for handler in logging.getLogger().handlers:
        handler.flush()
    if sys.platform == "win32":
        from calkit.upgrade import _popen_detached

        _popen_detached(cmd, log_fpath=get_log_path())
        return
    os.execv(cmd[0], cmd)


def get_running_pid(key: str | None = None) -> int | None:
    """The running link's process ID, if one is running."""
    import psutil

    try:
        with open(_pid_path(key)) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    try:
        cmdline = " ".join(psutil.Process(pid).cmdline())
    except (psutil.Error, SystemError):
        return None
    # The ID may have been reused by something else since
    return pid if "hub link start" in cmdline else None


def run(cfg: dict, mode: str = "foreground") -> bool:
    """Run the link until it's revoked, interrupted, or, in cron mode,
    idle or not asked to connect.

    Returns False if another link is already running.
    """
    import signal

    refuse_root()
    lock = acquire_lock()
    if lock is None:
        return False
    trim_log()
    if os.path.exists(get_log_path()):
        _private_log()
    if not any(isinstance(f, RepeatFilter) for f in logger.filters):
        logger.addFilter(RepeatFilter())

    # Service managers stop it with SIGTERM, which should shut down as
    # cleanly as Ctrl+C
    def interrupt(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    # A request left from before this one started is already answered
    try:
        os.remove(_restart_request_path())
    except OSError:
        pass
    link = None
    try:
        if mode == "cron":
            workspaces = discover_workspaces(cfg)
            resp = check_in(cfg, workspaces, mode, connected=False)
            if not resp["connect"]:
                return True
            link = HubLink(
                cfg, mode=mode, idle_exit_seconds=CRON_IDLE_EXIT_SECONDS
            )
        else:
            link = HubLink(cfg, mode=mode)
        asyncio.run(link.run())
    finally:
        lock.close()
    if link is not None and link.restarting:
        restart_process(mode)
    return True


# The service names below take a hub key, defaulting to the selected hub's


def _key(key: str | None) -> str:
    return hub_key() if key is None else key


def service_label(key: str | None = None) -> str:
    return f"io.calkit.hub-link.{_key(key)}"


def systemd_unit(key: str | None = None) -> str:
    return f"calkit-hub-link-{_key(key)}.service"


def cron_marker(key: str | None = None) -> str:
    return f"# calkit-hub-link {_key(key)}"


def get_log_path() -> str:
    return os.path.join(link_dir(), "link.log")


# Whether this process writes its own log, rather than a service manager
_logs_to_file = False


def log_to_file() -> None:
    """Send this process's output to its log, opened as the user, rather
    than have launchd open it as root, which a link in its place could
    point at a file only root may write.
    """
    global _logs_to_file
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | NOFOLLOW
    fd = os.open(_private_log(), flags, 0o600)
    sys.stdout.flush()
    sys.stderr.flush()
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    _logs_to_file = True


def trim_log(fpath: str | None = None) -> None:
    """Drop the log's oldest lines once it's over LOG_MAX_BYTES.

    Service managers write to it directly, so it's cut down in place rather
    than rotated, which would leave them writing to the old file. They open
    it to append, so their next write goes at the new end, except on
    Windows, where it's left alone.
    """
    if sys.platform == "win32":
        return
    fpath = fpath or get_log_path()
    try:
        if os.path.getsize(fpath) <= LOG_MAX_BYTES:
            return
        sys.stdout.flush()
        sys.stderr.flush()
        with open(fpath, "r+b") as f:
            f.seek(-LOG_KEEP_BYTES, os.SEEK_END)
            tail = f.read()
            # From the start of a line
            tail = tail[tail.find(b"\n") + 1 :]
            f.seek(0)
            f.write(tail)
            f.truncate()
    except OSError:
        pass


class RepeatFilter(logging.Filter):
    """Log a warning that keeps recurring, e.g., while the hub is down, only
    once per REPEAT_LOG_SECONDS, rather than every check-in.
    """

    def __init__(self) -> None:
        super().__init__()
        self.last_logged: dict[str, float] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        import time

        if record.levelno < logging.WARNING:
            return True
        message = record.getMessage()
        now = time.monotonic()
        last = self.last_logged.get(message)
        if last is not None and now - last < REPEAT_LOG_SECONDS:
            return False
        self.last_logged[message] = now
        return True


def _service_command(mode: str = "service") -> list[str]:
    # The interpreter Calkit runs in, so the service doesn't depend on PATH
    return [
        *CALKIT_COMMAND,
        "hub",
        "link",
        "start",
        "--hub",
        get_hub_url(),
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
    """Have cron start the link every few minutes and at boot, so it
    checks in and connects only when the hub asks.
    """
    if shutil.which("crontab") is None:
        raise NotImplementedError(
            "This machine has no crontab; install with --no-service and run "
            "'calkit hub link start' yourself, e.g., inside tmux"
        )
    # From / rather than the home folder, and with cron's own meaning of %
    # escaped, i.e., a newline
    command = (
        f"cd / && {shlex.join(_service_command('cron'))} "
        f">> {shlex.quote(_private_log())} 2>&1"
    ).replace("%", "\\%")
    lines = [
        line for line in _read_crontab() if not line.endswith(cron_marker())
    ]
    for schedule in ["*/5 * * * *", "@reboot"]:
        lines.append(f"{schedule} {command} {cron_marker()}")
    _write_crontab(lines)


def _cron_installed(key: str | None = None) -> bool:
    if shutil.which("crontab") is None:
        return False
    return any(line.endswith(cron_marker(key)) for line in _read_crontab())


def _launchd_plist_path(at_boot: bool, key: str | None = None) -> str:
    if at_boot:
        return f"/Library/LaunchDaemons/{service_label(key)}.plist"
    return os.path.join(
        config.get_user_home(),
        "Library",
        "LaunchAgents",
        f"{service_label(key)}.plist",
    )


def _launchd_plist(at_boot: bool) -> bytes:
    import plistlib

    # At boot, launchd opens these as root, so the link writes its own
    # log instead
    log = "/dev/null" if at_boot else get_log_path()
    plist: dict[str, Any] = {
        "Label": service_label(),
        "ProgramArguments": _service_command()
        + (["--log-file"] if at_boot else []),
        "RunAtLoad": True,
        # Restarted if it fails, but not after it exits cleanly because it
        # was revoked
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "WorkingDirectory": "/",
        "EnvironmentVariables": {"HOME": config.get_user_home()},
        # Without one, launchd throttles its CPU and disk use, which made
        # looking over workspaces take minutes while people waited on it
        "ProcessType": "Interactive",
    }
    if at_boot:
        import pwd

        # This user, which installing makes sure isn't root, from the OS
        # rather than the environment
        plist["UserName"] = pwd.getpwuid(os.getuid()).pw_name
    return plistlib.dumps(plist)


def _windows_startup_path(key: str | None = None) -> str:
    return os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        "Startup",
        f"calkit-hub-link-{_key(key)}.vbs",
    )


def _windows_startup_script() -> str:
    # pythonw has no console window, and a VBScript can start it hidden
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(pythonw):
        exe = pythonw
    args = " ".join(f'""{a}""' for a in [exe, *_service_command()[1:]])
    log = get_log_path()
    # cmd strips the first and last quotes of a command with more than two,
    # so the whole command gets a pair of its own (quotes are doubled in
    # VBScript)
    return (
        'Set shell = CreateObject("WScript.Shell")\r\n'
        f'shell.Run "cmd /c ""{args} >> ""{log}"" 2>&1""", 0, False\r\n'
    )


def _systemd_unit_path(key: str | None = None) -> str:
    return os.path.join(
        config.get_user_home(), ".config", "systemd", "user", systemd_unit(key)
    )


def _systemd_unit() -> str:
    # With systemd's own meanings of %, $, and backslashes escaped
    command = " ".join(shlex.quote(arg) for arg in _service_command())
    for char, escaped in [("\\", "\\\\"), ("%", "%%"), ("$", "$$")]:
        command = command.replace(char, escaped)
    return (
        "[Unit]\n"
        "Description=Calkit hub link\n"
        "After=network-online.target\n"
        "\n"
        "[Service]\n"
        f"ExecStart={command}\n"
        "WorkingDirectory=/\n"
        "Restart=on-failure\n"
        "RestartSec=10\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _has_terminal() -> bool:
    """Whether there's a terminal to ask for a password in, even with stdin
    piped, e.g., from 'curl ... | sh'.
    """
    try:
        with open("/dev/tty"):
            return True
    except OSError:
        return False


def install_service(login: bool = False) -> list[str]:
    """Install the link as a service that runs as this user, returning
    notes for the user.

    It starts at boot unless ``login``, which needs sudo on macOS, and on
    Linux, letting the user's services linger. Without sudo, it starts at
    login instead. On Windows it always starts at login.
    """

    def can_sudo() -> bool:
        # Without asking, e.g., while sudo remembers the password, then by
        # asking, if there's a terminal to ask in, which there isn't when
        # 'calkit hub link install --ssh' runs this over SSH
        if not shutil.which("sudo"):
            return False
        cached = subprocess.run(["sudo", "-n", "true"], capture_output=True)
        if cached.returncode == 0:
            return True
        if not _has_terminal():
            return False
        print(
            "Starting the hub link at boot needs sudo. Press Ctrl+C to start "
            "it at login instead.",
            file=sys.stderr,
        )
        try:
            return subprocess.run(["sudo", "-v"]).returncode == 0
        except KeyboardInterrupt:
            return False

    notes = []
    system = platform.system()
    _private_log()
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
                "This machine has no user systemd to run the hub link as a "
                "service. Link again with --cron to have cron start it when "
                "the hub asks, or with --no-service and run "
                "'calkit hub link start' yourself, e.g., inside tmux"
            )
        fpath = _systemd_unit_path()
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w") as f:
            f.write(_systemd_unit())
        for args in [
            ["daemon-reload"],
            ["enable", "--now", systemd_unit()],
            ["restart", systemd_unit()],
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
        if linger != "yes" and not login:
            enable = ["loginctl", "enable-linger", user]
            # Often allowed for one's own user without sudo
            enabled = subprocess.run(enable, capture_output=True)
            if enabled.returncode != 0 and can_sudo():
                enabled = subprocess.run(
                    ["sudo", "-n", *enable], capture_output=True
                )
            if enabled.returncode != 0:
                notes.append(
                    "The hub link will only run while you're logged in. "
                    "To start it at boot, run: "
                    f"sudo loginctl enable-linger {user}"
                )
    elif system == "Darwin":
        at_boot = not login and can_sudo()
        fpath = _launchd_plist_path(at_boot)
        domain = "system" if at_boot else f"gui/{os.getuid()}"
        # Checked above, so it never stops to ask
        sudo = ["sudo", "-n"] if at_boot else []
        target = f"{domain}/{service_label()}"
        subprocess.run(
            [*sudo, "launchctl", "bootout", target], capture_output=True
        )
        # Bootout returns before the old link has stopped, and loading
        # the new one fails until it has
        import time

        for _ in range(60):
            loaded = subprocess.run(
                [*sudo, "launchctl", "print", target], capture_output=True
            )
            if loaded.returncode != 0:
                break
            time.sleep(0.5)
        if at_boot:
            import tempfile

            with tempfile.NamedTemporaryFile("wb", delete=False) as tmp:
                tmp.write(_launchd_plist(at_boot))
            subprocess.run(["sudo", "-n", "cp", tmp.name, fpath], check=True)
            os.remove(tmp.name)
        else:
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "wb") as plist_file:
                plist_file.write(_launchd_plist(at_boot))
        subprocess.run(
            [*sudo, "launchctl", "bootstrap", domain, fpath], check=True
        )
        if not at_boot and not login:
            notes.append(
                "Starting at boot needs sudo, so the hub link will start "
                "when you log in. To start it at boot, run 'calkit hub link "
                "install' again in a terminal."
            )
    elif system == "Windows":
        fpath = _windows_startup_path()
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w") as script:
            script.write(_windows_startup_script())
        subprocess.Popen(["wscript", fpath])
        notes.append(
            "The hub link will start when you log in. Shell sessions aren't "
            "supported on Windows yet."
        )
    else:
        raise NotImplementedError(
            f"Installing the link as a service isn't supported on "
            f"{system} yet; run 'calkit hub link start' instead"
        )
    return notes


def _stop_running_link() -> None:
    import psutil

    pid = get_running_pid()
    if pid is None:
        return
    proc = psutil.Process(pid)
    proc.terminate()
    # So one started right after doesn't find the lock still held
    try:
        proc.wait(timeout=30)
    except psutil.TimeoutExpired:
        proc.kill()


def uninstall_service(key: str | None = None) -> None:
    """Remove the selected hub's link service, or the one for the hub
    with this key.
    """
    if platform.system() == "Windows":
        if os.path.isfile(_windows_startup_path(key)):
            os.remove(_windows_startup_path(key))
        if key is None:
            _stop_running_link()
        return
    if _cron_installed(key):
        _write_crontab(
            [
                line
                for line in _read_crontab()
                if not line.endswith(cron_marker(key))
            ]
        )
    system = platform.system()
    if system == "Linux":
        fpath = _systemd_unit_path(key)
        if os.path.isfile(fpath):
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", systemd_unit(key)]
            )
            os.remove(fpath)
            subprocess.run(["systemctl", "--user", "daemon-reload"])
    elif system == "Darwin":
        agent = _launchd_plist_path(at_boot=False, key=key)
        if os.path.isfile(agent):
            subprocess.run(
                [
                    "launchctl",
                    "bootout",
                    f"gui/{os.getuid()}/{service_label(key)}",
                ],
                capture_output=True,
            )
            os.remove(agent)
        daemon = _launchd_plist_path(at_boot=True, key=key)
        if os.path.isfile(daemon):
            target = f"system/{service_label(key)}"
            subprocess.run(
                ["sudo", "launchctl", "bootout", target], capture_output=True
            )
            subprocess.run(["sudo", "rm", "-f", daemon])
            # E.g., sudo had no terminal to ask for a password in
            if os.path.isfile(daemon):
                raise RuntimeError(
                    "Removing the service that starts at boot needs sudo; "
                    f"run 'sudo launchctl bootout {target}' and "
                    f"'sudo rm {daemon}'"
                )


def get_service_status() -> str | None:
    """Describe the service, or return None if it isn't installed."""
    if platform.system() == "Windows":
        if not os.path.isfile(_windows_startup_path()):
            return None
        return "a Startup folder script, started at login"
    if _cron_installed():
        return "a cron job, checking in every 5 minutes"
    system = platform.system()
    if system == "Linux" and os.path.isfile(_systemd_unit_path()):
        state = subprocess.run(
            ["systemctl", "--user", "is-active", systemd_unit()],
            capture_output=True,
            text=True,
        ).stdout.strip()
        linger = subprocess.run(
            [
                "loginctl",
                "show-user",
                os.environ.get("USER") or "",
                "--property=Linger",
                "--value",
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
        when = "started at boot" if linger == "yes" else "started at login"
        return f"a systemd user service, {when} ({state})"
    if system == "Darwin":
        for at_boot in [False, True]:
            if not os.path.isfile(_launchd_plist_path(at_boot)):
                continue
            domain = "system" if at_boot else f"gui/{os.getuid()}"
            out = subprocess.run(
                ["launchctl", "print", f"{domain}/{service_label()}"],
                capture_output=True,
                text=True,
            ).stdout
            state = "not running"
            # The first state is the service's; later ones are its parts'
            for line in out.splitlines():
                if line.strip().startswith("state = "):
                    state = line.split("=", 1)[1].strip()
                    break
            kind = (
                "a launchd daemon, started at boot"
                if at_boot
                else ("a launchd agent, started at login")
            )
            return f"{kind} ({state})"
    return None


def restart_service() -> None:
    """Restart the link's service, starting it if it isn't running."""
    system = platform.system()
    if system == "Linux" and os.path.isfile(_systemd_unit_path()):
        subprocess.run(
            ["systemctl", "--user", "restart", systemd_unit()], check=True
        )
        return
    if system == "Darwin":
        for at_boot in [False, True]:
            fpath = _launchd_plist_path(at_boot)
            if not os.path.isfile(fpath):
                continue
            domain = "system" if at_boot else f"gui/{os.getuid()}"
            sudo = ["sudo"] if at_boot else []
            target = f"{domain}/{service_label()}"
            loaded = subprocess.run(
                [*sudo, "launchctl", "print", target], capture_output=True
            )
            # Booting it out and in again races, since bootout returns
            # before the link has stopped, so it's restarted in place
            if loaded.returncode == 0:
                cmd = [*sudo, "launchctl", "kickstart", "-k", target]
            else:
                cmd = [*sudo, "launchctl", "bootstrap", domain, fpath]
            subprocess.run(cmd, check=True)
            return
    set_service_running(False)
    set_service_running(True)


def set_service_running(running: bool) -> None:
    system = platform.system()
    if system == "Windows" and os.path.isfile(_windows_startup_path()):
        if running:
            subprocess.Popen(["wscript", _windows_startup_path()])
        else:
            _stop_running_link()
        return
    if system == "Linux" and os.path.isfile(_systemd_unit_path()):
        action = "start" if running else "stop"
        subprocess.run(
            ["systemctl", "--user", action, systemd_unit()], check=True
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
                        f"{domain}/{service_label()}",
                    ],
                    check=True,
                )
            return
    # Cron starts it, so starting it now just checks in, connecting if the
    # hub asked, and stopping ends the one running, which cron starts again
    # when the hub asks
    if _cron_installed():
        if running:
            with open(_private_log(), "a") as log:
                subprocess.Popen(
                    _service_command("cron"),
                    cwd="/",
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        else:
            _stop_running_link()
        return
    raise RuntimeError("The link isn't installed as a service")
