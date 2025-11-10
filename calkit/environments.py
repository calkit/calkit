"""Functionality related to environments."""

import os
import platform
from pathlib import PurePosixPath


def get_env_lock_dir(wdir: str | None = None) -> str:
    env_lock_dir = os.path.join(".calkit", "env-locks")
    if wdir is not None:
        env_lock_dir = os.path.join(wdir, env_lock_dir)
    return env_lock_dir


def _conda_venv_subdir() -> str:
    sys = platform.system().lower()
    mach = platform.machine().lower()
    if sys == "darwin":
        return "osx-arm64" if mach in ("arm64", "aarch64") else "osx-64"
    if sys == "linux":
        if mach in ("arm64", "aarch64"):
            return "linux-aarch64"
        elif mach in ("ppc64le",):
            return "linux-ppc64le"
        else:
            return "linux-64"
    if sys == "windows":
        return "win-64"
    # Fallback for unusual platforms
    return f"{sys}-{mach}"


def _docker_platform() -> str:
    """Get Docker platform string (arch part only)."""
    mach = platform.machine().lower()
    # Map common platform.machine() outputs to Docker arch names
    if mach in ("x86_64", "amd64"):
        return "amd64"
    elif mach in ("aarch64", "arm64"):
        return "arm64"
    elif mach in ("armv7l", "armv7"):
        return "arm-v7"
    elif mach in ("armv6l", "armv6"):
        return "arm-v6"
    elif mach == "ppc64le":
        return "ppc64le"
    elif mach == "s390x":
        return "s390x"
    elif mach in ("i386", "i686"):
        return "386"
    elif mach == "riscv64":
        return "riscv64"
    # Fallback
    return mach


def get_env_lock_fpath(
    env: dict,
    env_name: str,
    wdir: str | None = None,
    as_posix: bool = True,
    legacy: bool = False,
) -> str | None:
    """Create the environment lock file path."""
    env_lock_dir = get_env_lock_dir(wdir=wdir)
    env_kind = env.get("kind")
    lock_fpath = os.path.join(env_lock_dir, env_name)
    if env_kind == "docker":
        if legacy:
            lock_fpath += ".json"
        else:
            lock_fpath = os.path.join(
                env_lock_dir, "docker", _docker_platform(), env_name + ".json"
            )
    elif env_kind == "uv":
        env_dir = os.path.dirname(env.get("path", ""))
        if env_dir:
            lock_fpath = os.path.join(env_dir, "uv.lock")
        else:
            lock_fpath = "uv.lock"
    elif env_kind in ["venv", "uv-venv"]:
        if legacy:
            lock_fpath += ".txt"
        else:
            lock_fpath = os.path.join(
                env_lock_dir,
                "venvs",
                _conda_venv_subdir(),
                env_name + ".txt",
            )
    elif env_kind == "conda":
        if legacy:
            lock_fpath += ".yml"
        else:
            lock_fpath = os.path.join(
                env_lock_dir,
                "conda",
                _conda_venv_subdir(),
                env_name + ".yml",
            )
    elif env_kind == "matlab":
        lock_fpath += ".json"
    elif env_kind == "julia":
        env_path = env.get("path")
        if env_path is None:
            raise ValueError(
                "Julia environments require a path pointing to Project.toml"
            )
        env_fname = os.path.basename(env_path)
        if not env_fname == "Project.toml":
            raise ValueError(
                "Julia environments require a path pointing to Project.toml"
            )
        # Simply replace Project.toml with Manifest.toml
        env_dir = os.path.dirname(env_path)
        lock_fpath = os.path.join(env_dir, "Manifest.toml")
    else:
        return
    if as_posix:
        lock_fpath = PurePosixPath(lock_fpath).as_posix()
    return lock_fpath
