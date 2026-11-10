"""CLI for working with Google files, e.g., Slides."""

from __future__ import annotations

import os
import posixpath
from typing import Any

import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import AliasGroup, raise_error

google_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


def get_hub_response(kind: str, path: str, **kwargs: Any) -> Any:
    """Return the hub's response to a request that uses the user's Google
    account, first connecting it in the browser if it isn't connected and
    someone is here to.
    """
    import time
    import webbrowser

    import requests

    from calkit.core import is_tty

    request = getattr(calkit.hub, kind)
    try:
        return request(path, **kwargs)
    except requests.HTTPError as e:
        if (
            e.response is None
            or e.response.status_code != 403
            or not is_tty()
            or calkit.hub.get("/user/connected-accounts").get("google")
        ):
            raise
    url = (
        calkit.hub.get_hub_url().rstrip("/")
        + "/settings?tab=connected-accounts&connect=google"
    )
    typer.echo("Connect your Google account to Calkit by opening this URL:")
    typer.echo(url)
    typer.echo("Waiting for it to be connected (Ctrl+C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    deadline = time.monotonic() + 600
    while not calkit.hub.get("/user/connected-accounts").get("google"):
        if time.monotonic() > deadline:
            raise RuntimeError("Google wasn't connected within 10 minutes")
        time.sleep(2)
    typer.echo("Google is connected")
    return request(path, **kwargs)


def record_edit_times(ck_info: dict, quick: bool = False) -> list[str]:
    """Record when each Google Slides presentation the pipeline, or a
    subproject's, exports was last edited, asking the hub, and return the
    stages an edit put out of date, e.g., 'sub/dvc.yaml:export-poster' in a
    subproject.

    ``quick`` makes one short attempt per presentation, for checks that must
    not hold things up, e.g., in ``calkit status``. Times that could be
    fetched are recorded even if others couldn't, which are then raised as
    a ``RuntimeError``.
    """
    from concurrent.futures import ThreadPoolExecutor

    import requests

    from calkit.google import (
        get_edit_time_path,
        get_slides_presentation_id,
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

    # Each presentation's exporting stages, by project directory
    exporters: dict[str, dict[str, list[str]]] = {}
    for wdir, info in calkit.iter_projects(ck_info=ck_info):
        stages = (info.get("pipeline") or {}).get("stages") or {}
        for name, stage in stages.items():
            if not (
                isinstance(stage, dict)
                and stage.get("kind") == "google-slides-export"
            ):
                continue
            presentation_id = get_slides_presentation_id(
                stage["presentation_url"]
            )
            label = name if wdir == "." else f"{wdir}/dvc.yaml:{name}"
            exporters.setdefault(presentation_id, {}).setdefault(
                wdir, []
            ).append(label)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            presentation_id: pool.submit(get_modified_time, presentation_id)
            for presentation_id in exporters
        }
    edited = []
    failures = []
    unreachable = False
    for presentation_id, future in futures.items():
        try:
            modified_time = future.result()
        except (requests.ConnectionError, requests.Timeout):
            unreachable = True
            continue
        except Exception as e:
            failures.append(f"{presentation_id}: {e}")
            continue
        for wdir, labels in exporters[presentation_id].items():
            path = os.path.join(wdir, get_edit_time_path(presentation_id))
            if write_edit_time(path, modified_time):
                edited += labels
    if unreachable:
        raise RuntimeError("couldn't reach the hub")
    if failures:
        raise RuntimeError("; ".join(failures))
    return edited


def add_slides_presentation(
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
    import calkit.google
    from calkit.core import ryaml

    if stage_name is None:
        stage_name = calkit.google.get_default_slides_stage_name(path)
    ck_info = calkit.load_calkit_info()
    try:
        calkit.google.add_slides_presentation(
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
    edit_time_path = calkit.google.get_edit_time_path(info["id"])
    calkit.google.write_edit_time(edit_time_path, info["modified_time"])
    typer.echo(
        f"Added {info['url']} as {path}, exported by stage '{stage_name}'"
    )
    if not no_commit:
        repo = calkit.git.get_repo()
        repo.git.add(["calkit.yaml", edit_time_path])
        repo.git.commit(
            ["calkit.yaml", edit_time_path, "-m", f"Add presentation {path}"]
        )


@google_app.command(name="export-slides")
def export_slides(
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
    import calkit.google

    def ask_hub(kind: str, path: str, action: str, **kwargs: Any) -> Any:
        try:
            return get_hub_response(kind, path, **kwargs)
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
    # Taken before exporting, since putting the figures in edited it, and
    # so an edit made while exporting is seen as one next time
    info = ask_hub("get", api_path, "check when it was last edited")
    for path, mime_type in zip(outputs, mime_types):
        typer.echo(f"Exporting {path}")
        resp = ask_hub(
            "get",
            f"{api_path}/export",
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


@google_app.command(name="pull")
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
