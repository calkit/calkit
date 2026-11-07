"""What environments of every kind share."""

from __future__ import annotations

import os
import subprocess


def relock(env_name: str, env: dict) -> None:
    """Rebuild an environment from its spec and write a fresh lock.

    Tools with an upgrade command of their own run it. Otherwise the locks
    are removed and the environment is rebuilt from scratch, since a check
    with a lock in place reproduces the lock rather than the spec. If any
    of it fails, the old locks are put back, so a failed relock leaves the
    environment pinned where it was.
    """
    import typer

    from calkit.cli import raise_error
    from calkit.cli.check import check_environment
    from calkit.environments import (
        get_all_conda_lock_fpaths,
        get_all_docker_lock_fpaths,
        get_all_venv_lock_fpaths,
        get_env_lock_fpath,
    )

    kind = env.get("kind")
    spec_path = env.get("path") or ""
    env_dir = os.path.dirname(spec_path) or "."
    if kind in ("slurm", "pbs"):
        typer.echo(
            f"Environment '{env_name}' is locked to its configuration in "
            "calkit.yaml, so there is nothing to relock"
        )
        return
    upgrade_cmd = None
    if kind == "uv":
        upgrade_cmd = ["uv", "lock", "--upgrade"]
    elif kind == "pixi":
        # Named, since a directory can hold more than one manifest
        upgrade_cmd = ["pixi", "update"]
        if spec_path:
            upgrade_cmd += ["--manifest-path", os.path.abspath(spec_path)]
    elif kind == "nix":
        upgrade_cmd = [
            "nix",
            "--extra-experimental-features",
            "nix-command flakes",
            "flake",
            "update",
        ]
    # Every lock, including other platforms' and legacy ones, since a check
    # falls back to any of them
    lock_fpaths = []
    if kind == "docker":
        lock_fpaths = get_all_docker_lock_fpaths(env_name, as_posix=False)
    elif kind == "conda":
        lock_fpaths = get_all_conda_lock_fpaths(env_name, as_posix=False)
    elif kind in ("venv", "uv-venv"):
        lock_fpaths = get_all_venv_lock_fpaths(env_name, as_posix=False)
    elif kind == "renv":
        renv_dir = env_dir if spec_path.endswith("DESCRIPTION") else spec_path
        lock_fpaths = [os.path.join(renv_dir or ".", "renv.lock")]
    elif kind == "julia":
        # Julia falls back to this when there's no manifest for its version
        lock_fpaths = [os.path.join(env_dir, "Manifest.toml")]
    for legacy in (False, True):
        try:
            fpath = get_env_lock_fpath(
                env=env, env_name=env_name, as_posix=False, legacy=legacy
            )
        except ValueError as e:
            raise_error(f"Environment '{env_name}': {e}")
        if fpath is not None:
            lock_fpaths.append(fpath)
    lock_fpaths = list(dict.fromkeys(lock_fpaths))
    old_locks: dict[str, bytes | None] = {}
    for fpath in lock_fpaths:
        if os.path.isfile(fpath):
            with open(fpath, "rb") as f:
                old_locks[fpath] = f.read()
        else:
            old_locks[fpath] = None
    try:
        if upgrade_cmd is not None:
            typer.echo(f"Running: {' '.join(upgrade_cmd)}")
            if subprocess.run(upgrade_cmd, cwd=env_dir).returncode != 0:
                raise_error(f"Failed to relock environment '{env_name}'")
            typer.echo(f"Checking environment '{env_name}'")
            check_environment(env_name=env_name, verbose=True)
            return
        for fpath, content in old_locks.items():
            if content is not None:
                typer.echo(f"Removing lock file: {fpath}")
                os.remove(fpath)
        typer.echo(f"Relocking environment '{env_name}'")
        check_environment(env_name=env_name, verbose=True, force=True)
    except BaseException:
        # Including an exit from raise_error or Ctrl-C partway through
        for fpath, content in old_locks.items():
            if content is None:
                if os.path.isfile(fpath):
                    os.remove(fpath)
                continue
            os.makedirs(os.path.dirname(fpath) or ".", exist_ok=True)
            with open(fpath, "wb") as f:
                f.write(content)
        typer.echo(
            f"Relocking environment '{env_name}' failed, so its old locks "
            "were put back",
            err=True,
        )
        raise
