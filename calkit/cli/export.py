"""CLI for exporting figures from the files they're drawn in, with the app
that draws them, e.g., a PNG from an Inkscape SVG.
"""

from __future__ import annotations

import typer
from typing_extensions import Annotated

from calkit.cli import raise_error

export_app = typer.Typer(no_args_is_help=True)


@export_app.command(name="inkscape", help="Export a figure from an SVG.")
def export_inkscape(
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


@export_app.command(
    name="gimp", help="Export a flattened figure from an XCF file."
)
def export_gimp(
    source: Annotated[str, typer.Argument(help="XCF file to export from.")],
    output: Annotated[
        str,
        typer.Option(
            "--output", "-o", help="File to export to, e.g., a PNG or TIFF."
        ),
    ],
) -> None:
    import calkit.gimp

    try:
        calkit.gimp.export(source, output)
    except ValueError as e:
        raise_error(str(e))
