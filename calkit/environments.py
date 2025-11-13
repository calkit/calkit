"""Functionality related to environments."""

import os
import platform
from pathlib import PurePosixPath

DOCKER_ARCHS = [
    "amd64",
    "arm64",
    "arm-v7",
    "arm-v6",
    "ppc64le",
    "s390x",
    "386",
    "riscv64",
]
CONDA_VENV_ARCHS = [
    "osx-arm64",
    "osx-64",
    "linux-aarch64",
    "linux-ppc64le",
    "linux-64",
    "win-64",
]


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


def get_all_docker_lock_fpaths(
    env_name: str,
    wdir: str | None = None,
    as_posix: bool = True,
) -> list[str]:
    """Return docker environment lock file paths for every supported
    architecture.

    This intentionally excludes legacy (pre-arch) lock file locations;
    legacy handling is performed separately.
    """
    env_lock_dir = get_env_lock_dir(wdir=wdir)
    docker_dir = os.path.join(env_lock_dir, "docker")
    fpaths = [
        os.path.join(docker_dir, arch, env_name + ".json")
        for arch in DOCKER_ARCHS
    ]
    if as_posix:
        fpaths = [PurePosixPath(p).as_posix() for p in fpaths]
    return fpaths


def get_all_conda_lock_fpaths(
    env_name: str,
    wdir: str | None = None,
    as_posix: bool = True,
) -> list[str]:
    """Return conda environment lock file paths for every supported
    architecture.
    """
    env_lock_dir = get_env_lock_dir(wdir=wdir)
    conda_dir = os.path.join(env_lock_dir, "conda")
    fpaths = [
        os.path.join(conda_dir, arch, env_name + ".yml")
        for arch in CONDA_VENV_ARCHS
    ]
    if as_posix:
        fpaths = [PurePosixPath(p).as_posix() for p in fpaths]
    return fpaths


def get_all_venv_lock_fpaths(
    env_name: str,
    wdir: str | None = None,
    as_posix: bool = True,
) -> list[str]:
    """Return venv environment lock file paths for every supported
    architecture.
    """
    env_lock_dir = get_env_lock_dir(wdir=wdir)
    venv_dir = os.path.join(env_lock_dir, "venvs")
    fpaths = [
        os.path.join(venv_dir, arch, env_name + ".txt")
        for arch in CONDA_VENV_ARCHS
    ]
    if as_posix:
        fpaths = [PurePosixPath(p).as_posix() for p in fpaths]
    return fpaths


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
