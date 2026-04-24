"""CLI for Calkit developers, hidden from the typical help menu."""

from __future__ import annotations

import subprocess
import sys
from typing import Annotated

import typer

import calkit

dev_app = typer.Typer(no_args_is_help=True)


@dev_app.command(
    name="python",
    add_help_option=False,
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
def run_python(
    ctx: typer.Context,
    help: Annotated[bool, typer.Option("-h", "--help")] = False,
):
    """Start an Python shell in Calkit's environment."""
    subprocess.run([sys.executable] + sys.argv[3:])


@dev_app.command(
    name="ipython",
    add_help_option=False,
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
def run_ipython(
    ctx: typer.Context,
    help: Annotated[bool, typer.Option("-h", "--help")] = False,
):
    """Start an IPython shell in Calkit's environment."""
    from IPython import start_ipython

    start_ipython(argv=sys.argv[3:], user_ns={"calkit": calkit})
