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


def export_with_inkscape(
    source: str, output: str, dpi: int | None = None
) -> None:
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


def export_with_gimp(source: str, output: str) -> None:
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


def export_slides(
    source: str,
    output: str,
    slides: list[int] | None = None,
    dpi: int | None = None,
    trim: bool | None = None,
    env: str = "_system",
) -> None:
    """Export slides to the format ``output``'s extension names, with the
    app ``env`` provides, raising ``ValueError`` if they can't be.

    Every slide unless ``slides`` says which, numbered from 1 and counting
    hidden ones. Several go into one PDF, or a file each if ``output`` has
    ``{slide}`` in it. Each is cropped to what's drawn on it unless
    ``trim`` is false, which it is by default for several in one PDF.
    """
    import json
    import re
    import shutil
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    import pypdfium2 as pdfium
    from PIL import ImageChops

    import calkit
    from calkit.export import LIBREOFFICE, get_slide_exporter
    from calkit.pptx import Presentation

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

    def export_pdfs(decks: list[str]) -> list[str]:
        """Export each deck's chosen slides to a PDF, a page each in order."""
        pdfs = [os.path.splitext(deck)[0] + ".pdf" for deck in decks]
        if exporter is LIBREOFFICE:
            # Hidden slides count, so numbers match PowerPoint's
            options = {
                "PageRange": {
                    "type": "string",
                    "value": ",".join(str(n) for n in numbers),
                },
                "ExportHiddenSlides": {"type": "boolean", "value": "true"},
            }
            # A profile of its own, since a LibreOffice already open would
            # take the job and exit without doing it
            profile = (
                "file:///tmp/calkit-libreoffice"
                if docker_env is not None
                else Path(work, "profile").as_uri()
            )
            cmd = (
                ["calkit", "xenv", "-n", docker_env, "--no-check", "--"]
                + ["soffice"]
                if docker_env is not None
                else [exe]
            )
            result = subprocess.run(
                cmd
                + [
                    f"-env:UserInstallation={profile}",
                    "--headless",
                    "--convert-to",
                    "pdf:impress_pdf_Export:" + json.dumps(options),
                    "--outdir",
                    work,
                ]
                + decks,
                capture_output=True,
                text=True,
            )
            detail = (result.stderr or result.stdout or "").strip()
        elif sys.platform == "darwin":

            def quote(path: str) -> str:
                path = os.path.abspath(path)
                return (
                    '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'
                )

            # It quits after only if it wasn't open before
            lines = [
                'set wasRunning to application "Microsoft PowerPoint" '
                "is running",
                'tell application "Microsoft PowerPoint"',
            ]
            for deck, pdf in zip(decks, pdfs):
                lines += [
                    f"    open POSIX file {quote(deck)}",
                    "    set pres to active presentation",
                    f"    save pres in POSIX file {quote(pdf)} as save as PDF",
                    "    close pres saving no",
                ]
            lines += ["    if not wasRunning then quit", "end tell"]
            result = subprocess.run(
                ["osascript", "-e", "\n".join(lines)],
                capture_output=True,
                text=True,
            )
            detail = (result.stderr or result.stdout or "").strip()
        else:
            import pythoncom  # type: ignore[import-untyped]
            import win32com.client  # type: ignore[import-untyped]

            pythoncom.CoInitialize()
            try:
                win32com.client.GetActiveObject("PowerPoint.Application")
                was_running = True
            except Exception:
                was_running = False
            app = win32com.client.Dispatch("PowerPoint.Application")
            detail = ""
            try:
                for deck, pdf in zip(decks, pdfs):
                    pres = app.Presentations.Open(
                        os.path.abspath(deck),
                        ReadOnly=True,
                        Untitled=False,
                        WithWindow=False,
                    )
                    try:
                        # 32 is ppSaveAsPDF
                        pres.SaveAs(os.path.abspath(pdf), 32)
                    finally:
                        pres.Close()
            except Exception as e:
                detail = str(e)
            finally:
                if not was_running:
                    app.Quit()
        for pdf in pdfs:
            if not os.path.isfile(pdf):
                raise ValueError(
                    f"{exporter.app} didn't export slides from '{source}'"
                    + (f": {detail.splitlines()[-1]}" if detail else "")
                )
            if exporter is LIBREOFFICE:
                continue
            # PowerPoint exports every slide, so keep the ones asked for
            whole = pdfium.PdfDocument(pdf)
            chosen = pdfium.PdfDocument.new()
            try:
                chosen.import_pages(whole, [n - 1 for n in numbers])
                chosen.save(pdf + ".tmp")
            finally:
                chosen.close()
                whole.close()
            os.replace(pdf + ".tmp", pdf)
        return pdfs

    LIBREOFFICE.check(source, output.replace("{slide}", "1"))
    if not os.path.isfile(source):
        raise ValueError(f"'{source}' doesn't exist")
    exporter, docker_env = get_slide_exporter(
        env, ck_info=None if env == "_system" else calkit.load_calkit_info()
    )
    found = exporter.find_executable() if docker_env is None else "soffice"
    if found is None:
        raise ValueError(
            f"Exporting '{source}' needs {exporter.app} installed"
        )
    exe: str = found
    # Which slides, and where each goes
    pres = Presentation(source)
    numbers = sorted(set(slides or range(1, len(pres.slides) + 1)))
    for n in numbers:
        if n < 1:
            raise ValueError("Slides are numbered from 1")
        pres.slide(n)
    each = "{slide}" in output
    single_pdf = not each and output.lower().endswith(".pdf")
    if not each and not single_pdf and len(numbers) > 1:
        raise ValueError(
            "Several slides go into one PDF, or a file each with {slide} "
            "in the output's name, e.g., 'figures/slide-{slide}.png'"
        )
    if trim is None:
        trim = each or len(numbers) == 1
    outputs = [output.replace("{slide}", str(n)) for n in numbers]
    for out in outputs:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        # What was there is from before, so it can't pass for a new export
        if os.path.exists(out):
            os.remove(out)
    # Somewhere the app can read and write: in the project for a Docker
    # environment, which only sees the project, and in its own container
    # for PowerPoint on macOS, which is sandboxed
    if docker_env is not None:
        os.makedirs(".calkit", exist_ok=True)
        work = os.path.relpath(tempfile.mkdtemp(dir=".calkit", prefix="tmp-"))
    elif exporter is not LIBREOFFICE and sys.platform == "darwin":
        container = os.path.expanduser(
            "~/Library/Containers/com.microsoft.Powerpoint/Data"
        )
        os.makedirs(container, exist_ok=True)
        work = tempfile.mkdtemp(dir=container, prefix="calkit-")
    else:
        work = tempfile.mkdtemp(prefix="calkit-")
    try:
        # Unhidden, since PowerPoint leaves hidden slides out, and beside
        # it the same slides with nothing drawn on them, so what's drawn is
        # whatever differs
        decks = [os.path.join(work, "slides.pptx")]
        pres.show_hidden_slides()
        pres.save(decks[0])
        if trim:
            for n in numbers:
                pres.clear_slide(n)
            decks.append(os.path.join(work, "blank.pptx"))
            pres.save(decks[1])
        pdfs = export_pdfs(decks)
        pdf = pdfium.PdfDocument(pdfs[0])
        blank = pdfium.PdfDocument(pdfs[1]) if trim else None
        try:
            for i in range(len(numbers)):
                page = pdf[i]
                if blank is not None:
                    # Rendered finely enough to place the edge within a
                    # quarter point
                    scale = 4
                    drawn = page.render(scale=scale).to_pil().convert("RGB")
                    empty = blank[i].render(scale=scale).to_pil()
                    box = (
                        ImageChops.difference(drawn, empty.convert("RGB"))
                        .convert("L")
                        .point(lambda v: 255 if v > 16 else 0)
                        .getbbox()
                    )
                    if box is not None:
                        left, bottom, _, top = page.get_cropbox()
                        crop = (
                            left + box[0] / scale,
                            top - box[3] / scale,
                            left + box[2] / scale,
                            top - box[1] / scale,
                        )
                        page.set_mediabox(*crop)
                        page.set_cropbox(*crop)
                if not single_pdf and not outputs[i].lower().endswith(".pdf"):
                    page.render(scale=(dpi or 300) / 72).to_pil().save(
                        outputs[i]
                    )
            # PDFs made fresh, so they carry nothing of the app's own
            groups = (
                [(outputs[0], list(range(len(numbers))))]
                if single_pdf
                else [
                    (out, [i])
                    for i, out in enumerate(outputs)
                    if out.lower().endswith(".pdf")
                ]
            )
            for out, pages in groups:
                doc = pdfium.PdfDocument.new()
                try:
                    doc.import_pages(pdf, pages)
                    doc.save(out)
                finally:
                    doc.close()
                settle(out)
        finally:
            pdf.close()
            if blank is not None:
                blank.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
        export_with_inkscape(source, output, dpi=dpi)
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
        export_with_gimp(source, output)
    except ValueError as e:
        raise_error(str(e))


@export_app.command(
    name="pptx",
    help="Export slides from a PowerPoint file to PDF or PNG.",
)
def export_pptx(
    source: Annotated[
        str, typer.Argument(help="PowerPoint file to export from.")
    ],
    output: Annotated[
        str,
        typer.Option(
            "--output",
            "-o",
            help=(
                "PDF or PNG to export to, with {slide} in its name for a "
                "file per slide."
            ),
        ),
    ],
    slides: Annotated[
        str | None,
        typer.Option(
            "--slides",
            help="Slides to export, e.g., '3' or '2,4-6' (default all).",
        ),
    ] = None,
    dpi: Annotated[
        int | None,
        typer.Option("--dpi", help="Resolution of a PNG (default 300)."),
    ] = None,
    trim: Annotated[
        bool | None,
        typer.Option(
            "--trim/--no-trim",
            help=(
                "Crop to what's drawn on each slide (default unless several "
                "go into one PDF)."
            ),
        ),
    ] = None,
    env: Annotated[
        str | None,
        typer.Option(
            "--env",
            "-e",
            help="Environment whose app exports them (default the system).",
        ),
    ] = None,
) -> None:
    import re

    numbers = None
    if slides is not None:
        numbers = []
        for part in slides.split(","):
            m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
            if m is None:
                raise_error(f"'{slides}' should list slides, e.g., '2,4-6'")
            numbers += list(range(int(m[1]), int(m[2] or m[1]) + 1))
    try:
        export_slides(
            source,
            output,
            slides=numbers,
            dpi=dpi,
            trim=trim,
            env=env or "_system",
        )
    except ValueError as e:
        raise_error(str(e))
