"""CLI for interacting with Calkit Cloud instances."""

from __future__ import annotations

from typing import Annotated

import typer

import calkit
from calkit.cli import raise_error

cloud_app = typer.Typer(no_args_is_help=True)


@cloud_app.command(name="get")
def get(endpoint: Annotated[str, typer.Argument(help="API endpoint")]):
    """Get a resource from the Cloud API."""
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    try:
        resp = calkit.cloud.get(endpoint)
        typer.echo(resp)
    except Exception as e:
        raise_error(e)
