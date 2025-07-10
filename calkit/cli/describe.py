"""CLI for describing thing."""

from __future__ import annotations

import json

import typer

import calkit

describe_app = typer.Typer(no_args_is_help=True)


@describe_app.command(name="system")
def describe_system():
    """Describe the system."""
    system_info = calkit.describe_system()
    typer.echo(json.dumps(system_info, indent=2))
