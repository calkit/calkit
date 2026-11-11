"""CLI for working with Office."""

from __future__ import annotations

import platform

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
    import docx2pdf

    docx2pdf.convert(input_path=input_fpath, output_path=output_fpath)


@office_app.command(
    name="update-pptx-figures",
    help="Put figures in place of pictures in a PowerPoint file.",
)
def update_pptx_figures(
    source: Annotated[str, typer.Argument(help="PowerPoint file to update.")],
    figures: Annotated[
        list[str],
        typer.Option(
            "--figure",
            "-f",
            help=(
                "Slide, picture name in the selection pane, and figure, "
                "e.g., '3:Plot=figures/plot.png', or '3=figures/plot.png' "
                "for the slide's only picture."
            ),
        ),
    ],
    output: Annotated[
        str | None,
        typer.Option(
            "--output", "-o", help="File to write (default: update in place)."
        ),
    ] = None,
    dpi: Annotated[
        int, typer.Option("--dpi", help="Resolution of a PDF figure.")
    ] = 300,
) -> None:
    import re

    from calkit.pptx import Placement, update_figures

    placements = []
    for spec in figures:
        m = re.fullmatch(r"(\d+)(?::(.+?))?=(.+)", spec)
        if m is None:
            raise_error(
                f"'{spec}' should be SLIDE:PICTURE=FIGURE or SLIDE=FIGURE"
            )
        placements.append(Placement(slide=int(m[1]), picture=m[2], path=m[3]))
    try:
        update_figures(source, placements, output=output, dpi=dpi)
    except ValueError as e:
        raise_error(str(e))
