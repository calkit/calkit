"""CLI for checking things."""

from __future__ import annotations

from typing import Literal, Annotated

import typer

import calkit
from calkit.check import check_reproducibility

check_app = typer.Typer(no_args_is_help=True)


@check_app.command(name="repro")
def check_repro(
    wdir: Annotated[
        str, typer.Option("--wdir", help="Project working directory.")
    ] = "."
):
    """Check the reproducibility of a project."""
    res = check_reproducibility(wdir=wdir, log_func=typer.echo)
    typer.echo(res.to_pretty().encode("utf-8", errors="replace"))
