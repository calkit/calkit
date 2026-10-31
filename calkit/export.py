"""Exporting a figure from the file it's drawn in, e.g., a PNG from an
Inkscape SVG: by an app as the pipeline runs, if one can, or else by a
person, as a manual step.

The apps that can are listed here once, so the CLI, the hub, and anything
built on them agree on which they are.
"""

from __future__ import annotations

import dataclasses
import os
import re
import shutil
from typing import Callable


@dataclasses.dataclass(frozen=True)
class Exporter:
    """An app that exports as the pipeline runs, and its stage kind."""

    kind: str
    app: str
    source_exts: frozenset[str]
    export_exts: frozenset[str]
    find_executable: Callable[[], str | None]


def exporters() -> list[Exporter]:
    from calkit import gimp, inkscape

    return [
        Exporter(
            kind=module.STAGE_KIND,
            app=module.APP,
            source_exts=frozenset(module.SOURCE_EXTS),
            export_exts=frozenset(module.EXPORT_EXTS),
            find_executable=module.find_executable,
        )
        for module in (inkscape, gimp)
    ]


def find_executable(candidates: list[str]) -> str | None:
    """The first of an app's candidate executables that's here, whether
    on PATH or at an absolute path where its installer puts it.
    """
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
        if os.path.isabs(candidate) and os.path.isfile(candidate):
            return candidate
    return None


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
