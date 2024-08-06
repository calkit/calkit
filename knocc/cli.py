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
    except FileNotFoundError:
        cfg = config.Settings.model_validate({key: value})
    cfg.write()


def run() -> None:
    app()
