"""Functionality related to environments."""

import os
from pathlib import PurePosixPath


def get_env_lock_dir(wdir: str | None = None) -> str:
    env_lock_dir = os.path.join(".calkit", "env-locks")
    if wdir is not None:
        env_lock_dir = os.path.join(wdir, env_lock_dir)
    return env_lock_dir


def get_env_lock_fpath(
    env: dict, env_name: str, wdir: str | None = None, as_posix: bool = True
) -> str | None:
    """Create the environment lock file path."""
    env_lock_dir = get_env_lock_dir(wdir=wdir)
    env_kind = env.get("kind")
    lock_fpath = os.path.join(env_lock_dir, env_name)
    if env_kind == "docker":
        lock_fpath += ".json"
    elif env_kind == "uv":
        lock_fpath = "uv.lock"
    elif env_kind in ["venv", "uv-venv"]:
        lock_fpath += ".txt"
    elif env_kind == "conda":
        lock_fpath += ".yml"
    elif env_kind == "matlab":
        lock_fpath += ".json"
    else:
        return
    if as_posix:
        lock_fpath = PurePosixPath(lock_fpath).as_posix()
    return lock_fpath
