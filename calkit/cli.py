"""The command line interface."""

import typer

from . import config

app = typer.Typer()
config_app = typer.Typer()
app.add_typer(config_app, name="config")


@config_app.command(name="set")
def set_config_value(key: str, value: str):
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
    cfg = config.read()
    print(getattr(cfg, key))


def run() -> None:
    app()
