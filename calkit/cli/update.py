"""CLI for updating objects."""

from __future__ import annotations

import os
import zipfile
from datetime import datetime

import requests
import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import raise_error

update_app = typer.Typer(no_args_is_help=True)


@update_app.command(name="devcontainer")
def update_devcontainer(
    wdir: Annotated[
        str | None,
        typer.Option(
            "--wdir",
            help=(
                "Working directory. "
                "By default will run current working directory."
            ),
        ),
    ] = None,
):
    """Update a project's devcontainer to match the latest Calkit spec."""
    url = (
        "https://raw.githubusercontent.com/calkit/devcontainer/"
        "refs/heads/main/devcontainer.json"
    )
    typer.echo(f"Downloading {url}")
    resp = requests.get(url)
    out_dir = os.path.join(wdir or ".", ".devcontainer")
    os.makedirs(out_dir, exist_ok=True)
    out_fpath = os.path.join(out_dir, "devcontainer.json")
    typer.echo(f"Writing to {out_fpath}")
    with open(out_fpath, "w") as f:
        f.write(resp.text)


@update_app.command(name="release")
def update_release(
    name: Annotated[
        str | None, typer.Option("--name", "-n", help="Release name.")
    ] = None,
    use_latest: Annotated[
        bool, typer.Option("--latest", help="Update latest release.")
    ] = False,
    delete: Annotated[
        bool, typer.Option("--delete", help="Delete release.")
    ] = False,
    publish: Annotated[
        bool, typer.Option("--publish", help="Publish the release.")
    ] = False,
    reupload: Annotated[
        bool, typer.Option("--reupload", help="Reupload files.")
    ] = False,
):
    """Update a release."""
    if name is None and not use_latest:
        raise_error("Release name or --latest must be specified")
    if delete and (publish or reupload):
        raise_error("Cannot delete release if reuploading or publishing")
    ck_info = calkit.load_calkit_info()
    releases = ck_info.get("releases", {})
    if name is not None and name not in releases:
        raise_error(f"Release '{name}' does not exist")
    if use_latest:
        latest_name = None
        latest_date = None
        for release_name, release in releases.items():
            release_date = release.get("date")
            try:
                release_date = datetime.fromisoformat(release_date)
            except Exception:
                raise_error(
                    f"Release '{release_name}' has invalid date "
                    f"'{release_date}'"
                )
            if latest_date is None or release_date > latest_date:
                latest_name = release_name
                latest_date = release_date
        if latest_name is None:
            raise_error("No releases found")
        name = latest_name
    release = releases[name]
    publisher = release.get("publisher")
    if publisher is None:
        raise_error("Release does not have a publisher")
    record_id = release.get("record_id")
    if record_id is None:
        raise_error("Release has no record ID")
    if publish:
        try:
            calkit.invenio.post(
                f"/records/{record_id}/draft/actions/publish",
                service=publisher,
            )
        except Exception as e:
            raise_error(f"Failed to publish release: {e}")
    if delete:
        try:
            calkit.invenio.delete(
                f"/records/{record_id}/draft", service=publisher
            )
        except Exception as e:
            raise_error(f"Failed to delete release: {e}")
    if reupload:
        # Regenerate archive data and reupload
        path = release["path"]
        release_type = release["kind"]
        # TODO: Enable reuploading artifact releases
        if path != "." or release_type != "project":
            raise_error("Can only handle updating project releases")
        release_files_dir = f".calkit/releases/{name}/files"
        zip_path = release_files_dir + "/archive.zip"
        all_paths = calkit.releases.ls_files()
        typer.echo(f"Adding files to {zip_path}")
        with zipfile.ZipFile(zip_path, "w") as zipf:
            for fpath in all_paths:
                zipf.write(fpath)
        files = os.listdir(release_files_dir)
        for filename in files:
            typer.echo(f"Uploading {filename}")
            fpath = os.path.join(release_files_dir, filename)
            # First, initiate the file upload
            calkit.invenio.post(
                f"/records/{record_id}/draft/files",
                json=[{"key": filename}],
                service=publisher.lower(),  # type: ignore
            )
            # Then upload the file content
            with open(fpath, "rb") as f:
                file_data = f.read()
                resp = calkit.invenio.put(
                    f"/records/{record_id}/draft/files/{filename}/content",
                    headers={"Content-Type": "application/octet-stream"},
                    as_json=False,
                    service=publisher.lower(),  # type: ignore
                    data=file_data,
                )
                typer.echo(f"Status code: {resp.status_code}")
            # Commit the file
            calkit.invenio.post(
                f"/records/{record_id}/draft/files/{filename}/commit",
                service=publisher.lower(),  # type: ignore
            )
    # TODO: Add ability to update metadata
