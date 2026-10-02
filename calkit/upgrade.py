"""Upgrading Calkit itself, on request or automatically."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any, Literal

PYPI_URL = "https://pypi.org/pypi/calkit-python/json"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
# How long an upgrade handed to the background counts as in progress, so
# its notice isn't shown while it's still running
UPGRADE_GRACE_SECONDS = 15 * 60

InstallMethod = Literal["uv-tool", "pipx", "pip", "frozen"]


def get_state_fpath() -> str:
    from calkit.config import get_env_suffix, get_user_home

    return os.path.join(
        get_user_home(), ".calkit", f"upgrade{get_env_suffix()}.json"
    )


def read_state() -> dict[str, Any]:
    try:
        with open(get_state_fpath()) as f:
            state = json.load(f)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def write_state(state: dict[str, Any]) -> None:
    fpath = get_state_fpath()
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, "w") as f:
        json.dump(state, f)


def update_state(**kwargs: Any) -> None:
    write_state(read_state() | kwargs)


def get_install_method() -> InstallMethod:
    """Detect how the running Calkit was installed."""
    if getattr(sys, "frozen", False):
        return "frozen"
    if os.path.isfile(os.path.join(sys.prefix, "uv-receipt.toml")):
        return "uv-tool"
    if os.path.isfile(os.path.join(sys.prefix, "pipx_metadata.json")):
        return "pipx"
    return "pip"


def get_direct_url() -> dict[str, Any]:
    """Read the PEP 610 record of where Calkit was installed from, which
    is empty for an install from a package index.
    """
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        txt = distribution("calkit-python").read_text("direct_url.json")
    except PackageNotFoundError:
        return {}
    if not txt:
        return {}
    try:
        info = json.loads(txt)
    except ValueError:
        return {}
    return info if isinstance(info, dict) else {}


def get_editable_path() -> str | None:
    """Return the source directory of an editable (dev) install."""
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    info = get_direct_url()
    if not info.get("dir_info", {}).get("editable"):
        return None
    return url2pathname(urlparse(info["url"]).path)


def is_dev_install() -> bool:
    """Whether Calkit was installed from source rather than a release."""
    info = get_direct_url()
    return bool(info.get("dir_info", {}).get("editable") or "vcs_info" in info)


def can_auto_upgrade() -> bool:
    """Only installs Calkit owns, i.e., isolated tool environments, are
    upgraded automatically; one in some other environment could have
    pins that an upgrade would break.
    """
    return get_install_method() in ["uv-tool", "pipx"] and not (
        is_dev_install()
    )


def get_upgrade_cmd() -> list[str]:
    import importlib.util
    import shutil

    method = get_install_method()
    if method == "frozen":
        raise ValueError(
            "This Calkit is a standalone executable, so it can't upgrade "
            "itself; download a new one or install with "
            "'uv tool install calkit-python'"
        )
    # 'uv tool upgrade' honors how the tool was installed, e.g., a version
    # constraint or the Python it runs on
    if method == "uv-tool" and shutil.which("uv"):
        return ["uv", "tool", "upgrade", "calkit-python"]
    if method == "pipx" and shutil.which("pipx"):
        return ["pipx", "upgrade", "calkit-python"]
    # Environments created by uv don't have pip
    if importlib.util.find_spec("pip") is None and shutil.which("uv"):
        return [
            "uv",
            "pip",
            "install",
            "--python",
            sys.executable,
            "--upgrade",
            "calkit-python",
        ]
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "calkit-python",
    ]


def get_dev_upgrade_cmds(branch: str | None = None) -> list[list[str]]:
    """Return the commands that update a dev install: pull its branch, then
    reinstall, which picks up new dependencies and refreshes the reported
    version.

    By default, that's whatever its checkout is on. Another branch is
    installed from the worktree that has it checked out, or checked out in
    the install's own worktree if that has no changes.
    """
    import shutil

    src = get_editable_path()
    if src is None:
        raise ValueError("Calkit is not an editable (dev) install")
    cmds: list[list[str]] = []
    target = src
    if os.path.exists(os.path.join(src, ".git")) or branch is not None:

        def git(*args: str) -> str:
            return subprocess.check_output(
                ["git", "-C", src, *args], text=True, stderr=subprocess.DEVNULL
            ).strip()

        try:
            toplevel = git("rev-parse", "--show-toplevel")
        except (OSError, subprocess.CalledProcessError):
            raise ValueError(f"{src} is not in a Git repo")
        if branch is None:
            branch = git("branch", "--show-current")
        worktrees: dict[str, str] = {}
        path = None
        for line in git("worktree", "list", "--porcelain").splitlines():
            if line.startswith("worktree "):
                path = line.removeprefix("worktree ")
            elif line.startswith("branch refs/heads/") and path:
                worktrees[line.removeprefix("branch refs/heads/")] = path
        if branch in worktrees:
            # The package may live below the repo root
            target = os.path.normpath(
                os.path.join(
                    worktrees[branch],
                    os.path.relpath(
                        os.path.realpath(src), os.path.realpath(toplevel)
                    ),
                )
            )
        elif branch:
            if git("status", "--porcelain"):
                raise ValueError(
                    f"Branch '{branch}' isn't checked out anywhere and "
                    f"{toplevel} has changes; commit or stash them, or add "
                    "a worktree for it with 'git worktree add'"
                )
            cmds.append(["git", "-C", toplevel, "checkout", branch])
        # A detached HEAD or a branch with no upstream has nothing to pull
        try:
            if branch:
                git("rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}")
                cmds.append(["git", "-C", target, "pull", "--ff-only"])
        except subprocess.CalledProcessError:
            pass
    if get_install_method() == "uv-tool" and shutil.which("uv"):
        python = f"{sys.version_info.major}.{sys.version_info.minor}"
        cmds.append(
            [
                "uv",
                "tool",
                "install",
                "--python",
                python,
                "--reinstall-package",
                "calkit-python",
                "--editable",
                target,
            ]
        )
    elif shutil.which("uv"):
        cmds.append(
            [
                "uv",
                "pip",
                "install",
                "--python",
                sys.executable,
                "--reinstall-package",
                "calkit-python",
                "--editable",
                target,
            ]
        )
    else:
        cmds.append(
            [sys.executable, "-m", "pip", "install", "--editable", target]
        )
    return cmds


def get_calkit_pids() -> list[int]:
    """Return this process and any ancestors running from Calkit's
    environment, e.g., the launcher a uv tool install puts on PATH, all of
    which hold files an upgrade must replace on Windows.
    """
    import psutil

    pids = [os.getpid()]
    prefix = os.path.normcase(os.path.realpath(sys.prefix))
    try:
        proc = psutil.Process().parent()
        while proc is not None:
            exe = os.path.normcase(os.path.realpath(proc.exe()))
            if not exe.startswith(prefix + os.sep):
                break
            pids.append(proc.pid)
            proc = proc.parent()
    except psutil.Error:
        pass
    return pids


def _popen_detached(cmd: list[str], log_fpath: str | None = None) -> None:
    kws: dict[str, Any] = {}
    if sys.platform == "win32":
        kws["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
    else:
        kws["start_new_session"] = True
    out = open(log_fpath, "a") if log_fpath else subprocess.DEVNULL
    try:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            close_fds=True,
            **kws,
        )
    finally:
        if log_fpath:
            out.close()  # type: ignore[union-attr]


def get_log_fpath() -> str:
    dpath = os.path.dirname(get_state_fpath())
    os.makedirs(dpath, exist_ok=True)
    return os.path.join(dpath, "upgrade.log")


def run_after_exit(cmds: list[list[str]], pids: list[int]) -> None:
    """Run commands in the background once the given processes exit.

    On Windows, files of a running program can't be replaced, so an
    upgrade has to wait for every Calkit process involved to exit, and
    the waiting can't be done by Calkit's own Python.
    """
    log_fpath = get_log_fpath()
    if sys.platform == "win32":

        def quote(s: str) -> str:
            return "'" + s.replace("'", "''") + "'"

        script = "".join(
            f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue; "
            for pid in pids
        )
        for cmd in cmds:
            script += (
                "& "
                + " ".join(quote(c) for c in cmd)
                + f" *>> {quote(log_fpath)}; "
                + "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; "
            )
        _popen_detached(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
        )
        return
    import psutil

    procs = []
    for pid in pids:
        try:
            procs.append(psutil.Process(pid))
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(procs)
    with open(log_fpath, "a") as log:
        for cmd in cmds:
            if subprocess.run(cmd, stdout=log, stderr=log).returncode != 0:
                break


def run_upgrade_cmds(cmds: list[list[str]]) -> None:
    """Run upgrade commands, deferring them on Windows until Calkit exits,
    since its own files can't be replaced while it runs.
    """
    import shlex

    import typer

    if sys.platform == "win32":
        run_after_exit(cmds, get_calkit_pids())
        typer.echo(
            "Calkit will finish upgrading in the background once this "
            f"command exits; see {get_log_fpath()} for details"
        )
        return
    for cmd in cmds:
        typer.echo(f"Running: {shlex.join(cmd)}")
        if subprocess.run(cmd).returncode != 0:
            raise RuntimeError("Upgrade failed")
    typer.echo("Success!")


def get_latest_version() -> str:
    import requests

    resp = requests.get(PYPI_URL, timeout=5)
    resp.raise_for_status()
    return str(resp.json()["info"]["version"])


def is_newer(version: str, than: str) -> bool:
    from packaging.version import InvalidVersion, Version

    try:
        return Version(version) > Version(than)
    except InvalidVersion:
        return False


def check(command: str | None) -> None:
    """Show any upgrade notice and, once a day, check for a new version in
    the background, upgrading automatically unless disabled.

    Called before every command, so this only reads a small state file
    unless a check is due.
    """
    import calkit

    if (
        command == "upgrade"
        or os.getenv("CALKIT_ENV") == "test"
        or os.getenv("CI")
    ):
        return
    state = read_state()
    now = time.time()
    current = calkit.__version__
    # Notices are for people, so are skipped when nobody's at a terminal,
    # and kept until somebody is
    if sys.stderr.isatty():
        upgraded_from = state.get("upgraded_from")
        upgrading = now - state.get("upgrading", 0) < UPGRADE_GRACE_SECONDS
        latest = state.get("latest")
        if upgraded_from and upgraded_from != current:
            _notify(f"Calkit was upgraded from v{upgraded_from} to v{current}")
            state.pop("upgraded_from")
            write_state(state)
        elif (
            latest
            and not upgrading
            and is_newer(latest, current)
            and now - state.get("notified", 0) > CHECK_INTERVAL_SECONDS
        ):
            _notify(
                f"Calkit v{latest} is available (you have v{current}); "
                "run 'calkit upgrade' to upgrade"
            )
            update_state(notified=now)
    if now - state.get("checked", 0) < CHECK_INTERVAL_SECONDS:
        return
    # Mark the check as done up front, so commands started while it runs,
    # e.g., by an editor, don't start their own
    try:
        update_state(checked=now)
        _popen_detached(
            [sys.executable, "-m", "calkit.upgrade"]
            + [str(pid) for pid in get_calkit_pids()],
            log_fpath=get_log_fpath(),
        )
    except Exception:
        pass


def _notify(txt: str) -> None:
    import typer

    typer.echo(typer.style(txt, fg="cyan"), err=True)


def check_in_background(pids: list[int]) -> None:
    """Check for a new version and upgrade to it once the Calkit processes
    in ``pids`` exit, if allowed.
    """
    import calkit
    from calkit import config

    if is_dev_install():
        return
    latest = get_latest_version()
    update_state(latest=latest)
    current = calkit.__version__
    if not is_newer(latest, current) or not can_auto_upgrade():
        return
    if not config.read().auto_upgrade:
        return
    # Recorded before upgrading, since on Windows the upgrade outlives this
    # process; the next command learns how it went by its own version
    update_state(upgraded_from=current, upgrading=time.time())
    run_after_exit([get_upgrade_cmd()], pids + get_calkit_pids())


if __name__ == "__main__":
    check_in_background([int(pid) for pid in sys.argv[1:]])
