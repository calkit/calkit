"""CLI for working with Office."""

from __future__ import annotations

import platform

import docx2pdf
import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import raise_error

office_app = typer.Typer(no_args_is_help=True)


@office_app.command(
    name="excel-chart-to-image",
    help="Extract a chart from Excel and save to image.",
)
def excel_chart_to_image(
    input_fpath: Annotated[str, typer.Argument(help="Input Excel file path.")],
    output_fpath: Annotated[
        str, typer.Argument(help="Output image file path.")
    ],
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
    calkit.office.excel_chart_to_image(
        input_fpath=input_fpath,
        output_fpath=output_fpath,
        sheet=sheet,
        chart_index=chart_index,
    )


@office_app.command(name="word-to-pdf", help="Convert a Word document to PDF.")
def word_to_pdf(
    input_fpath: Annotated[
        str, typer.Argument(help="Input Word document file path.")
    ],
    output_fpath: Annotated[
        str,
        typer.Option(
            "-o",
            "--output",
            help=(
                "Output file path. If not specified, "
                "will be the same as input with a .pdf extension."
            ),
        ),
    ] = None,
):
    docx2pdf.convert(input_path=input_fpath, output_path=output_fpath)
