"""Config CLI."""

from __future__ import annotations

import subprocess

import git
import typer
from git.exc import InvalidGitRepositoryError
from typing_extensions import Annotated

import calkit
from calkit import config
from calkit.cli.core import raise_error
from calkit.dvc import configure_remote, get_remotes, set_remote_auth

config_app = typer.Typer(no_args_is_help=True)


@config_app.command(name="set")
def set_config_value(key: str, value: str):
    """Set a value in the config."""
    keys = config.Settings.model_fields.keys()
    if key not in keys:
        raise_error(
            f"Invalid config key: '{key}'; Valid keys are: {list(keys)}"
        )
    try:
        cfg = config.read()
        cfg = config.Settings.model_validate(cfg.model_dump() | {key: value})
    except Exception as e:
        raise_error(f"Failed to set {key} in config: {e}")
    cfg.write()


@config_app.command(name="get")
def get_config_value(key: str) -> None:
    """Get and print a value from the config."""
    cfg = config.read().model_dump()
    if key not in cfg:
        raise_error(
            f"Invalid config key: '{key}'; Valid keys are: {list(cfg.keys())}"
        )
    val = cfg[key]
    if val is not None:
        print(val)
    else:
        print()


@config_app.command(name="unset")
def unset_config_value(key: str):
    """Unset a value in the config, returning it to default."""
    model_fields = config.Settings.model_fields
    if key not in model_fields:
        raise_error(
            f"Invalid config key: '{key}'; "
            f"Valid keys: {list(model_fields.keys())}"
        )
    try:
        cfg = config.read()
        setattr(cfg, key, model_fields[key].default)
    except Exception as e:
        raise_error(f"Failed to unset {key} in config: {e}")
    cfg.write()


@config_app.command(name="setup-remote", help="Alias for 'remote'.")
@config_app.command(name="remote")
def setup_remote(
    no_commit: Annotated[
        bool,
        typer.Option(
            "--no-commit", help="Do not commit changes to DVC config."
        ),
    ] = False,
):
    """Setup the Calkit cloud as the default DVC remote and store a token in
    the local config.
    """
    try:
        configure_remote()
        set_remote_auth()
    except subprocess.CalledProcessError:
        raise_error("DVC remote config failed; have you run `dvc init`?")
    except InvalidGitRepositoryError:
        raise_error("Current directory is not a Git repository")
    except ValueError as e:
        raise_error(e)
    if not no_commit:
        repo = git.Repo()
        repo.git.add(".dvc/config")
        if ".dvc/config" in calkit.git.get_staged_files():
            typer.echo("Committing changes to DVC config")
            repo.git.commit([".dvc/config", "-m", "Set DVC remote"])


@config_app.command(name="setup-remote-auth", help="Alias for 'remote-auth'.")
@config_app.command(name="remote-auth")
def setup_remote_auth():
    """Store a Calkit cloud token in the local DVC config for all Calkit
    remotes.
    """
    remotes = get_remotes()
    for name, url in remotes.items():
        if name == "calkit" or name.startswith("calkit:"):
            typer.echo(f"Setting up authentication for DVC remote: {name}")
            set_remote_auth(remote_name=name)


@config_app.command(name="list")
def list_config_keys():
    """List keys in the config."""
    cfg = config.read()
    for key in cfg.model_dump():
        typer.echo(key)
