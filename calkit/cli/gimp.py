"""CLI for working with GIMP."""

from __future__ import annotations

import typer
from typing_extensions import Annotated

from calkit.cli import raise_error

gimp_app = typer.Typer(no_args_is_help=True)


@gimp_app.command(
    name="export", help="Export a flattened figure from an XCF file."
)
def export(
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
