"""Exporting data and artifacts from various apps, e.g., a PNG from an
Inkscape SVG.

An app that can export from the command line does it as the pipeline runs,
in a stage of its own kind. Anything else is a manual step. The apps that
can are listed here once, so the CLI, the hub, and anything built on them
agree on which they are.
"""

from __future__ import annotations

import dataclasses
import os
import re


@dataclasses.dataclass
class Exporter:
    """An app that exports as the pipeline runs, and its stage kind."""

    # As a key, e.g., in 'inkscape_version'
    name: str
    kind: str
    app: str
    # What it exports from, as a person would say it
    source_desc: str
    source_exts: frozenset[str]
    export_exts: frozenset[str]
    # Its executable, by name on PATH, or where its installer puts it
    executables: list[str]

    def find_executable(self) -> str | None:
        """Its executable here, if it's installed."""
        import shutil

        for candidate in self.executables:
            found = shutil.which(candidate)
            if found:
                return found
            if os.path.isabs(candidate) and os.path.isfile(candidate):
                return candidate
        return None

    def version(self) -> str | None:
        """The version installed here, if it's installed and says."""
        import subprocess

        from calkit.core import extract_version

        exe = self.find_executable()
        if exe is None:
            return None
        try:
            result = subprocess.run(
                [exe, "--version"], capture_output=True, text=True, timeout=60
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return extract_version(result.stdout or result.stderr or "")

    def check(self, source: str, output: str) -> None:
        """Raise ``ValueError`` unless it can export ``source`` to
        ``output``.
        """
        if os.path.splitext(source)[1].lower() not in self.source_exts:
            raise ValueError(
                f"{self.app} exports from {self.source_desc}, not '{source}'"
            )
        if os.path.splitext(output)[1].lower() not in self.export_exts:
            raise ValueError(
                f"{self.app} can export to "
                f"{', '.join(sorted(self.export_exts))}, not '{output}'"
            )


INKSCAPE = Exporter(
    name="inkscape",
    kind="inkscape-export",
    app="Inkscape",
    source_desc="an SVG",
    source_exts=frozenset({".svg"}),
    export_exts=frozenset({".png", ".pdf", ".eps", ".ps"}),
    executables=[
        "inkscape",
        "/Applications/Inkscape.app/Contents/MacOS/inkscape",
        r"C:\Program Files\Inkscape\bin\inkscape.exe",
    ],
)
GIMP = Exporter(
    name="gimp",
    kind="gimp-export",
    app="GIMP",
    source_desc="an XCF file",
    source_exts=frozenset({".xcf"}),
    export_exts=frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff"}),
    # The console binary, since the plain 'gimp' on macOS opens a window
    # and ignores batch flags
    executables=[
        "gimp-console",
        "gimp-console-3",
        "gimp-console-2.10",
        "/Applications/GIMP.app/Contents/MacOS/gimp-console",
        r"C:\Program Files\GIMP 3\bin\gimp-console-3.0.exe",
        r"C:\Program Files\GIMP 2\bin\gimp-console-2.10.exe",
    ],
)


def exporters() -> list[Exporter]:
    return [INKSCAPE, GIMP]


def exporter_for(
    source: str, output: str, app: str | None = None
) -> Exporter | None:
    """The app that can export ``output`` from ``source`` as the pipeline
    runs, if any.

    One a person names has to be that app: an SVG exported with
    Illustrator is a manual step, even though Inkscape could do it.
    """
    source_ext = os.path.splitext(source)[1].lower()
    output_ext = os.path.splitext(output)[1].lower()
    named = (app or "").strip().lower()
    for exporter in exporters():
        if (
            source_ext in exporter.source_exts
            and output_ext in exporter.export_exts
            and named in ("", exporter.app.lower())
        ):
            return exporter
    return None


def export_stage(source: str, output: str, app: str | None = None) -> dict:
    """The stage exporting ``output`` from ``source``, as written in
    calkit.yaml.

    An app that can does it as the pipeline runs. Otherwise it's a manual
    step, which opens ``source`` in ``app`` if one is named.
    """
    exporter = exporter_for(source, output, app=app)
    if exporter is not None:
        return {
            "kind": exporter.kind,
            "source_path": source,
            "outputs": [output],
        }
    app = (app or "").strip()
    stage: dict = {
        "kind": "manual-step",
        "message": (
            f"In {app}, export {output} from {source}"
            if app
            else f"Export {output} from {source}"
        ),
        "inputs": [source],
        "outputs": [output],
    }
    if app:
        stage["open"] = {"app": app, "path": source}
    return stage


def export_stage_name(output: str) -> str:
    """A name for the stage exporting ``output``, e.g., ``export-setup``."""
    stem = os.path.splitext(os.path.basename(output))[0]
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return f"export-{slug or 'figure'}"
