"""The command line interface."""

from . import config

import typer

app = typer.Typer()
config_app = typer.Typer()
app.add_typer(config_app, name="config")


@config_app.command(name="set")
def set_config_value(key: str, value: str):
    cfg = config.read().model_dump()
    cfg[key] = value
    cfg = config.Settings.model_validate(cfg)
    cfg.write()


def run() -> None:
    app()
