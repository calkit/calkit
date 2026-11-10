"""CLI helpers for working with Google files, e.g., Slides, through the
hub.
"""

from __future__ import annotations

import os
from typing import Any

import typer

import calkit
from calkit.cli import raise_error, warn


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


def get_presentation_response(
    kind: str,
    presentation_id: str,
    suffix: str = "",
    wdir: str | None = None,
    connect: bool = True,
    **kwargs: Any,
) -> Any:
    """Return the hub's response to a request about a Google Slides
    presentation, e.g., ``suffix="/export"``, made of the project's route,
    which reaches it through the Google account of whoever linked it to the
    project, or otherwise of the user's own.

    The user's own route is for a project the hub doesn't know, or a
    presentation nobody linked to it, and ``connect`` offers to connect
    their Google account there if it isn't.
    """
    import requests

    try:
        project = calkit.detect_project_name(wdir=wdir)
    except Exception:
        project = None
    request = getattr(calkit.hub, kind)
    if project is not None:
        try:
            return request(
                f"/projects/{project}/google/presentations/"
                f"{presentation_id}{suffix}",
                **kwargs,
            )
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code not in (403, 404):
                raise
    path = f"/user/google/presentations/{presentation_id}{suffix}"
    if connect:
        return get_hub_response(kind, path, **kwargs)
    return request(path, **kwargs)


def link_presentation(presentation_id: str) -> None:
    """Link a Google Slides presentation to the project on the hub, so
    everyone with access to the project reaches it through the user's
    Google account, and it's shared with them in Google.

    A project the hub doesn't know is left alone.
    """
    import requests

    try:
        project = calkit.detect_project_name()
    except Exception:
        return
    try:
        calkit.hub.post(
            f"/projects/{project}/google/presentations/{presentation_id}"
        )
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return
        warn(f"Failed to link the presentation to {project} on the hub: {e}")
    except Exception as e:
        warn(f"Failed to link the presentation to {project} on the hub: {e}")


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

    def get_modified_time(presentation_id: str, wdir: str) -> str:
        info = get_presentation_response(
            "get",
            presentation_id,
            wdir=wdir,
            connect=False,
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
            presentation_id: pool.submit(
                get_modified_time, presentation_id, next(iter(wdirs))
            )
            for presentation_id, wdirs in exporters.items()
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
    link_presentation(info["id"])
    if not no_commit:
        repo = calkit.git.get_repo()
        repo.git.add(["calkit.yaml", edit_time_path])
        repo.git.commit(
            ["calkit.yaml", edit_time_path, "-m", f"Add presentation {path}"]
        )
