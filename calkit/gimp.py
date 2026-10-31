"""Working with GIMP."""

from __future__ import annotations

import os
import shutil
import subprocess

# The console binary, since the plain 'gimp' on macOS opens a window and
# ignores batch flags, and where it can be when it isn't on PATH
EXECUTABLES = [
    "gimp-console",
    "gimp-console-3",
    "gimp-console-2.10",
    "/Applications/GIMP.app/Contents/MacOS/gimp-console",
    r"C:\Program Files\GIMP 3\bin\gimp-console-3.0.exe",
    r"C:\Program Files\GIMP 2\bin\gimp-console-2.10.exe",
]
SOURCE_EXTS = {".xcf"}
EXPORT_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def find_executable() -> str | None:
    """GIMP's console executable here, if it's installed."""
    for candidate in EXECUTABLES:
        found = shutil.which(candidate)
        if found:
            return found
        if os.path.isabs(candidate) and os.path.isfile(candidate):
            return candidate
    return None


def check_export(source: str, output: str) -> None:
    """Raise ``ValueError`` unless GIMP can export ``source`` to
    ``output``.
    """
    if os.path.splitext(source)[1].lower() not in SOURCE_EXTS:
        raise ValueError(f"GIMP exports from an XCF file, not '{source}'")
    if os.path.splitext(output)[1].lower() not in EXPORT_EXTS:
        raise ValueError(
            f"GIMP can export to {', '.join(sorted(EXPORT_EXTS))}, "
            f"not '{output}'"
        )


def export(source: str, output: str) -> None:
    """Flatten a GIMP document into the format ``output``'s extension
    names, raising ``ValueError`` if it can't be.

    Runs GIMP 3's batch dialect, then GIMP 2's, which differ in their file
    procedures. Neither reports a failed script in its exit code, so the
    written file is what says it worked.
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
        raise ValueError(f"Exporting '{source}' needs GIMP installed")
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
