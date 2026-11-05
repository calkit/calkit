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


@dev_app.command(name="upgrade")
def upgrade(
    branch: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Branch to install from: the worktree that has it checked "
                "out, or else the install's own, if it has no changes. "
                "Defaults to the current branch."
            )
        ),
    ] = None,
) -> None:
    """Update a dev (editable) install: pull the branch and reinstall."""
    from calkit.cli.core import raise_error
    from calkit.upgrade import get_dev_upgrade_cmds, run_upgrade_cmds

    try:
        run_upgrade_cmds(get_dev_upgrade_cmds(branch))
    except Exception as e:
        raise_error(str(e))
