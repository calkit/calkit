"""CLI for working with Google Slides."""

from __future__ import annotations

import os
import posixpath
from typing import Any

import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import AliasGroup, raise_error

google_slides_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


def record_edit_times(ck_info: dict, quick: bool = False) -> list[str]:
    """Record when each Google Slides presentation the pipeline exports was
    last edited, asking the hub, and return the stages an edit put out of
    date.

    ``quick`` makes one short attempt per presentation, for checks that must
    not hold things up, e.g., in ``calkit status``.
    """
    from concurrent.futures import ThreadPoolExecutor

    from calkit.google_slides import (
        get_edit_time_path,
        get_presentation_id,
        write_edit_time,
    )

    def get_modified_time(presentation_id: str) -> str:
        info = calkit.hub.get(
            f"/user/google/presentations/{presentation_id}",
            allow_login=False,
            max_retries=0 if quick else 2,
            timeout=(2, 5) if quick else (10, 120),
        )
        return str(info["modified_time"])

    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    ids = {
        name: get_presentation_id(stage["presentation_url"])
        for name, stage in stages.items()
        if stage.get("kind") == "google-slides-export"
    }
    unique_ids = list(dict.fromkeys(ids.values()))
    with ThreadPoolExecutor(max_workers=8) as pool:
        modified_times = list(pool.map(get_modified_time, unique_ids))
    edited_ids = {
        presentation_id
        for presentation_id, modified_time in zip(unique_ids, modified_times)
        if write_edit_time(get_edit_time_path(presentation_id), modified_time)
    }
    return [name for name, pid in ids.items() if pid in edited_ids]


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

    if stage_name is None:
        stage_name = calkit.google_slides.get_default_stage_name(path)
    ck_info = calkit.load_calkit_info()
    try:
        calkit.google_slides.add_presentation(
            ck_info,
            info,
            path=path,
            kind=kind,
            stage_name=stage_name,
            figures=figures,
            pptx=pptx,
        )
    except ValueError as e:
        raise_error(str(e))
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


def add_slide_figure(
    ck_info: dict, url: str, path: str, stage_name: str | None
) -> str:
    """Have the stage exporting a presentation export a slide, given its
    URL, to the figure at ``path``, adding the stage if needed, and return
    the stage's name.
    """
    import calkit.google_slides

    try:
        presentation_id = calkit.google_slides.get_presentation_id(url)
        calkit.google_slides.get_slide_export_format(path)
    except ValueError as e:
        raise_error(str(e))
    slide_id = calkit.google_slides.get_slide_id(url)
    if slide_id is None:
        raise_error(
            "That URL doesn't say which slide; open the slide in Google "
            "Slides and copy the URL, which ends with '#slide=id.' and its ID"
        )
    api_path = f"/user/google/presentations/{presentation_id}"
    try:
        info = calkit.hub.get(api_path)
        layout = calkit.hub.get(f"{api_path}/slides")
    except Exception as e:
        raise_error(f"Failed to open the presentation: {e}")
    slide = next((s for s in layout["slides"] if s["id"] == slide_id), None)
    if slide is None:
        raise_error(f"The presentation has no slide '{slide_id}'")
    if stage_name is None:
        stage_name = calkit.google_slides.get_slides_stage_name(
            ck_info, presentation_id, info.get("title")
        )
    try:
        calkit.google_slides.add_slide_figure(
            ck_info, info, slide_id, path, stage_name=stage_name
        )
    except ValueError as e:
        raise_error(str(e))
    calkit.google_slides.write_edit_time(
        calkit.google_slides.get_edit_time_path(presentation_id),
        info["modified_time"],
    )
    typer.echo(f"Stage '{stage_name}' exports slide {slide_id} to {path}")
    if slide["bounds"] is None:
        typer.echo("Nothing is drawn on the slide yet")
    return stage_name


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
    ] = [],
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
    slides: Annotated[
        list[str],
        typer.Option(
            "--slide",
            help=(
                "Figure to export from a slide, as its path and the slide's "
                "ID, e.g., 'figures/setup.pdf=g2c3a1b9_0_12', cropped to "
                "what's drawn on it."
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
    """Put figures into a Google Slides presentation, then export it, and
    figures from its slides.
    """
    import calkit.google_slides

    exports: dict[str, bytes] = {}

    def ask_hub(kind: str, path: str, action: str, **kwargs: Any) -> Any:
        try:
            return getattr(calkit.hub, kind)(path, **kwargs)
        except Exception as e:
            raise_error(f"Failed to {action}: {e}")

    def get_export(fmt: str) -> bytes:
        if fmt not in exports:
            exports[fmt] = ask_hub(
                "get",
                f"{api_path}/export",
                f"export the presentation as {fmt}",
                params={"format": fmt},
                as_json=False,
            ).content
        return exports[fmt]

    def write(path: str, content: bytes) -> None:
        # An unchanged presentation exports to a file that differs only in
        # its date, which would rerun everything downstream of it
        if os.path.isfile(path):
            with open(path, "rb") as existing:
                if calkit.google_slides.is_same_export(
                    existing.read(), content, path
                ):
                    typer.echo(f"{path} is unchanged, so it was kept")
                    return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as out:
            out.write(content)

    try:
        presentation_id = calkit.google_slides.get_presentation_id(url)
        for p in outputs:
            calkit.google_slides.get_export_mime_type(p)
        figure_mime_types = [
            calkit.google_slides.get_figure_mime_type(p) for p in figures
        ]
        slide_ids = {}
        for spec in slides:
            path, sep, slide_id = spec.rpartition("=")
            if not sep or not path or not slide_id:
                raise ValueError(
                    f"A slide is given as its figure's path and its ID, e.g., "
                    f"'figures/setup.pdf=g2c3a1b9_0_12', not {spec!r}"
                )
            calkit.google_slides.get_slide_export_format(path)
            slide_ids[path] = slide_id
    except ValueError as e:
        raise_error(str(e))
    api_path = f"/user/google/presentations/{presentation_id}"
    for figure, mime_type in zip(figures, figure_mime_types):
        if not os.path.isfile(figure):
            raise_error(f"Figure {figure} does not exist")
        with open(figure, "rb") as f:
            content = f.read()
        resp = ask_hub(
            "post",
            f"{api_path}/figures",
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
    for path in outputs:
        typer.echo(f"Exporting {path}")
        write(path, get_export(posixpath.splitext(path)[1][1:].lower()))
    if slide_ids:
        layout = ask_hub("get", f"{api_path}/slides", "read the slides")
        by_id = {s["id"]: s for s in layout["slides"]}
        for path, slide_id in slide_ids.items():
            if slide_id in by_id:
                continue
            # A slide copied, e.g., from a deleted one keeps its notes
            tag = calkit.google_slides.get_figure_tag(path)
            tagged = [
                s["id"]
                for s in layout["slides"]
                if tag in s["notes"].splitlines()
            ]
            hint = (
                f"; the slide whose notes say '{tag}' is '{tagged[0]}', so "
                "set that as its slide in calkit.yaml"
                if tagged
                else "; link it to a slide again with 'calkit new figure "
                f"{path} --google-slide <the slide's URL>'"
            )
            raise_error(
                f"The slide {path} is exported from ({slide_id}) is no "
                f"longer in the presentation{hint}"
            )
        # Each slide says in its notes which figure it makes, so someone
        # editing the presentation can tell
        ask_hub(
            "post",
            f"{api_path}/slide-tags",
            "tag the slides",
            json={"tags": slide_ids},
        )
        import pypdfium2

        # If the PDF leaves skipped slides out, its pages are the others
        deck = pypdfium2.PdfDocument(get_export("pdf"))
        n_pages = len(deck)
        deck.close()
        pages = [s["id"] for s in layout["slides"]]
        if n_pages != len(pages):
            pages = [s["id"] for s in layout["slides"] if not s["is_skipped"]]
        for path, slide_id in slide_ids.items():
            if slide_id not in pages:
                raise_error(
                    f"The slide {path} is exported from is skipped, so "
                    "Google leaves it out of exports; unskip it"
                )
            bounds = by_id[slide_id]["bounds"]
            if bounds is None:
                raise_error(f"Nothing is drawn on the slide {path} is from")
            typer.echo(f"Exporting {path} from slide {slide_id}")
            write(
                path,
                calkit.google_slides.get_slide_export(
                    get_export("pdf"),
                    pages.index(slide_id),
                    bounds,
                    layout["page_size"],
                    path,
                ),
            )
    # Putting the figures in edited the presentation, which this export
    # already accounts for
    info = ask_hub("get", api_path, "check when it was last edited")
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
