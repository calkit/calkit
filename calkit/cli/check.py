"""CLI for checking things."""

from __future__ import annotations

import subprocess
from typing import Annotated

import typer

from calkit.check import check_reproducibility
from calkit.cli import raise_error

check_app = typer.Typer(no_args_is_help=True)


@check_app.command(name="repro")
def check_repro(
    wdir: Annotated[
        str, typer.Option("--wdir", help="Project working directory.")
    ] = ".",
):
    """Check the reproducibility of a project."""
    res = check_reproducibility(wdir=wdir, log_func=typer.echo)
    typer.echo(res.to_pretty().encode("utf-8", errors="replace"))


@check_app.command(name="call")
def check_call(
    cmd: Annotated[str, typer.Argument(help="Command to check.")],
    if_error: Annotated[
        str,
        typer.Option(
            "--if-error", help="Command to run if there is an error."
        ),
    ],
):
    """Check that a command succeeds and run an alternate if not."""
    try:
        subprocess.check_call(cmd, shell=True)
        typer.echo("Command succeeded")
    except subprocess.CalledProcessError:
        typer.echo("Command failed")
        try:
            typer.echo("Attempting fallback call")
            subprocess.check_call(if_error, shell=True)
            typer.echo("Fallback call succeeded")
        except subprocess.CalledProcessError:
            raise_error("Fallback call failed")
