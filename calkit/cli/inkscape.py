"""CLI for working with Inkscape."""

from __future__ import annotations

import typer
from typing_extensions import Annotated

from calkit.cli import raise_error

inkscape_app = typer.Typer(no_args_is_help=True)


@inkscape_app.command(name="export", help="Export a figure from an SVG.")
def export(
    source: Annotated[str, typer.Argument(help="SVG to export from.")],
    output: Annotated[
        str,
        typer.Option(
            "--output", "-o", help="File to export to, e.g., a PNG or PDF."
        ),
    ],
    dpi: Annotated[
        int | None, typer.Option("--dpi", help="Resolution of a PNG.")
    ] = None,
) -> None:
    import calkit.inkscape

    try:
        calkit.inkscape.export(source, output, dpi=dpi)
    except ValueError as e:
        raise_error(str(e))
