"""The ``calkit expand`` command, for kits embedded in artifacts."""

from __future__ import annotations

import os
from typing import Annotated

import typer

from calkit.cli import raise_error
from calkit.cli.main.core import app


@app.command(name="expand")
def expand(
    path: Annotated[str, typer.Argument(help="Path of a file with a kit.")],
    dest_dir: Annotated[
        str | None,
        typer.Argument(
            help="Directory for the project; defaults to the project's name."
        ),
    ] = None,
) -> None:
    """Expand the kit embedded in a file into a project.

    The project holds what makes the file, committed to a new Git repo with
    the original project's remote as 'upstream'.
    """
    import calkit.kits

    if not os.path.isfile(path):
        raise_error(f"{path} doesn't exist")
    if dest_dir is None:
        try:
            kit = calkit.kits.read(path)
        except ValueError as e:
            raise_error(f"Can't read kit: {e}")
        if kit is None:
            raise_error(f"{path} has no kit")
        dest_dir = (
            kit.manifest.source.name
            or os.path.splitext(os.path.basename(path))[0]
        )
    try:
        kit = calkit.kits.expand(path, dest_dir)
    except ValueError as e:
        raise_error(str(e))
    typer.echo(f"Expanded into {dest_dir}")
    if not kit.artifact_unchanged:
        typer.echo(
            typer.style(
                f"{kit.manifest.artifact.path} was modified since kit was "
                "made",
                fg="yellow",
            )
        )
    left_out = [f for f in kit.manifest.files if not f.included]
    if left_out:
        typer.echo(
            f"Left out of kit: {len(left_out)} file"
            + "s" * (len(left_out) != 1)
            + "; "
            "'calkit pull' fetches them if you have access, "
            "'calkit run' remakes outputs"
        )
