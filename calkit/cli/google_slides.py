"""CLI for working with Google Slides."""

from __future__ import annotations

import os
import posixpath

import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import AliasGroup, raise_error

google_slides_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


def record_edit_times(ck_info: dict) -> list[str]:
    """Record when each Google Slides presentation the pipeline exports was
    last edited, asking the hub, and return the stages an edit put out of
    date.
    """
    from calkit.google_slides import (
        get_edit_time_path,
        get_presentation_id,
        write_edit_time,
    )

    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    edited_ids = set()
    checked_ids = set()
    for stage in stages.values():
        if stage.get("kind") != "google-slides-export":
            continue
        presentation_id = get_presentation_id(stage["presentation_url"])
        if presentation_id in checked_ids:
            continue
        checked_ids.add(presentation_id)
        info = calkit.hub.get(
            f"/user/google/presentations/{presentation_id}",
            allow_login=False,
            max_retries=2,
        )
        if write_edit_time(
            get_edit_time_path(presentation_id), info["modified_time"]
        ):
            edited_ids.add(presentation_id)
    return [
        name
        for name, stage in stages.items()
        if stage.get("kind") == "google-slides-export"
        and get_presentation_id(stage["presentation_url"]) in edited_ids
    ]


def add_presentation(
    info: dict,
    path: str,
    kind: str | None,
    stage_name: str | None,
    figures: list[str],
    pptx: bool,
    no_commit: bool,
) -> None:
    """Add a Google Slides presentation to the project, with the stage
    that exports it to ``path``, given what the hub said about it.
    """
    import calkit.google_slides
    from calkit.core import ryaml
    from calkit.models.pipeline import GoogleSlidesExportStage

    if kind is not None and kind not in ["slides", "poster"]:
        raise_error("Presentation kind must be either 'slides' or 'poster'")
    if not path.lower().endswith(".pdf"):
        raise_error(f"The exported presentation must be a PDF, not {path}")
    if stage_name is None:
        stage_name = (
            "export-" + posixpath.splitext(posixpath.basename(path))[0]
        )
    outputs = [path]
    if pptx:
        outputs.append(path[:-4] + ".pptx")
    try:
        stage = GoogleSlidesExportStage(
            presentation_url=info["url"],
            figures=figures,
            outputs=outputs,  # type: ignore[arg-type]
        )
    except Exception as e:
        raise_error(f"Invalid stage specification: {e}")
    ck_info = calkit.load_calkit_info()
    presentations = ck_info.get("presentations") or []
    if any(p.get("path") == path for p in presentations):
        raise_error(f"Presentation at path {path} already exists")
    stages = ck_info.setdefault("pipeline", {}).setdefault("stages", {})
    if stage_name in stages:
        raise_error(f"Stage '{stage_name}' already exists; pass --stage")
    presentation = {"path": path}
    if info.get("title"):
        presentation["title"] = info["title"]
    if kind is not None:
        presentation["kind"] = kind
    presentation["stage"] = stage_name
    ck_info["presentations"] = presentations + [presentation]
    stages[stage_name] = stage.to_ck_dict()
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    edit_time_path = calkit.google_slides.get_edit_time_path(info["id"])
    calkit.google_slides.write_edit_time(edit_time_path, info["modified_time"])
    typer.echo(
        f"Added {info['url']} as {path}, exported by stage '{stage_name}'"
    )
    if not no_commit:
        repo = calkit.git.get_repo()
        repo.git.add(["calkit.yaml", edit_time_path])
        repo.git.commit(
            ["calkit.yaml", edit_time_path, "-m", f"Add presentation {path}"]
        )


@google_slides_app.command(name="export")
def export(
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
    import calkit.google_slides

    try:
        presentation_id = calkit.google_slides.get_presentation_id(url)
        mime_types = [
            calkit.google_slides.get_export_mime_type(p) for p in outputs
        ]
        figure_mime_types = [
            calkit.google_slides.get_figure_mime_type(p) for p in figures
        ]
    except ValueError as e:
        raise_error(str(e))
    api_path = f"/user/google/presentations/{presentation_id}"
    for figure, mime_type in zip(figures, figure_mime_types):
        if not os.path.isfile(figure):
            raise_error(f"Figure {figure} does not exist")
        with open(figure, "rb") as f:
            content = f.read()
        resp = calkit.hub.post(
            f"{api_path}/figures",
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
    for path, mime_type in zip(outputs, mime_types):
        typer.echo(f"Exporting {path}")
        resp = calkit.hub.get(
            f"{api_path}/export",
            params={"format": posixpath.splitext(path)[1][1:].lower()},
            as_json=False,
        )
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(resp.content)
    # Putting the figures in edited the presentation, which this export
    # already accounts for
    info = calkit.hub.get(api_path)
    calkit.google_slides.write_edit_time(
        edit_time_path
        or calkit.google_slides.get_edit_time_path(presentation_id),
        info["modified_time"],
    )


@google_slides_app.command(name="pull")
def pull() -> None:
    """Check whether the project's Google Slides presentations were edited,
    putting the stages that export them out of date if so.
    """
    try:
        edited = record_edit_times(calkit.load_calkit_info())
    except Exception as e:
        raise_error(f"Failed to check Google Slides: {e}")
    if edited:
        typer.echo(
            "Edited in Google Slides, so out of date: " + ", ".join(edited)
        )
    else:
        typer.echo("No Google Slides presentations were edited")
