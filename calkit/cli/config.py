"""Config CLI."""

from __future__ import annotations

import typer

from calkit import config
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


@config_app.command(name="setup-remote")
def setup_remote():
    """Setup the Calkit cloud as the default DVC remote and store a token in
    the local config.
    """
    configure_remote()
    set_remote_auth()


@config_app.command(name="setup-remote-auth")
def setup_remote_auth():
    """Store a Calkit cloud token in the local DVC config for all Calkit
    remotes.
    """
    remotes = get_remotes()
    for name, url in remotes.items():
        if name == "calkit" or name.startswith("calkit:"):
            typer.echo(f"Setting up authentication for DVC remote: {name}")
            set_remote_auth(remote_name=name)
