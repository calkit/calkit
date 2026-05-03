"""CLI for describing things."""

from __future__ import annotations

import json
from typing import Annotated

import typer

import calkit
from calkit.environments import get_env_lock_fpath

describe_app = typer.Typer(no_args_is_help=True)


@describe_app.command(name="system")
def describe_system():
    """Describe the system."""
    system_info = calkit.get_system_info()
    typer.echo(json.dumps(system_info, indent=2))


@describe_app.command(name="env")
def describe_env(
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="Environment name."),
    ],
):
    """Describe a single environment, including spec and lock file paths."""
    ck_info = calkit.load_calkit_info()
    envs: dict = ck_info.get("environments", {})
    if name not in envs:
        typer.echo(f"Environment '{name}' not found.", err=True)
        raise typer.Exit(1)
    env = envs[name]
    lock_path = get_env_lock_fpath(env=env, env_name=name)
    result = {
        "kind": env.get("kind"),
        "spec_path": env.get("path"),
        "lock_path": lock_path,
        "prefix": env.get("prefix"),
        "python": env.get("python"),
    }
    typer.echo(json.dumps(result, indent=2))


@describe_app.command(name="envs")
def describe_envs():
    """Describe all environments, including spec and lock file paths."""
    ck_info = calkit.load_calkit_info()
    envs: dict = ck_info.get("environments", {})
    result = {}
    for env_name, env in envs.items():
        lock_path = get_env_lock_fpath(env=env, env_name=env_name)
        result[env_name] = {
            "kind": env.get("kind"),
            "spec_path": env.get("path"),
            "lock_path": lock_path,
            "prefix": env.get("prefix"),
            "python": env.get("python"),
        }
    typer.echo(json.dumps(result, indent=2))
