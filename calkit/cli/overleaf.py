"""CLI for working with Overleaf."""

from __future__ import annotations

import os
import shutil
import subprocess

import git
import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import raise_error, warn

overleaf_app = typer.Typer(no_args_is_help=True)


@overleaf_app.command(name="sync")
def sync(
    no_commit: Annotated[
        bool,
        typer.Option(
            "--no-commit",
            help="Do not commit the changes.",
        ),
    ] = False,
):
    """Sync publications with Overleaf."""
    # TODO: We should probably ensure the pipeline isn't stale
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
        sync_paths_relative = [os.path.join(wdir, p) for p in sync_paths]
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
        # Stage the changes in the project repo
        repo.git.add(sync_paths_relative)
        if repo.git.diff("--staged", sync_paths_relative) and not no_commit:
            typer.echo("Committing changes to project repo")
            commit_message = (
                f"Sync {wdir} with Overleaf project {overleaf_project_id}"
            )
            repo.git.commit(
                *sync_paths_relative,
                "-m",
                commit_message,
            )
        # Copy our versions of sync and push paths into the Overleaf project
        push_paths = pub["overleaf"].get("push_paths", [])
        for push_path in sync_paths + push_paths:
            src = os.path.join(wdir, push_path)
            dst = os.path.join(overleaf_project_dir, push_path)
            if os.path.isdir(src):
                # Remove destination directory if it exists
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                # Copy the directory and its contents
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.isfile(src):
                # Copy the file
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
            else:
                raise_error(
                    f"Source path {src} does not exist; "
                    "please check your Overleaf config"
                )
                continue
        # Stage the changes in the Overleaf project
        overleaf_repo.git.add(sync_paths + push_paths)
        if (
            overleaf_repo.git.diff("--staged", sync_paths + push_paths)
            and not no_commit
        ):
            commit_message = "Sync with Calkit project"
            overleaf_repo.git.commit(
                *(sync_paths + push_paths),
                "-m",
                commit_message,
            )
            # TODO: We should probably always push and pull to we can
            # idempotently run this command
            typer.echo("Pushing changes to Overleaf")
            overleaf_repo.git.push()
        # Update the last sync commit
        last_overleaf_commit = overleaf_repo.head.commit.hexsha
        typer.echo(f"Updating last sync commit as {last_overleaf_commit}")
        pub["overleaf"]["last_sync_commit"] = last_overleaf_commit
        # TODO: Write last sync commit to our publication in calkit.yaml and
        # commit and push the changes
        # TODO: Add option to run the pipeline after?
