"""CLI for exporting data and artifacts from various apps, e.g., a PNG
from an Inkscape SVG.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import typer
from typing_extensions import Annotated

from calkit.cli import raise_error

if TYPE_CHECKING:
    from calkit.export import Exporter

export_app = typer.Typer(no_args_is_help=True)


def _prepare(exporter: Exporter, source: str, output: str) -> str:
    """Get ready to export, returning the executable to run."""
    exporter.check(source, output)
    if not os.path.isfile(source):
        raise ValueError(f"'{source}' doesn't exist")
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    # What was there is from before, so it can't pass for a new export
    if os.path.exists(output):
        os.remove(output)
    exe = exporter.find_executable()
    if exe is None:
        raise ValueError(
            f"Exporting '{source}' needs {exporter.app} installed"
        )
    return exe


def inkscape(source: str, output: str, dpi: int | None = None) -> None:
    """Export a drawing to the format ``output``'s extension names,
    raising ``ValueError`` if it can't be.
    """
    import subprocess

    from calkit.export import INKSCAPE

    exe = _prepare(INKSCAPE, source, output)
    cmd = [exe, source, f"--export-filename={output}"]
    if dpi is not None:
        cmd.append(f"--export-dpi={dpi}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.isfile(output):
        detail = (result.stderr or result.stdout or "").strip()
        raise ValueError(
            f"Inkscape didn't export '{output}' from '{source}'"
            + (f": {detail.splitlines()[-1]}" if detail else "")
        )


def gimp(source: str, output: str) -> None:
    """Flatten a GIMP document into the format ``output``'s extension
    names, raising ``ValueError`` if it can't be.

    Runs GIMP 3's batch dialect, then GIMP 2's, which differ in their file
    procedures. Neither reports a failed script in its exit code, so the
    written file is what says it worked.
    """
    import subprocess

    from calkit.export import GIMP

    exe = _prepare(GIMP, source, output)
    src = os.path.abspath(source).replace("\\", "\\\\").replace('"', '\\"')
    dst = os.path.abspath(output).replace("\\", "\\\\").replace('"', '\\"')
    v3 = (
        f'(let* ((image (car (gimp-file-load RUN-NONINTERACTIVE "{src}"))))'
        "  (gimp-image-flatten image)"
        f'  (gimp-file-save RUN-NONINTERACTIVE image "{dst}" "{dst}")'
        "  (gimp-image-delete image)"
        "  (gimp-quit 0))"
    )
    v2 = (
        "(let* ((image (car (gimp-file-load RUN-NONINTERACTIVE "
        f'"{src}" "{src}")))'
        "       (drawable (car (gimp-image-flatten image))))"
        f'  (gimp-file-save RUN-NONINTERACTIVE image drawable "{dst}" '
        f'"{dst}")'
        "  (gimp-image-delete image)"
        "  (gimp-quit 0))"
    )
    detail = ""
    for cmd in [
        [exe, "-i", "--batch-interpreter=plug-in-script-fu-eval", "-b", v3],
        [exe, "-i", "-b", v2],
    ]:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if os.path.isfile(output):
            return
        detail = (result.stderr or result.stdout or "").strip()
    raise ValueError(
        f"GIMP didn't export '{output}' from '{source}'"
        + (f": {detail.splitlines()[-1]}" if detail else "")
    )


def powerpoint(
    source: str,
    output: str,
    slide: int = 1,
    dpi: int | None = None,
    trim: bool = True,
) -> None:
    """Export a slide with LibreOffice to the format ``output``'s
    extension names, cropped to what's drawn on it unless ``trim`` is
    false, raising ``ValueError`` if it can't be.
    """
    import json
    import re
    import subprocess
    import tempfile
    import zipfile
    from pathlib import Path

    import pypdfium2 as pdfium

    from calkit.export import POWERPOINT

    def settle(pdf_path: str) -> None:
        """Fix the dates and hashes that differ from run to run, keeping
        their lengths so the file's offsets still hold.
        """
        with open(pdf_path, "rb") as f:
            data = f.read()
        # The document info's dates are optional
        data = re.sub(
            rb"/(?:CreationDate|ModDate)\s*\([^)]*\)",
            lambda m: b" " * len(m[0]),
            data,
        )
        data = re.sub(
            rb"(?<=Date>)\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:[+-]\d\d:\d\d)?",
            lambda m: b"1970-01-01T00:00:00" + b"+00:00"[: len(m[0]) - 19],
            data,
        )
        data = re.sub(
            rb"/ID\s*\[[^\]]*\]",
            lambda m: re.sub(rb"[0-9A-Fa-f](?=[0-9A-Fa-f]*>)", b"0", m[0]),
            data,
        )
        data = re.sub(
            rb"(?<=/DocChecksum/)[0-9A-Fa-f]+",
            lambda m: b"0" * len(m[0]),
            data,
        )
        with open(pdf_path, "wb") as f:
            f.write(data)

    if slide < 1:
        raise ValueError("Slides are numbered from 1")
    exe = _prepare(POWERPOINT, source, output)
    # Hidden slides are exported and counted, so numbers match PowerPoint's
    options = {
        "PageRange": {"type": "string", "value": str(slide)},
        "ExportHiddenSlides": {"type": "boolean", "value": "true"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        # A profile of its own, since a LibreOffice already open would take
        # the job and exit without doing it
        result = subprocess.run(
            [
                exe,
                f"-env:UserInstallation={Path(tmp, 'profile').as_uri()}",
                "--headless",
                "--convert-to",
                "pdf:impress_pdf_Export:" + json.dumps(options),
                "--outdir",
                tmp,
                os.path.abspath(source),
            ],
            capture_output=True,
            text=True,
        )
        exported = os.path.join(tmp, Path(source).stem + ".pdf")
        if not os.path.isfile(exported):
            detail = (result.stderr or result.stdout or "").strip()
            try:
                with zipfile.ZipFile(source) as z:
                    count = sum(
                        bool(re.fullmatch(r"ppt/slides/slide\d+\.xml", n))
                        for n in z.namelist()
                    )
                if slide > count:
                    detail = f"it has {count} slide{'s' * (count != 1)}"
            except (zipfile.BadZipFile, OSError):
                pass
            raise ValueError(
                f"LibreOffice didn't export slide {slide} from '{source}'"
                + (f": {detail.splitlines()[-1]}" if detail else "")
            )
        pdf = pdfium.PdfDocument(exported)
        try:
            page = pdf[0]
            width, height = page.get_size()
            # The slide's background covers the whole page
            bounds = [
                b
                for b in (
                    o.get_bounds() for o in page.get_objects(max_depth=1)
                )
                if not (
                    b[0] <= 0.5
                    and b[1] <= 0.5
                    and b[2] >= width - 0.5
                    and b[3] >= height - 0.5
                )
            ]
            if trim and bounds:
                box = (
                    min(b[0] for b in bounds),
                    min(b[1] for b in bounds),
                    max(b[2] for b in bounds),
                    max(b[3] for b in bounds),
                )
                page.set_mediabox(*box)
                page.set_cropbox(*box)
            if output.lower().endswith(".pdf"):
                pdf.save(output)
                settle(output)
            else:
                page.render(scale=(dpi or 300) / 72).to_pil().save(output)
        finally:
            pdf.close()


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
    try:
        inkscape(source, output, dpi=dpi)
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
    try:
        gimp(source, output)
    except ValueError as e:
        raise_error(str(e))


@export_app.command(
    name="powerpoint",
    help="Export a slide from a PowerPoint file with LibreOffice.",
)
def export_powerpoint(
    source: Annotated[
        str, typer.Argument(help="PowerPoint file to export from.")
    ],
    output: Annotated[
        str,
        typer.Option(
            "--output", "-o", help="File to export to, a PDF or PNG."
        ),
    ],
    slide: Annotated[
        int, typer.Option("--slide", help="Slide to export, from 1.")
    ] = 1,
    dpi: Annotated[
        int | None,
        typer.Option("--dpi", help="Resolution of a PNG (default 300)."),
    ] = None,
    trim: Annotated[
        bool,
        typer.Option(
            "--trim/--no-trim",
            help="Crop to what's drawn on the slide.",
        ),
    ] = True,
) -> None:
    try:
        powerpoint(source, output, slide=slide, dpi=dpi, trim=trim)
    except ValueError as e:
        raise_error(str(e))
