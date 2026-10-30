"""Exporting a figure from the file it's drawn in, with the app that draws
it, e.g., a PNG from an Inkscape SVG, as ``calkit export`` does.

A source no app can export without a person, e.g., a Photoshop file, is a
manual stage instead.
"""

from __future__ import annotations

import os

# The app that exports each kind of source
APPS = {".svg": "Inkscape", ".xcf": "GIMP"}


def app_name(source: str) -> str | None:
    """The app that exports a source, or None if a person has to."""
    return APPS.get(os.path.splitext(source)[1].lower())


def check_paths(source: str, output: str, dpi: int | None = None) -> None:
    """Raise ``ValueError`` unless an app can export ``source`` to
    ``output``.
    """
    import calkit.gimp
    import calkit.inkscape

    name = app_name(source)
    if name is None:
        raise ValueError(
            f"Nothing exports '{source}' on its own; supported sources are "
            f"{', '.join(sorted(APPS))}, and anything else is a manual stage"
        )
    exts = (calkit.inkscape if name == "Inkscape" else calkit.gimp).EXPORT_EXTS
    if os.path.splitext(output)[1].lower() not in exts:
        raise ValueError(
            f"{name} can export '{source}' to {', '.join(sorted(exts))}, "
            f"not '{output}'"
        )
    if dpi is not None and name != "Inkscape":
        raise ValueError("dpi only applies to an SVG exported with Inkscape")


def find_app(source: str) -> str | None:
    """The executable that exports a source here, if it's installed."""
    import calkit.gimp
    import calkit.inkscape

    name = app_name(source)
    if name == "Inkscape":
        return calkit.inkscape.find_executable()
    if name == "GIMP":
        return calkit.gimp.find_executable()
    return None


def export(source: str, output: str, dpi: int | None = None) -> None:
    """Export ``output`` from ``source``, raising ``ValueError`` if it
    can't be.
    """
    import calkit.gimp
    import calkit.inkscape

    check_paths(source, output, dpi)
    if not os.path.isfile(source):
        raise ValueError(f"'{source}' doesn't exist")
    out_dir = os.path.dirname(output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    # What was there is from before, so it can't pass for a new export
    if os.path.exists(output):
        os.remove(output)
    if app_name(source) == "Inkscape":
        calkit.inkscape.export(source, output, dpi=dpi)
    else:
        calkit.gimp.export(source, output)
