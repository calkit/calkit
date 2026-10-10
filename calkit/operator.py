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
import re
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
# Messages from the relay are at most 256 KiB, plus its wrapping
MAX_FRAME_BYTES = 1024 * 1024
# Session input waiting for its terminal to drain, e.g., a long paste
MAX_INPUT_BUFFER_BYTES = 1024 * 1024
# In cron mode, the Operator exits after this long with no sessions or
# browsers, and cron starts it again when the hub asks
CRON_IDLE_EXIT_SECONDS = 900
# How often to check whether Calkit was upgraded or a restart was asked for
RESTART_CHECK_SECONDS = 30

# The hub the Operator commands in this process act on, by its web URL.
# Each hub's Operator has its own config, service, lock, and log, named by
# the hub's key, so Operators for several hubs can run side by side.
_hub_url: str | None = None
# Hub requests are pointed at the Operator's hub through CALKIT_HUB, but
# what runs in workspaces gets the value it started with
_inherited_hub = os.environ.get("CALKIT_HUB")


class OperatorRevoked(Exception):
    pass


def select_hub(hub_url: str | None = None) -> str:
    """Choose the hub the Operator commands act on, or the user's own hub
    if not given, returning its key.
    """
    global _hub_url
    if hub_url is None:
        from calkit import hub

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


def hub_url_from_api_url(api_url: str) -> str:
    """The web URL of the hub serving an API, which is on its ``api``
    subdomain.
    """
    from urllib.parse import urlparse

    parsed = urlparse(api_url)
    netloc = parsed.netloc
    if netloc.startswith("api."):
        netloc = netloc[len("api.") :]
    return f"{parsed.scheme}://{netloc}"


def operator_dir(key: str | None = None) -> str:
    return os.path.join(
        config.get_user_home(),
        ".calkit",
        "operators",
        hub_key() if key is None else key,
    )


def get_config_path() -> str:
    return os.path.join(operator_dir(), "config.yaml")


def _legacy_config_path() -> str:
    return os.path.join(config.get_user_home(), ".calkit", "operator.yaml")


def list_configured_hubs() -> list[str]:
    """The web URLs of the hubs this machine has Operators for."""
    import yaml

    # One from before Operators were kept per hub moves to its hub's place
    legacy = _legacy_config_path()
    if os.path.isfile(legacy):
        with open(legacy) as f:
            cfg = yaml.safe_load(f) or {}
        if cfg.get("api_url"):
            cfg.setdefault("hub_url", hub_url_from_api_url(cfg["api_url"]))
            fpath = os.path.join(
                config.get_user_home(),
                ".calkit",
                "operators",
                hub_key(cfg["hub_url"]),
                "config.yaml",
            )
            if not os.path.exists(fpath):
                _write_private(fpath, yaml.safe_dump(cfg, sort_keys=False))
        os.remove(legacy)
    root = os.path.join(config.get_user_home(), ".calkit", "operators")
    hubs = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        fpath = os.path.join(root, name, "config.yaml")
        if not os.path.isfile(fpath):
            continue
        with open(fpath) as f:
            cfg = yaml.safe_load(f) or {}
        if cfg.get("hub_url"):
            hubs.append(cfg["hub_url"])
        elif cfg.get("api_url"):
            hubs.append(hub_url_from_api_url(cfg["api_url"]))
    return hubs


def _write_private(fpath: str, text: str) -> None:
    """Write a file only the user can read, e.g., one holding a token."""
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    fd = os.open(fpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    # A file that already existed keeps its mode otherwise
    if hasattr(os, "fchmod"):
        os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


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
    from calkit import hub

    if not os.getenv("CALKIT_HUB") and os.getenv("CALKIT_ENV") != "test":
        os.environ["CALKIT_HUB"] = (
            config._get_default_hub() or hub.DEFAULT_HUB_URL
        )
    url = hub.get_base_url()
    check_secure_url(url)
    return url


def is_registered(cfg: Any) -> bool:
    """Whether a config is for one of the user's active Operators on their
    own hub, rather than a revoked one or one from another hub, asked with
    the user's login so it works for another machine's config too.
    """
    from calkit import hub

    if not isinstance(cfg, dict) or cfg.get("api_url") != use_own_hub():
        return False
    active = hub._request("get", "/operators")
    return any(o.get("id") == cfg.get("id") for o in active)


def register(name: str | None = None, hosts: list[str] | None = None) -> dict:
    """Register this machine as an Operator with the hub and save its
    config.
    """
    from calkit import hub

    use_own_hub()
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


def install_remote(
    host: str,
    cron: bool = False,
    no_service: bool = False,
    interactive: bool = True,
) -> dict:
    """Install an Operator on another machine over SSH, returning its
    config.

    It's registered from here, with this machine's hub login, since the
    other one may never have logged in; its config is then written there
    and Calkit there installs the service, finding itself already
    registered.
    """
    import yaml

    from calkit import hub
    from calkit import workspace as ws

    use_own_hub()
    # Where the other machine keeps this hub's Operator
    remote_dir = f"~/.calkit/operators/{hub_key()}"
    remote_config = f"{remote_dir}/config.yaml"
    # Otherwise ssh would take it as an option
    if host.startswith("-"):
        raise ValueError(f"Invalid host '{host}'")
    target = ws.Workspace(host=host, wdir="~")
    target = ws.ensure_reachable(target, interactive=interactive)
    ws.ensure_calkit_installed(target, interactive=interactive, required=True)
    # Reinstalling, e.g., to change mode, keeps the Operator it already has
    # rather than leaving that one behind on the hub
    existing = subprocess.run(
        target.login_argv(f"cat {remote_config} 2>/dev/null || true"),
        capture_output=True,
        text=True,
    ).stdout
    cfg = yaml.safe_load(existing) if existing.strip() else None
    registered = False
    if not is_registered(cfg):
        info = ws.remote_system_info(target)
        hostname = info.get("hostname") or host
        resp = hub._request(
            "post",
            "/operators",
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
        args = ["calkit", "operator", "install", "--hub", get_hub_url()]
        if cron:
            args.append("--cron")
        if no_service:
            args.append("--no-service")
        subprocess.run(target.login_argv(shlex.join(args)), check=True)
    except Exception:
        # A registration nothing can use would linger on the hub
        if registered:
            hub._request("delete", f"/operators/{cfg['id']}")
        raise
    return dict(cfg)


def _workspace_lock_path(wdir: str) -> str:
    return os.path.join(wdir, ".calkit", "local", "operator.lock")


def workspace_lock_holder(wdir: str) -> dict | None:
    """Who's using a workspace, if anyone: the hub whose Operator holds its
    lock, as long as that Operator is still running.

    The lock lives in the workspace, so Operators for different hubs on
    the same machine see each other's.
    """
    import psutil

    try:
        with open(_workspace_lock_path(wdir)) as f:
            holder = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(holder, dict):
        return None
    pid = holder.get("pid")
    if not isinstance(pid, int):
        return None
    if pid == os.getpid():
        return holder
    # One that's gone left a stale lock, as did one whose ID has since been
    # reused by something else
    try:
        if "operator" not in " ".join(psutil.Process(pid).cmdline()):
            return None
    except psutil.Error:
        return None
    return holder


def claim_workspace(wdir: str) -> None:
    """Take a workspace for this hub's Operator, refusing if another hub's
    is using it, since two hubs changing one checkout would step on each
    other.
    """
    holder = workspace_lock_holder(wdir)
    if holder is not None:
        if holder.get("pid") == os.getpid():
            return
        raise ValueError(
            "This workspace is in use by the Operator for "
            f"{holder.get('hub', 'another hub')}"
        )
    fpath = _workspace_lock_path(wdir)
    # Which keeps it out of Git
    calkit.ensure_local_dir(wdir)
    tmp = f"{fpath}.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(
            {
                "hub": get_hub_url(),
                "pid": os.getpid(),
                "since": calkit.utcnow().isoformat(),
            },
            f,
        )
    os.replace(tmp, fpath)
    # Another Operator may have claimed it at the same moment, in which
    # case only one of the writes stands
    holder = workspace_lock_holder(wdir)
    if holder is None or holder.get("pid") != os.getpid():
        raise ValueError("This workspace is in use by another Operator")


def release_workspace(wdir: str) -> None:
    """Let other hubs' Operators use a workspace this one was using."""
    holder = workspace_lock_holder(wdir)
    if holder is not None and holder.get("pid") == os.getpid():
        try:
            os.remove(_workspace_lock_path(wdir))
        except OSError:
            pass


def discover_workspaces(cfg: dict) -> list[dict]:
    """Find the workspaces this Operator gives the hub access to.

    These are Calkit projects directly under ``~/calkit``, ones registered
    in the config, and the managed ones Calkit creates for running stages.
    """

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

    home = config.get_user_home()
    candidates: list[tuple[str, str]] = []
    root = os.path.join(home, "calkit")
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
        # Another hub's Operator using it, which this one has to wait for
        holder = workspace_lock_holder(path)
        in_use_by = None
        if holder is not None and holder.get("hub") != get_hub_url():
            in_use_by = holder.get("hub")
        workspaces.append(
            dict(
                path=path,
                kind=kind,
                project=project,
                in_use_by=in_use_by,
            )
            | _git_status(path)
            | get_run_state(path)
        )
    return workspaces


def check_in(
    cfg: dict,
    workspaces: list[dict],
    mode: str,
    connected: bool = True,
    restart_pending: bool = False,
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
                restart_pending=restart_pending,
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
    # Operators registered before grants were signed pin the key now; one
    # that's already pinned is never replaced
    key = resp.get("grant_public_key")
    if key and not cfg.get("grant_public_key"):
        cfg["grant_public_key"] = key
        save_config(cfg)
    elif key and key != cfg.get("grant_public_key"):
        logger.warning(
            "The hub's grant key changed, so browsers can't connect; "
            "run 'calkit operator install' again if that's expected"
        )
    return resp


def check_grant(cfg: dict, grant: Any, used: dict[str, float]) -> bool:
    """Whether a channel's grant is one the hub signed for this Operator's
    owner, and hasn't been used or expired.

    This, rather than the relay's word, is what decides who opened a
    channel, so the relay alone can't run anything here.
    """
    import base64
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )

    key = cfg.get("grant_public_key")
    if not isinstance(grant, str) or not key:
        return False
    try:
        payload = jwt.decode(
            grant,
            Ed25519PublicKey.from_public_bytes(base64.b64decode(key)),
            algorithms=["EdDSA"],
            audience=str(cfg["id"]),
            options={"require": ["exp", "aud", "sub", "jti"]},
            # For clocks that disagree with the hub's
            leeway=60,
        )
    except (jwt.InvalidTokenError, ValueError):
        return False
    now = time.time()
    for jti, exp in list(used.items()):
        if exp + 60 < now:
            del used[jti]
    jti = payload["jti"]
    if payload["sub"] != str(cfg["user_id"]) or jti in used:
        return False
    used[jti] = float(payload["exp"])
    return True


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
    """The environment for what runs in workspaces, without the Operator's
    own hub, so commands use the project's, as in any terminal.
    """
    env = dict(os.environ)
    if _inherited_hub is None:
        env.pop("CALKIT_HUB", None)
    else:
        env["CALKIT_HUB"] = _inherited_hub
    return env


def _calkit(args: list[str], wdir: str) -> None:
    """Run Calkit in the Operator's interpreter, raising with its output if
    it fails.
    """
    result = subprocess.run(
        [sys.executable, "-m", "calkit", *args],
        cwd=wdir,
        env=child_env(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            (result.stderr or result.stdout).strip() or "Calkit failed"
        )


def get_workspace_status(wdir: str, fetch: bool = True) -> dict:
    """A workspace's status as ``calkit status --json`` reports it, the same
    as the VS Code extension shows, plus how far it is from its remote.

    This is too expensive to run at every check-in, so the hub asks for it
    when someone is looking at the workspace.
    """
    errors = []
    git_repo = calkit.git.get_repo(wdir)
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
    result = subprocess.run(
        # Checking environments can build them, running whatever a repo's
        # specs say, which viewing status shouldn't do; the record of their
        # last checks is reported instead
        [sys.executable, "-m", "calkit", "status", "--json", "--no-env-check"],
        cwd=wdir,
        env=child_env(),
        capture_output=True,
        text=True,
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
    return {
        "status": status,
        "commits_ahead": ahead,
        "commits_behind": behind,
        "errors": errors,
    }


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
            with open(record) as f:
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


def pull_workspace(wdir: str) -> None:
    """Pull with Git, fast-forward only, then with DVC."""
    calkit.git.get_repo(wdir).git.pull("--ff-only")
    _calkit(["dvc", "pull"], wdir)


def push_workspace(wdir: str) -> None:
    """Push with DVC, then with Git."""
    _calkit(["dvc", "push"], wdir)
    git_repo = calkit.git.get_repo(wdir)
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
    # Only what was asked for goes in the commit
    calkit.git.get_repo(wdir).git.reset()
    args = ["add", *paths, "--commit-message"]
    args.append(message or f"Update {', '.join(paths)}")
    if to is not None:
        args += ["--to", to]
    if push:
        args.append("--push")
    _calkit(args, wdir)


def ignore_path(
    wdir: str,
    path: str,
    commit: bool = True,
    message: str | None = None,
    push: bool = False,
) -> None:
    check_workspace_path(wdir, path)
    git_repo = calkit.git.get_repo(wdir)
    if git_repo.ignored(path):
        return
    fpath = os.path.join(wdir, ".gitignore")
    txt = ""
    if os.path.isfile(fpath):
        with open(fpath) as f:
            txt = f.read()
    if txt and not txt.endswith("\n"):
        txt += "\n"
    with open(fpath, "w") as f:
        f.write(txt + path + "\n")
    if commit:
        git_repo.git.add(".gitignore")
        git_repo.git.commit(["-m", message or f"Ignore {path}"])
        if push:
            git_repo.git.push("origin", git_repo.active_branch.name)


def discard_changes(wdir: str) -> dict:
    """Put a workspace back to its last commit with ``calkit stash``, so
    ``calkit stash pop`` brings back what was discarded, DVC-tracked data
    included. New files are left alone.
    """
    repo = calkit.git.get_repo(wdir)

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
    fpath = os.path.join(wdir, "dvc.yaml")
    pipeline: dict = {}
    if os.path.isfile(fpath):
        with open(fpath) as f:
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
    with open(fpath, "w") as f:
        calkit.ryaml.dump(pipeline, f)
    repo = calkit.git.get_repo(wdir)
    repo.git.add("dvc.yaml")
    if calkit_type is not None:
        assert outs is not None and calkit_object is not None
        objs.append(dict(path=outs[0], stage=name) | calkit_object)
        ck_info[calkit_type + "s"] = objs
        with open(os.path.join(wdir, "calkit.yaml"), "w") as f:
            calkit.ryaml.dump(ck_info, f)
        repo.git.add("calkit.yaml")
    repo.git.commit(["-m", f"Add pipeline stage {name}"])
    if push:
        repo.git.push(["origin", repo.active_branch.name])


def run_pipeline(wdir: str, stages: list[str] | None = None) -> dict:
    """Run the pipeline, or some of its stages, without a terminal,
    returning whether it succeeded and the end of its output.

    This is for Operators that can't run sessions, i.e., on Windows; others
    run the pipeline in a session so its output can be watched.
    """
    # Stage names become arguments, so they can't be options
    for stage in stages or []:
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:/-]*", str(stage)):
            raise ValueError(f"Invalid stage name '{stage}'")
    result = subprocess.run(
        [sys.executable, "-m", "calkit", "run", *(stages or [])],
        cwd=wdir,
        env=child_env(),
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    # Kept well under the relay's message limit
    return {"ok": result.returncode == 0, "output": output[-50_000:]}


def clone_project(git_repo_url: str) -> str:
    """Clone a project into ``~/calkit``, where it becomes a workspace,
    returning its path.

    The clone uses this machine's own Git credentials.
    """
    # Only the kinds of URL projects have, so nothing else Git can fetch
    # from, e.g., local paths or other transports, can be named
    if not re.match(r"(https://|git@)[A-Za-z0-9]", git_repo_url):
        raise ValueError(f"Can't clone {git_repo_url}")
    parent = os.path.join(config.get_user_home(), "calkit")
    os.makedirs(parent, exist_ok=True)
    name = git_repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name.startswith("."):
        raise ValueError(f"Can't clone {git_repo_url}")
    dest = os.path.join(parent, name)
    if os.path.exists(dest):
        raise ValueError(f"{dest} already exists")
    # Pulling data can be slow or need credentials, so it's left to an
    # explicit pull
    _calkit(["clone", git_repo_url, dest, "--no-dvc-pull"], parent)
    return dest


# Browser requests that act on a workspace, run off the event loop since
# they wait on Git, DVC, and the network
WORKSPACE_ACTIONS: dict[str, Any] = {
    "workspace.status": get_workspace_status,
    "workspace.pull": pull_workspace,
    "workspace.push": push_workspace,
    "workspace.save": save_workspace,
    "workspace.ignore": ignore_path,
    "workspace.discard": discard_changes,
    "workspace.add_stage": add_stage,
    "workspace.run": run_pipeline,
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

    @property
    def label(self) -> str:
        """What's running in the foreground, e.g., 'bash' or 'claude'."""
        import psutil

        try:
            return str(psutil.Process(os.tcgetpgrp(self.fd)).name())
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
        # IDs of grants channels were opened with, and when they expire
        self.used_grants: dict[str, float] = {}
        self.workspaces: list[dict] = []
        self.ws: Any = None
        self.check_in_interval = 60
        # One Git or DVC operation at a time per workspace, and which
        self.workspace_locks: dict[str, asyncio.Lock] = {}
        self.workspace_actions: dict[str, str] = {}
        # Workspaces this Operator holds the lock for, against other hubs'
        self.claimed: set[str] = set()
        self.connected_check_in: asyncio.Task | None = None
        # Asked for by the hub or 'calkit upgrade', and done once idle
        self.restart_requested = False
        self.stop_requested = False
        self.restarting = False

    async def send(self, ch: str, msg: dict) -> None:
        ws = self.ws
        if ws is None:
            return
        try:
            # Unescaped, since escaping makes each non-ASCII character, e.g.,
            # a TUI's box drawing, 6 to 12 bytes, which can push a chunk of
            # output past the relay's message limit
            await ws.send(
                json.dumps({"ch": ch, "msg": msg}, ensure_ascii=False)
            )
        except Exception as e:
            logger.debug(f"Dropped message to {ch}: {e}")

    def send_soon(self, ch: str, msg: dict) -> None:
        asyncio.get_running_loop().create_task(self.send(ch, msg))

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
        raise ValueError("Not a workspace this Operator allows")

    def open_session(
        self, workspace: str, cols: int, rows: int, command: str | None = None
    ) -> Session:
        if platform.system() == "Windows":
            raise ValueError("Sessions aren't supported on Windows yet")
        import pty

        workspace = self.get_workspace(workspace)
        claim_workspace(workspace)
        self.claimed.add(workspace)
        # Everything the child needs is prepared here, since it's forked
        # from a process with threads: between fork and exec it may only
        # make system calls, not run code that could wait on a lock held
        # by a thread that no longer exists in it
        shell = shutil.which(get_shell()) or "/bin/sh"
        env = dict(child_env(), TERM="xterm-256color")
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
        loop.remove_writer(session.fd)
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
        self._release_if_unused(session.workspace)
        for ch in session.channels:
            self.send_soon(
                ch,
                {"type": "sessions.exit", "session": session.id, "code": code},
            )
        logger.info(f"Session {session.id} exited with code {code}")

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
        # Stopping, so nothing here is being used any more
        for wdir in list(self.claimed):
            release_workspace(wdir)
        self.claimed.clear()

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
        if not isinstance(ch, str):
            return
        if kind == "channel.open":
            # Only the owner may use this Operator, as the hub vouches with
            # a grant it signed, whatever the relay says
            if check_grant(self.cfg, frame.get("grant"), self.used_grants):
                self.channels.add(ch)
            else:
                logger.warning(f"Refused channel {ch} without a valid grant")
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
        if msg.get("type") in WORKSPACE_ACTIONS or msg.get("type") == (
            "workspaces.clone"
        ):
            asyncio.get_running_loop().create_task(self.run_action(ch, msg))
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

    async def run_action(self, ch: str, msg: dict) -> None:
        """Run a request that waits on Git, DVC, or the network in a thread,
        replying when it's done.
        """
        kind = msg["type"]
        req_id = msg.get("id")
        try:
            if kind == "workspaces.clone":
                path = await asyncio.to_thread(
                    clone_project, msg["git_repo_url"]
                )
                # So the hub lists it right away, though the clone stands
                # either way
                try:
                    await self.check_in()
                except Exception as e:
                    logger.warning(f"Check-in after cloning failed: {e}")
                result: Any = {"path": path}
            else:
                wdir = self.get_workspace(
                    msg.get("workspace", ""),
                    personal=kind != "workspace.status",
                )
                kwargs = {
                    k: v
                    for k, v in msg.items()
                    if k not in ("type", "id", "workspace")
                }
                lock = self.workspace_locks.setdefault(wdir, asyncio.Lock())
                action = WORKSPACE_ACTIONS[kind]
                # A run holds DVC's lock for as long as it goes, so status
                # only reports its progress then, changing nothing, and
                # needn't wait for it to finish
                if (
                    kind == "workspace.status"
                    and self.workspace_actions.get(wdir) == "workspace.run"
                ):
                    result = await asyncio.to_thread(action, wdir, **kwargs)
                else:
                    async with lock:
                        # Reading status changes nothing, but anything else
                        # takes the workspace from other hubs' Operators
                        if kind != "workspace.status":
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
        if req_id is not None:
            await self.send(
                ch, {"type": "result", "id": req_id, "result": result}
            )

    async def check_in(self) -> dict:
        self.workspaces = await asyncio.to_thread(
            discover_workspaces, self.cfg
        )
        # Whether browsers can reach it now, so the hub doesn't show it
        # online while it's reconnecting
        resp = await asyncio.to_thread(
            check_in,
            self.cfg,
            self.workspaces,
            self.mode,
            self.ws is not None,
            self.restart_pending(),
        )
        self.check_in_interval = resp.get("check_in_interval", 60)
        if resp.get("restart"):
            self.restart_requested = True
        return resp

    def restart_pending(self) -> bool:
        """Whether this Operator should restart or stop once idle, because
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
        Operator, so no session or run is cut off.
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
            try:
                await self.check_in()
            except OperatorRevoked:
                raise
            except Exception as e:
                logger.warning(f"Check-in failed: {e}")

    async def connect(self, resp: dict) -> None:
        from websockets.asyncio.client import connect

        url = f"{resp['relay_url']}/operator"
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
            # Anything running or watching keeps it up, e.g., loops
            # once Operators run them (see the ADR)
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
                except OperatorRevoked:
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
    """Take the lock that keeps one Operator running per machine, user, and
    hub, returning its file, or None if another Operator holds it.

    Two would each replace the other's relay connection, and in cron mode
    cron starts one every few minutes regardless.
    """
    fpath = os.path.join(operator_dir(), "operator.lock")
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
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
    return os.path.join(operator_dir(key), "operator.pid")


def _restart_request_path(key: str | None = None) -> str:
    return os.path.join(operator_dir(key), "restart")


def request_restarts(stop: bool = False) -> list[tuple[str, int]]:
    """Ask every Operator running on this machine to restart, or to stop,
    once nothing is using it, returning their hub keys and process IDs.
    """
    root = os.path.join(config.get_user_home(), ".calkit", "operators")
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
    under a running Operator.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("calkit-python")
    except PackageNotFoundError:
        return None


def restart_process(mode: str) -> None:
    """Replace this process with an Operator running the Calkit installed
    now.

    Exec keeps the process ID, so the service manager that started it still
    tracks it; Windows has no exec, so a new process is started instead.
    """
    cmd = _service_command(mode)
    if logger.isEnabledFor(logging.DEBUG):
        cmd.append("--verbose")
    for handler in logging.getLogger().handlers:
        handler.flush()
    if sys.platform == "win32":
        from calkit.upgrade import _popen_detached

        _popen_detached(cmd, log_fpath=get_log_path())
        return
    os.execv(cmd[0], cmd)


def get_running_pid(key: str | None = None) -> int | None:
    """The running Operator's process ID, if one is running."""
    import psutil

    try:
        with open(_pid_path(key)) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    try:
        cmdline = " ".join(psutil.Process(pid).cmdline())
    except psutil.Error:
        return None
    # The ID may have been reused by something else since
    return pid if "operator" in cmdline else None


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
    # A request left from before this one started is already answered
    try:
        os.remove(_restart_request_path())
    except OSError:
        pass
    operator = None
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
    if operator is not None and operator.restarting:
        restart_process(mode)
    return True


# The service names below take a hub key, defaulting to the selected
# hub's; an empty one gives the names used before Operators were kept per
# hub, so an old install can be found and removed


def _key(key: str | None) -> str:
    return hub_key() if key is None else key


def service_label(key: str | None = None) -> str:
    k = _key(key)
    return "io.calkit.operator" + (f".{k}" if k else "")


def systemd_unit(key: str | None = None) -> str:
    k = _key(key)
    return "calkit-operator" + (f"-{k}" if k else "") + ".service"


def cron_marker(key: str | None = None) -> str:
    k = _key(key)
    return "# calkit-operator" + (f" {k}" if k else "")


def get_log_path() -> str:
    return os.path.join(operator_dir(), "operator.log")


def _service_command(mode: str = "service") -> list[str]:
    # The interpreter Calkit runs in, so the service doesn't depend on PATH
    return [
        sys.executable,
        "-m",
        "calkit",
        "operator",
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
    lines = [
        line for line in _read_crontab() if not line.endswith(cron_marker())
    ]
    for schedule in ["*/5 * * * *", "@reboot"]:
        lines.append(f"{schedule} {command} >> {log} 2>&1 {cron_marker()}")
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

    plist: dict[str, Any] = {
        "Label": service_label(),
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
        import pwd

        # From the OS rather than the environment, which says root under
        # sudo, and this must never run as root
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
        "calkit-operator" + (f"-{_key(key)}" if _key(key) else "") + ".vbs",
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
            [*sudo, "launchctl", "bootout", f"{domain}/{service_label()}"],
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
                "boot instead, reinstall with --boot, which needs sudo."
            )
    elif system == "Windows":
        fpath = _windows_startup_path()
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w") as script:
            script.write(_windows_startup_script())
        subprocess.Popen(["wscript", fpath])
        notes.append(
            "The Operator will start when you log in. Shell sessions aren't "
            "supported on Windows yet."
        )
    else:
        raise NotImplementedError(
            f"Installing the Operator as a service isn't supported on "
            f"{system} yet; run 'calkit operator start' instead"
        )
    return notes


def _stop_running_operator() -> None:
    import psutil

    pid = get_running_pid()
    if pid is not None:
        psutil.Process(pid).terminate()


def uninstall_service(key: str | None = None) -> None:
    """Remove the selected hub's Operator service, or the one for the hub
    with this key, where an empty key means one installed before Operators
    were kept per hub.
    """
    if platform.system() == "Windows":
        if os.path.isfile(_windows_startup_path(key)):
            os.remove(_windows_startup_path(key))
        if key is None:
            _stop_running_operator()
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
            subprocess.run(
                [
                    "sudo",
                    "launchctl",
                    "bootout",
                    f"system/{service_label(key)}",
                ],
                capture_output=True,
            )
            subprocess.run(["sudo", "rm", daemon])


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


def set_service_running(running: bool) -> None:
    system = platform.system()
    if system == "Windows" and os.path.isfile(_windows_startup_path()):
        if running:
            subprocess.Popen(["wscript", _windows_startup_path()])
        else:
            _stop_running_operator()
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
            with open(get_log_path(), "a") as log:
                subprocess.Popen(
                    _service_command("cron"),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        else:
            _stop_running_operator()
        return
    raise RuntimeError("The Operator isn't installed as a service")
