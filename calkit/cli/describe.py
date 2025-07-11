"""CLI for describing things."""

from __future__ import annotations

import json

import typer

import calkit

describe_app = typer.Typer(no_args_is_help=True)


@describe_app.command(name="system")
def describe_system():
    """Describe the system."""
    system_info = calkit.get_system_info()
    typer.echo(json.dumps(system_info, indent=2))
