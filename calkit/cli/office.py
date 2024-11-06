"""CLI for working with Office."""

from __future__ import annotations

import platform

import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import raise_error

office_app = typer.Typer(no_args_is_help=True)


@office_app.command(
    name="excel-chart-to-png",
    help="Extract a chart from Excel and save to PNG.",
)
def excel_chart_to_png(
    input_fpath: Annotated[str, typer.Argument(help="Input Excel file path.")],
    output_fpath: Annotated[str, typer.Argument(help="Output PNG file path.")],
    sheet: Annotated[
        int, typer.Option("--sheet", help="Sheet in workbook.")
    ] = 1,
    chart_index: Annotated[
        int, typer.Option("--chart-index", help="Chart index.")
    ] = 0,
):
    if platform.system() != "Windows":
        raise_error("This command is only available on Windows")
    typer.echo(
        f"Exporting chart at index {chart_index} from sheet {sheet} "
        f"in {input_fpath} to {output_fpath}"
    )
    calkit.office.excel_chart_to_png(
        input_fpath=input_fpath,
        output_fpath=output_fpath,
        sheet=sheet,
        chart_index=chart_index,
    )
