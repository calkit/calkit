"""CLI for working with Overleaf."""

from __future__ import annotations

import platform

import docx2pdf
import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import raise_error

overleaf_app = typer.Typer(no_args_is_help=True)

@overleaf_app.command(name="sync")
def sync():
    """Sync publications with Overleaf."""
    pass
