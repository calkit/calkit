"""CLI for exporting data and artifacts from various apps, e.g., a PNG
from an Inkscape SVG.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

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


@export_app.command(name="google-slides")
def google_slides(
    url: Annotated[
        str, typer.Argument(help="URL of the Google Slides presentation.")
    ],
    outputs: Annotated[
        list[str],
        typer.Option(
            "--output", "-o", help="File to export to, a .pdf or .pptx."
        ),
    ],
    figures: Annotated[
        list[str],
        typer.Option(
            "--figure",
            help=(
                "Project figure to put in first, replacing the images "
                "tagged with its path, or added to the first slide."
            ),
        ),
    ] = [],
    edit_time_path: Annotated[
        str | None,
        typer.Option(
            "--edit-time-path",
            help="Where to record when the presentation was last edited.",
        ),
    ] = None,
) -> None:
    """Put figures into a Google Slides presentation, then export it."""
    import posixpath

    import calkit.google
    from calkit.cli.google import get_presentation_response

    def ask_hub(kind: str, suffix: str, action: str, **kwargs: Any) -> Any:
        try:
            return get_presentation_response(
                kind, presentation_id, suffix, **kwargs
            )
        except Exception as e:
            raise_error(f"Failed to {action}: {e}")

    try:
        presentation_id = calkit.google.get_slides_presentation_id(url)
        mime_types = [
            calkit.google.get_slides_export_mime_type(p) for p in outputs
        ]
        figure_mime_types = [
            calkit.google.get_figure_mime_type(p) for p in figures
        ]
    except ValueError as e:
        raise_error(str(e))
    for figure, mime_type in zip(figures, figure_mime_types):
        if not os.path.isfile(figure):
            raise_error(f"Figure {figure} does not exist")
        with open(figure, "rb") as f:
            content = f.read()
        resp = ask_hub(
            "post",
            "/figures",
            f"put {figure} in the presentation",
            params={"path": figure},
            files={"file": (posixpath.basename(figure), content, mime_type)},
        )
        if resp["added"]:
            typer.echo(
                f"Added {figure} to the first slide; move it into place in "
                "Google Slides"
            )
        else:
            typer.echo(f"Updated {figure} in {resp['replaced']} place(s)")
    # Taken before exporting, since putting the figures in edited it, and
    # so an edit made while exporting is seen as one next time
    info = ask_hub("get", "", "check when it was last edited")
    for path, mime_type in zip(outputs, mime_types):
        typer.echo(f"Exporting {path}")
        resp = ask_hub(
            "get",
            "/export",
            f"export {path}",
            params={"format": posixpath.splitext(path)[1][1:].lower()},
            as_json=False,
        )
        # An unchanged presentation exports to a file that differs only in
        # its date, which would rerun everything downstream of it
        if os.path.isfile(path):
            with open(path, "rb") as existing:
                if calkit.google.is_same_export(
                    existing.read(), resp.content, path
                ):
                    typer.echo(f"{path} is unchanged, so it was kept")
                    continue
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as out:
            out.write(resp.content)
    calkit.google.write_edit_time(
        edit_time_path or calkit.google.get_edit_time_path(presentation_id),
        info["modified_time"],
    )
