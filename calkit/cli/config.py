"""Config CLI."""

from __future__ import annotations

import subprocess

import typer
from git.exc import InvalidGitRepositoryError

from calkit import config
from calkit.cli.core import raise_error
from calkit.dvc import configure_remote, get_remotes, set_remote_auth

config_app = typer.Typer(no_args_is_help=True)


@config_app.command(name="set")
def set_config_value(key: str, value: str):
    """Set a value in the config."""
    try:
        cfg = config.read()
        cfg = config.Settings.model_validate(cfg.model_dump() | {key: value})
        # Kind of a hack for setting the password computed field
        # Types have been validated above, so this won't hurt to do again
        setattr(cfg, key, value)
    except FileNotFoundError:
        # TODO: This fails if we try to set password before any config has
        # been written
        # Username is fine
        cfg = config.Settings.model_validate({key: value})
    cfg.write()


@config_app.command(name="get")
def get_config_value(key: str) -> None:
    """Get and print a value from the config."""
    cfg = config.read()
    val = getattr(cfg, key)
    if val is not None:
        print(val)
    else:
        print()


@config_app.command(name="setup-remote", help="Alias for 'remote'.")
@config_app.command(name="remote")
def setup_remote():
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
