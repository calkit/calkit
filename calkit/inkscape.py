"""Working with Inkscape."""

from __future__ import annotations

import os
import shutil
import subprocess

# Where its executable can be when it isn't on PATH, e.g., installed on
# macOS from its own download
EXECUTABLES = [
    "inkscape",
    "/Applications/Inkscape.app/Contents/MacOS/inkscape",
    r"C:\Program Files\Inkscape\bin\inkscape.exe",
]
SOURCE_EXTS = {".svg"}
EXPORT_EXTS = {".png", ".pdf", ".eps", ".ps"}


def find_executable() -> str | None:
    """Inkscape's executable here, if it's installed."""
    for candidate in EXECUTABLES:
        found = shutil.which(candidate)
        if found:
            return found
        if os.path.isabs(candidate) and os.path.isfile(candidate):
            return candidate
    return None


def check_export(source: str, output: str) -> None:
    """Raise ``ValueError`` unless Inkscape can export ``source`` to
    ``output``.
    """
    if os.path.splitext(source)[1].lower() not in SOURCE_EXTS:
        raise ValueError(f"Inkscape exports from an SVG, not '{source}'")
    if os.path.splitext(output)[1].lower() not in EXPORT_EXTS:
        raise ValueError(
            f"Inkscape can export to {', '.join(sorted(EXPORT_EXTS))}, "
            f"not '{output}'"
        )


def export(source: str, output: str, dpi: int | None = None) -> None:
    """Export a drawing to the format ``output``'s extension names,
    raising ``ValueError`` if it can't be.
    """
    check_export(source, output)
    if not os.path.isfile(source):
        raise ValueError(f"'{source}' doesn't exist")
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    # What was there is from before, so it can't pass for a new export
    if os.path.exists(output):
        os.remove(output)
    exe = find_executable()
    if exe is None:
        raise ValueError(f"Exporting '{source}' needs Inkscape installed")
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
