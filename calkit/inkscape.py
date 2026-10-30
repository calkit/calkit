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


def export(source: str, output: str, dpi: int | None = None) -> None:
    """Export a drawing to the format ``output``'s extension names,
    raising ``ValueError`` if it can't be.
    """
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
