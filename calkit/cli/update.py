"""CLI for updating objects."""

from __future__ import annotations

import os

import requests
import typer
from typing_extensions import Annotated

update_app = typer.Typer(no_args_is_help=True)


@update_app.command(name="devcontainer")
def update_devcontainer(
    wdir: Annotated[
        str,
        typer.Option(
            "--wdir",
            help=(
                "Working directory. "
                "By default will run current working directory."
            ),
        ),
    ] = None,
):
    """Update a project's devcontainer to match the latest Calkit spec."""
    url = (
        "https://raw.githubusercontent.com/calkit/devcontainer/"
        "refs/heads/main/devcontainer.json"
    )
    typer.echo(f"Downloading {url}")
    resp = requests.get(url)
    out_dir = os.path.join(wdir or ".", ".devcontainer")
    os.makedirs(out_dir, exist_ok=True)
    out_fpath = os.path.join(out_dir, "devcontainer.json")
    typer.echo(f"Writing to {out_fpath}")
    with open(out_fpath, "w") as f:
        f.write(resp.text)
