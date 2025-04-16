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
    # Find all publications with Overleaf projects linked
    ck_info = calkit.load_calkit_info()
    pubs = ck_info.get("publications", [])
    pubs = [p for p in pubs if p.get("overleaf", {}).get("project_id")]
    for pub in pubs:
        overleaf_project_id = pub["overleaf"]["project_id"]
        typer.echo(
            f"Syncing {pub['path']} with "
            f"Overleaf project ID {overleaf_project_id}"
        )
        # Ensure we've cloned the Overleaf project
        # Pull the latest version in the Overleaf project
        # Compute a diff in the Overleaf project between HEAD and the last sync
        # If there are changes, apply them to our local file(s)
        # Copy our versions into the Overleaf project and commit
        # TODO: Add option to run the pipeline after?
