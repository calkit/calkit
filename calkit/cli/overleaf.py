"""CLI for working with Overleaf."""

from __future__ import annotations

import os
import subprocess

import git
import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import raise_error, warn

overleaf_app = typer.Typer(no_args_is_help=True)


@overleaf_app.command(name="sync")
def sync(
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Run in dry run mode (don't apply changes).",
        ),
    ] = False,
):
    """Sync publications with Overleaf."""
    # Find all publications with Overleaf projects linked
    ck_info = calkit.load_calkit_info()
    pubs = ck_info.get("publications", [])
    repo = git.Repo()
    pubs = [p for p in pubs if p.get("overleaf", {}).get("project_id")]
    for pub in pubs:
        overleaf_project_id = pub["overleaf"]["project_id"]
        typer.echo(
            f"Syncing {pub['path']} with "
            f"Overleaf project ID {overleaf_project_id}"
        )
        wdir = pub["overleaf"].get("wdir")
        if wdir is None:
            raise_error(
                "No working directory defined for this publication; "
                "please set it in the publication's Overleaf config"
            )
        # Ensure we've cloned the Overleaf project
        overleaf_project_dir = os.path.join(
            ".calkit", "overleaf", overleaf_project_id
        )
        if not os.path.isdir(overleaf_project_dir):
            calkit_config = calkit.config.read()
            overleaf_token = calkit_config.overleaf_token
            if not overleaf_token:
                raise_error(
                    "Overleaf token not set; "
                    "Please set it using 'calkit config set overleaf_token'"
                )
            overleaf_clone_url = (
                f"https://git:{overleaf_token}@git.overleaf.com/"
                f"{overleaf_project_id}"
            )
            overleaf_repo = git.Repo.clone_from(overleaf_clone_url)
        else:
            overleaf_repo = git.Repo(overleaf_project_dir)
        # Pull the latest version in the Overleaf project
        typer.echo("Pulling the latest version from Overleaf")
        overleaf_repo.git.pull()
        last_sync_commit = pub["overleaf"].get("last_sync_commit")
        sync_paths = pub["overleaf"].get("sync_paths", [])
        if not sync_paths:
            warn("No sync paths defined in the publication's Overleaf config")
        elif last_sync_commit:
            # Compute a diff in the Overleaf project between HEAD and the last
            # sync
            diff = overleaf_repo.git.diff(
                [last_sync_commit, "HEAD", "--"] + sync_paths
            )
            # Ensure the diff ends with a new line
            if diff and not diff.endswith("\n"):
                diff += "\n"
            typer.echo("Diff:")
            typer.echo(diff)
            if diff:
                typer.echo("Applying to project repo")
                process = subprocess.run(
                    ["git", "apply", "--directory", wdir, "-"],
                    input=diff,
                    text=True,
                )
                if process.returncode != 0:
                    raise_error("Failed to apply diff")
            else:
                typer.echo("No changes to apply")
        else:
            # Simply copy in all files, TODO
            typer.echo(
                "No last sync commit defined; "
                "copying all files from Overleaf project"
            )
            pass
        # If there are changes, apply them to our local file(s)
        # Copy our versions into the Overleaf project and commit
        # TODO: Add option to run the pipeline after?
