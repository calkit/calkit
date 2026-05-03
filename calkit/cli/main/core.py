"""Core functionality in the main namespace of the CLI."""

from __future__ import annotations

import csv
import glob
import json
import logging
import os
import platform as _platform
import posixpath
import shutil
import subprocess
import sys
import time
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import dotenv
import git
import typer
from git.exc import InvalidGitRepositoryError
from typing_extensions import Annotated, Optional

import calkit
import calkit.dvc.zip
import calkit.matlab
import calkit.pipeline
from calkit import (
    AUTO_IGNORE_PATHS,
    AUTO_IGNORE_PREFIXES,
    AUTO_IGNORE_SUFFIXES,
    DVC_EXTENSIONS,
    DVC_SIZE_THRESH_BYTES,
)
from calkit.cli import (
    complete_stage_names,
    print_sep,
    raise_error,
    run_cmd,
    warn,
)
from calkit.cli.check import (
    check_app,
    check_conda_env,
    check_docker_env,
    check_environment,
    check_matlab_env,
    check_venv,
)
from calkit.cli.cloud import cloud_app
from calkit.cli.config import config_app
from calkit.cli.describe import describe_app
from calkit.cli.dev import dev_app
from calkit.cli.import_ import import_app
from calkit.cli.latex import latex_app
from calkit.cli.list import list_app
from calkit.cli.new import new_app
from calkit.cli.notebooks import notebooks_app
from calkit.cli.office import office_app
from calkit.cli.overleaf import overleaf_app
from calkit.cli.slurm import slurm_app
from calkit.cli.update import update_app
from calkit.dvc import get_dvc_repo, run_dvc_command
from calkit.environments import get_env_lock_fpath
from calkit.models import Procedure

app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=True,
    context_settings=dict(help_option_names=["-h", "--help"]),
    pretty_exceptions_show_locals=False,
)
app.add_typer(config_app, name="config", help="Configure Calkit.")
app.add_typer(new_app, name="new", help="Create a new Calkit object.")
app.add_typer(
    new_app,
    name="create",
    help="Create a new Calkit object (alias for 'new').",
)
app.add_typer(notebooks_app, name="nb", help="Work with Jupyter notebooks.")
app.add_typer(list_app, name="list", help="List Calkit objects.")
app.add_typer(describe_app, name="describe", help="Describe things.")
app.add_typer(import_app, name="import", help="Import objects.")
app.add_typer(office_app, name="office", help="Work with Microsoft Office.")
app.add_typer(update_app, name="update", help="Update objects.")
app.add_typer(check_app, name="check", help="Check things.")
app.add_typer(latex_app, name="latex", help="Work with LaTeX.")
app.add_typer(overleaf_app, name="overleaf", help="Interact with Overleaf.")
app.add_typer(cloud_app, name="cloud", help="Interact with a Calkit Cloud.")
app.add_typer(slurm_app, name="slurm", help="Work with SLURM.")
app.add_typer(dev_app, name="dev", help="Developer tools.", hidden=True)


def _to_shell_cmd(cmd: list[str]) -> str:
    """Join a command to be compatible with running at the shell.

    This is similar to ``shlex.join`` but works with Git Bash on Windows.
    """
    quoted_cmd = []
    for part in cmd:
        # Find quotes within quotes and escape them
        if " " in part or '"' in part[1:-1] or "'" in part[1:-1]:
            part = part.replace('"', r"\"")
            quoted_cmd.append(f'"{part}"')
        else:
            quoted_cmd.append(part)
    return " ".join(quoted_cmd)


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", help="Show version and exit."),
    ] = False,
):
    if version:
        typer.echo(f"Calkit {calkit.__version__}")
        raise typer.Exit()


@app.command(name="init")
def init(
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Force reinitializing DVC if already initialized.",
        ),
    ] = False,
):
    """Initialize the current working directory."""
    subprocess.run(["git", "init"])
    result = run_dvc_command(["init"] + (["--force"] if force else []))
    if result != 0:
        raise_error("Failed to initialize DVC")
    # Ensure autostage is enabled for DVC
    result = run_dvc_command(["config", "core.autostage", "true"])
    if result != 0:
        raise_error("Failed to configure DVC autostage")
    # Commit the newly created .dvc directory
    repo = git.Repo()
    repo.git.add(".dvc")
    repo.git.commit("-m", "Initialize DVC")
    # TODO: Initialize `calkit.yaml`
    # TODO: Initialize `dvc.yaml`
    # TODO: Add a sane .gitignore file
    # TODO: Add a sane LICENSE file?


@app.command(name="clone")
def clone(
    url: Annotated[str, typer.Argument(help="Repo URL.")],
    location: Annotated[
        str | None,
        typer.Argument(
            help="Location to clone to (default will be ./{repo_name})"
        ),
    ] = None,
    ssh: Annotated[
        bool, typer.Option("--ssh", help="Use SSH with Git.")
    ] = False,
    no_config_remote: Annotated[
        bool,
        typer.Option(
            "--no-config-remote",
            help="Do not automatically configure Calkit DVC remote.",
        ),
    ] = False,
    no_dvc_pull: Annotated[
        bool, typer.Option("--no-dvc-pull", help="Do not pull DVC objects.")
    ] = False,
    non_recursive: Annotated[
        bool,
        typer.Option(
            "--no-recursive", help="Do not recursively clone submodules."
        ),
    ] = False,
):
    """Clone or download a copy of a project."""
    # If the URL looks like just a project owner and name, fetch its repo URL
    # first
    if not url.startswith("https://") and not url.startswith("git@"):
        url_split = url.split("/")
        if len(url_split) != 2:
            raise_error(
                "Calkit projects must be specified like "
                "{owner_name}/{project_name}"
            )
        owner_name, project_name = url_split
        typer.echo("Fetching Git repo URL from the Calkit Cloud")
        try:
            project = calkit.cloud.get(
                f"/projects/{owner_name}/{project_name}"
            )
        except Exception as e:
            raise_error(f"Failed to fetch project information: {e}")
        url = project["git_repo_url"]
        if not url.endswith(".git"):
            url += ".git"
        if ssh:
            typer.echo("Converting URL to use with SSH")
            url = url.replace("https://github.com/", "git@github.com:")
    # Git clone
    cmd = ["git", "clone", url]
    if not non_recursive:
        cmd.append("--recursive")
    if location is not None:
        cmd.append(location)
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        raise_error("Failed to clone with Git")
    if location is None:
        location = url.split("/")[-1].removesuffix(".git")
    typer.echo(f"Moving into repo dir: {location}")
    os.chdir(location)
    # Setup auth for any Calkit remotes
    if not no_config_remote:
        remotes = calkit.dvc.get_remotes()
        for name, url in remotes.items():
            if name == "calkit" or name.startswith("calkit:"):
                typer.echo(f"Setting up authentication for DVC remote: {name}")
                calkit.dvc.set_remote_auth(remote_name=name)
    # DVC pull
    if not no_dvc_pull:
        try:
            result = run_dvc_command(["pull"])
            if result != 0:
                raise_error("Failed to pull from DVC remote(s)")
        except Exception as e:
            raise_error(f"Failed to pull from DVC remote(s): {e}")
        calkit.dvc.zip.sync_all(direction="to-workspace")


def _format_dvc_data_status(status: dict, zip_path_map: dict) -> str:
    """Format DVC data status, substituting zip paths with workspace paths."""
    reverse_zip = {zip_p: ws for ws, zip_p in zip_path_map.items()}
    color_map = {
        "added": typer.colors.GREEN,
        "modified": typer.colors.YELLOW,
        "deleted": typer.colors.RED,
        "renamed": typer.colors.CYAN,
    }

    def transform(path: str) -> str | None:
        if path in reverse_zip:
            return reverse_zip[path] + " (zipped)"
        return path

    def format_section(changes: dict, title: str) -> list[str]:
        entries = []
        for change_type, color in color_map.items():
            for item in changes.get(change_type, []):
                if isinstance(item, dict):
                    old = transform(item.get("old", ""))
                    new = transform(item.get("new", ""))
                    if old is not None and new is not None:
                        line = typer.style(
                            f"        {change_type}: {old} -> {new}", fg=color
                        )
                        entries.append(line)
                else:
                    display = transform(item)
                    if display is not None:
                        line = typer.style(
                            f"        {change_type}: {display}", fg=color
                        )
                        entries.append(line)
        if not entries:
            return []
        return [title] + entries

    lines = []
    lines += format_section(
        status.get("committed", {}), "DVC committed changes:"
    )
    lines += format_section(
        status.get("uncommitted", {}), "DVC uncommitted changes:"
    )
    not_in_cache = [transform(p) for p in status.get("not_in_cache", [])]
    not_in_cache = [p for p in not_in_cache if p is not None]
    if not_in_cache:
        lines.append(typer.style("Files not in cache:", bold=True))
        for p in not_in_cache:
            lines.append(f"        {p}")
    not_in_remote = [transform(p) for p in status.get("not_in_remote", [])]
    not_in_remote = [p for p in not_in_remote if p is not None]
    if not_in_remote:
        lines.append(typer.style("Files not in remote:", bold=True))
        for p in not_in_remote:
            lines.append(f"        {p}")
    if not lines:
        return "No changes.\n"
    return "\n".join(lines) + "\n"


@app.command(name="status")
def get_status(
    targets: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Optional targets to check status for. These may be "
                "pipeline stage names or repo paths."
            ),
        ),
    ] = None,
    categories: Annotated[
        list[str] | None,
        typer.Option(
            "--category",
            "-c",
            help=(
                "Status categories to show. By default, all categories are "
                "shown. Can be specified multiple times."
            ),
        ),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Output status as JSON.")
    ] = False,
):
    """View status (project, version control, and/or pipeline)."""
    ck_info = calkit.load_calkit_info()
    # If there's anything in ck_info and this isn't a Git repo, initialize one
    if ck_info:
        try:
            git.Repo()
        except InvalidGitRepositoryError:
            git.Repo.init()
    valid_categories = ["project", "git", "dvc", "pipeline"]
    if categories is not None:
        for category in categories:
            if category not in valid_categories:
                raise_error(
                    f"Invalid category: {category}. Valid categories are: "
                    f"{valid_categories}"
                )
    else:
        categories = valid_categories
    pipeline_status = None
    if "pipeline" in categories or "dvc" in categories:
        # Sync zips so the zip files reflect current workspace state before
        # reporting status
        calkit.dvc.zip.sync_all(direction="to-zip")
        pipeline_status = calkit.pipeline.get_status(
            ck_info=ck_info,
            targets=targets,
            check_environments=True,
            clean_notebooks=True,
            compile_to_dvc=True,
        )
        if pipeline_status.failed_environment_checks:
            warn(
                "Failed pipeline environment checks for: "
                + ", ".join(pipeline_status.failed_environment_checks)
            )
    if as_json:
        status_dict = {}
        if "project" in categories:
            status = calkit.get_latest_project_status()
            status_dict["project"] = (
                None
                if status is None
                else {
                    "status": status.status,
                    "message": status.message,
                    "timestamp": status.timestamp.isoformat(),
                }
            )
        if "git" in categories:
            try:
                repo = git.Repo()
                changed_files = calkit.git.get_changed_files(repo=repo)
                staged_files = calkit.git.get_staged_files(repo=repo)
                untracked_files = calkit.git.get_untracked_files(repo=repo)
                if targets:
                    target_prefixes = [
                        Path(target).as_posix().rstrip("/")
                        for target in targets
                    ]

                    def _matches_target(path: str) -> bool:
                        path = Path(path).as_posix()
                        return any(
                            path == prefix or path.startswith(prefix + "/")
                            for prefix in target_prefixes
                        )

                    changed_files = [
                        path for path in changed_files if _matches_target(path)
                    ]
                    staged_files = [
                        path for path in staged_files if _matches_target(path)
                    ]
                    untracked_files = [
                        path
                        for path in untracked_files
                        if _matches_target(path)
                    ]
                status_dict["git"] = {
                    "branch": None
                    if repo.head.is_detached
                    else repo.active_branch.name,
                    "is_dirty": repo.is_dirty(untracked_files=True),
                    "changed_files": changed_files,
                    "staged_files": staged_files,
                    "untracked_files": untracked_files,
                }
            except InvalidGitRepositoryError:
                status_dict["git"] = {"error": "Not a Git repository"}
        if "dvc" in categories:
            try:
                dvc_repo = calkit.dvc.get_dvc_repo()
                data_status = dvc_repo.data_status()
                if isinstance(data_status, dict):
                    data_status.pop("git", None)
                status_dict["dvc"] = data_status
            except Exception as e:
                status_dict["dvc"] = {"error": f"{e.__class__.__name__}: {e}"}
        if "pipeline" in categories or "dvc" in categories:
            if pipeline_status is None:
                status_dict["pipeline"] = None
            else:
                status_dict["pipeline"] = pipeline_status.model_dump(
                    mode="json"
                )
        print(json.dumps(status_dict, indent=2, default=str))
        return
    if "project" in categories:
        print_sep("Project")
        # Print latest status
        status = calkit.get_latest_project_status()
        if status is not None:
            ts = status.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            colors = {
                "in-progress": "blue",
                "on-hold": "yellow",
                "completed": "green",
            }
            status_txt = typer.style(
                status.status, fg=colors.get(status.status)
            )
            typer.echo(f"Current status: {status_txt} (updated {ts} UTC)")
        else:
            typer.echo(
                'Project status not set. Use "calkit new status" to update.'
            )
        typer.echo()
    if "git" in categories:
        print_sep("Git")
        git_cmd = ["git", "status"]
        if targets:
            git_cmd += ["--"] + targets
        run_cmd(git_cmd)
        typer.echo()
    if "dvc" in categories:
        print_sep("DVC")
        try:
            get_dvc_repo()
        except Exception:
            typer.echo("This is not a DVC repository.\n")
        else:
            zip_path_map = calkit.dvc.zip.get_zip_path_map()
            dvc_repo = get_dvc_repo()
            raw = dict(dvc_repo.data_status())
            raw.pop("git", None)
            typer.echo(_format_dvc_data_status(raw, zip_path_map))
    if "pipeline" in categories or "dvc" in categories:
        print_sep("Pipeline")
        # Nicely format the results from pipeline status
        if pipeline_status and pipeline_status.errors:
            warn("Pipeline status unavailable due to errors:")
            for error in pipeline_status.errors:
                warn(error)
            return
        if pipeline_status and not pipeline_status.has_pipeline:
            typer.echo("This project has no pipeline.")
            return
        elif pipeline_status and pipeline_status.is_stale:
            typer.echo("Stale stages:")
            for stage_name in pipeline_status.stale_stage_names:
                stale_stage = pipeline_status.stale_stages.get(stage_name)
                if stale_stage is None:
                    continue
                typer.echo(f"        {typer.style(stage_name, fg='yellow')}:")
                if stale_stage.modified_command:
                    typer.echo("          modified command")
                # Show stale outputs for this stage
                if stale_stage.stale_outputs:
                    typer.echo("          stale outputs:")
                    for output_path in stale_stage.stale_outputs:
                        typer.echo(f"            {output_path}")
                # Show modified outputs from this stage
                if stale_stage.modified_outputs:
                    typer.echo("          modified outputs:")
                    for output_path in stale_stage.modified_outputs:
                        typer.echo(f"            {output_path}")
                # Show modified inputs making the stage stale
                if stale_stage.modified_inputs:
                    typer.echo("          modified inputs:")
                    for input_path in stale_stage.modified_inputs:
                        typer.echo(f"            {input_path}")
        elif pipeline_status:
            typer.echo("Pipeline is up to date.")


@app.command(name="diff")
def diff(
    staged: Annotated[
        bool,
        typer.Option(
            "--staged", help="Show a diff from files staged with Git."
        ),
    ] = False,
):
    """Get a unified Git and DVC diff."""
    print_sep("Code (Git)")
    git_cmd = ["git", "diff"]
    if staged:
        git_cmd.append("--staged")
    run_cmd(git_cmd)
    print_sep("Pipeline (DVC)")
    run_dvc_command(["diff"])


def _get_pipeline_output_storage_map() -> dict[str, str]:
    """Get a map of pipeline output paths to their explicitly-set storage.

    Only outputs with an explicitly-set ``storage`` key in ``calkit.yaml``
    are included so that default-DVC outputs still go through auto-detection.

    Returns
    -------
    dict[str, str]
        Mapping of posix file path to storage type, e.g.
        ``{"figures/plot.png": "git", "data/archive": "dvc-zip"}``.
        Plain string outputs (no explicit ``storage`` key) are not included.
    """
    try:
        ck_info = calkit.load_calkit_info()
    except Exception:
        return {}
    pipeline = ck_info.get("pipeline", {})
    if not pipeline:
        return {}
    stages = pipeline.get("stages", {})
    result: dict[str, str] = {}
    for stage in stages.values():
        if not isinstance(stage, dict):
            continue
        for out in stage.get("outputs", []):
            if isinstance(out, dict) and "path" in out and "storage" in out:
                result[out["path"]] = out["storage"]
    return result


@app.command(name="add")
def add(
    paths: list[str],
    commit_message: Annotated[
        str | None,
        typer.Option(
            "-m",
            "--commit-message",
            help="Automatically commit and use this as a message.",
        ),
    ] = None,
    auto_commit_message: Annotated[
        bool,
        typer.Option(
            "--auto-message",
            "-M",
            help="Commit with an automatically-generated message.",
        ),
    ] = False,
    disable_auto_ignore: Annotated[
        bool, typer.Option("--no-auto-ignore", help="Disable auto-ignore.")
    ] = False,
    push_commit: Annotated[
        bool, typer.Option("--push", help="Push after committing.")
    ] = False,
    to: Annotated[
        str | None,
        typer.Option(
            "--to",
            "-t",
            help="System with which to add (git, dvc, or dvc-zip).",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "--dry",
            help="Show what would be added without actually adding it.",
        ),
    ] = False,
):
    """Add paths to the repo.

    Code will be added to Git and data will be added to DVC.

    Note: This will enable the 'autostage' feature of DVC, automatically
    adding any .dvc files to Git when adding to DVC.
    """
    import dvc.repo
    from dvc.exceptions import NotDvcRepoError

    if dry_run:
        typer.echo("Dry run: No files will be added")
    if auto_commit_message:
        if commit_message is not None:
            raise_error(
                "Commit message should not be provided if using "
                "automatic message"
            )
        if "." in paths:
            raise_error("Cannot auto-generate commit message for '.'")
        if len(paths) > 1:
            raise_error(
                "Cannot auto-generate commit message for more than one path"
            )
    if to is not None and to not in ["git", "dvc", "dvc-zip"]:
        raise_error(f"Invalid option for 'to': {to}")
    try:
        repo = git.Repo()
    except InvalidGitRepositoryError:
        # Prompt user if they want to run git init here
        warn("Current directory is not a Git repo")
        auto_init = typer.confirm(
            "Do you want to initialize the current directory with Git?",
            default=False,
        )
        if auto_init:
            subprocess.check_call(["git", "init"])
        else:
            raise_error("Not currently in a Git repo; run `calkit init` first")
        repo = git.Repo()
    try:
        dvc_repo = get_dvc_repo()
    except NotDvcRepoError:
        if dry_run:
            dvc_repo = None
            typer.echo(
                "This is not a DVC repository; would initialize DVC here"
            )
        else:
            warn("DVC not initialized yet; initializing")
            dvc_repo = dvc.repo.Repo.init()
    if not dry_run:
        # Ensure autostage is enabled for DVC
        run_dvc_command(
            [
                "config",
                "core.autostage",
                "true",
            ]
        )
        repo.git.add(".dvc/config")
    dvc_paths = [] if dvc_repo is None else calkit.dvc.list_paths()
    untracked_git_files = repo.untracked_files
    if auto_commit_message:
        # See if this path is in the repo already
        if paths[0] in dvc_paths or repo.git.ls_files(paths[0]):
            commit_message = f"Update {paths[0]}"
        else:
            commit_message = f"Add {paths[0]}"
    if to is not None:
        if dry_run:
            for path in paths:
                typer.echo(f"Would add {path} to {to}")
        elif to == "git":
            subprocess.call(["git", "add"] + paths)
        elif to == "dvc":
            run_dvc_command(["add"] + paths)
        elif to == "dvc-zip":
            for path in paths:
                typer.echo(f"Adding {path} as a DVC zip")
                calkit.dvc.zip.add(path)
        else:
            raise_error(f"Invalid option for 'to': {to}")
    else:
        if "." in paths:
            paths.remove(".")
            if dvc_repo is not None:
                dvc_status = dvc_repo.data_status()
                for dvc_uncommitted in dvc_status["uncommitted"].get(
                    "modified", []
                ):
                    if os.path.exists(dvc_uncommitted):
                        if dry_run:
                            typer.echo(
                                f"Would commit {dvc_uncommitted} to DVC"
                            )
                        else:
                            typer.echo(f"Adding {dvc_uncommitted} to DVC")
                            dvc_repo.commit(dvc_uncommitted, force=True)
                    else:
                        warn(
                            f"DVC uncommitted '{dvc_uncommitted}' does not "
                            "exist; skipping"
                        )
            if not disable_auto_ignore:
                for untracked_file in untracked_git_files:
                    if (
                        any(
                            [
                                untracked_file.endswith(suffix)
                                for suffix in AUTO_IGNORE_SUFFIXES
                            ]
                        )
                        or any(
                            [
                                untracked_file.startswith(prefix)
                                for prefix in AUTO_IGNORE_PREFIXES
                            ]
                        )
                        or untracked_file in AUTO_IGNORE_PATHS
                    ):
                        if dry_run:
                            typer.echo(f"Would ignore {untracked_file}")
                        else:
                            typer.echo(
                                f"Automatically ignoring {untracked_file}"
                            )
                            with open(".gitignore", "a") as f:
                                f.write("\n" + untracked_file + "\n")
                            if ".gitignore" not in paths:
                                paths.append(".gitignore")
            # TODO: Figure out if we should group large folders for dvc
            # Now add untracked files automatically
            for untracked_file in repo.untracked_files:
                paths.append(untracked_file)
            # Now add changed files
            for changed_file in [
                d.a_path for d in repo.index.diff(None) if d.a_path is not None
            ]:
                paths.append(changed_file)
        zip_path_map = calkit.dvc.zip.get_zip_path_map()
        pipeline_output_storage = _get_pipeline_output_storage_map()
        for path in paths:
            # Check if this path is already registered as a zip
            posix_path = Path(path).as_posix()
            if posix_path in zip_path_map:
                if dry_run:
                    typer.echo(f"Would add {path} via DVC zip")
                else:
                    typer.echo(f"Adding {path} via DVC zip")
                    calkit.dvc.zip.add(path)
                continue
            # Detect if this file should be tracked with Git or DVC
            # First see if it's in Git
            if repo.git.ls_files(path):
                if dry_run:
                    typer.echo(
                        f"Would add {path} to Git (already tracked in repo)"
                    )
                else:
                    typer.echo(
                        f"Adding {path} to Git since it's already in the repo"
                    )
                    subprocess.call(["git", "add", path])
            elif path in dvc_paths:
                if dry_run:
                    typer.echo(
                        f"Would add {path} to DVC (already tracked with DVC)"
                    )
                else:
                    typer.echo(
                        f"Adding {path} to DVC since it's already tracked "
                        "with DVC"
                    )
                    run_dvc_command(["add", path])
            elif posix_path in pipeline_output_storage:
                # Respect storage explicitly set in the pipeline definition
                pipeline_storage = pipeline_output_storage[posix_path]
                if pipeline_storage == "git":
                    if dry_run:
                        typer.echo(
                            f"Would add {path} to Git "
                            "(pipeline output storage)"
                        )
                    else:
                        typer.echo(
                            f"Adding {path} to Git per pipeline output storage"
                        )
                        subprocess.call(["git", "add", path])
                elif pipeline_storage == "dvc-zip":
                    if dry_run:
                        typer.echo(
                            f"Would add {path} as a DVC zip "
                            "(pipeline output storage)"
                        )
                    else:
                        typer.echo(
                            f"Adding {path} as a DVC zip per pipeline output "
                            "storage"
                        )
                        calkit.dvc.zip.add(path)
                else:
                    if dry_run:
                        typer.echo(
                            f"Would add {path} to DVC "
                            "(pipeline output storage)"
                        )
                    else:
                        typer.echo(
                            f"Adding {path} to DVC per pipeline output storage"
                        )
                        run_dvc_command(["add", path])
            elif os.path.splitext(path)[-1] in DVC_EXTENSIONS:
                if dry_run:
                    typer.echo(f"Would add {path} to DVC (per extension)")
                else:
                    typer.echo(f"Adding {path} to DVC per its extension")
                    run_dvc_command(["add", path])
            elif calkit.dvc.zip.is_zip_candidate(path):
                if dry_run:
                    typer.echo(
                        f"Would add {path} as a DVC zip "
                        "(large directory of small files)"
                    )
                else:
                    typer.echo(
                        f"Adding {path} as a DVC zip "
                        "(large directory of small files)"
                    )
                    calkit.dvc.zip.add(path)
            elif calkit.get_size(path) > DVC_SIZE_THRESH_BYTES:
                if dry_run:
                    typer.echo(f"Would add {path} to DVC (>1 MB)")
                else:
                    typer.echo(
                        f"Adding {path} to DVC since it's greater than 1 MB"
                    )
                    run_dvc_command(["add", path])
            else:
                if dry_run:
                    typer.echo(f"Would add {path} to Git")
                else:
                    typer.echo(f"Adding {path} to Git")
                    subprocess.call(["git", "add", path])
    if not dry_run:
        if commit_message is not None:
            subprocess.call(["git", "commit", "-m", commit_message])
        if push_commit:
            push()
    else:
        if commit_message is not None:
            typer.echo(f"Would commit with message: {commit_message}")
        if push_commit:
            typer.echo("Would push to Git and DVC after committing")


@app.command(name="commit")
def commit(
    all: Annotated[
        Optional[bool],
        typer.Option(
            "--all", "-a", help="Automatically stage all changed files."
        ),
    ] = False,
    message: Annotated[
        Optional[str], typer.Option("--message", "-m", help="Commit message.")
    ] = None,
    push_commit: Annotated[
        bool,
        typer.Option(
            "--push", help="Push to both Git and DVC after committing."
        ),
    ] = False,
):
    """Commit a change to the repo."""
    if message is None:
        typer.echo("Please provide a message describing the changes.")
        typer.echo("Example: Update y-label in scripts/plot-data.py")
        message = typer.prompt("Message")
    cmd = ["git", "commit"]
    if all:
        cmd.append("-a")
    if message:
        cmd += ["-m", message]
    subprocess.call(cmd)
    if push_commit:
        push()


@app.command(name="save")
def save(
    paths: Annotated[
        Optional[list[str]],
        typer.Argument(
            help=(
                "Paths to add and commit. If not provided, will default to "
                "any changed files that have been added previously."
            ),
        ),
    ] = None,
    save_all: Annotated[
        Optional[bool],
        typer.Option(
            "--all",
            "-a",
            help=("Save all, automatically handling staging and ignoring."),
        ),
    ] = False,
    message: Annotated[
        Optional[str], typer.Option("--message", "-m", help="Commit message.")
    ] = None,
    auto_commit_message: Annotated[
        bool,
        typer.Option(
            "--auto-message",
            "-M",
            help="Commit with an automatically-generated message.",
        ),
    ] = False,
    to: Annotated[
        str | None,
        typer.Option(
            "--to", "-t", help="System with which to add (git or dvc)."
        ),
    ] = None,
    no_push: Annotated[
        bool,
        typer.Option(
            "--no-push", help="Do not push to Git and DVC after committing."
        ),
    ] = False,
    git_push_args: Annotated[
        list[str],
        typer.Option(
            "--git-push",
            help="Additional Git args to pass when pushing.",
        ),
    ] = [],
    dvc_push_args: Annotated[
        list[str],
        typer.Option(
            "--dvc-push",
            help="Additional DVC args to pass when pushing.",
        ),
    ] = [],
    no_recursive: Annotated[
        bool, typer.Option("--no-recursive", help="Do not push to submodules.")
    ] = False,
    sync_overleaf: Annotated[
        bool,
        typer.Option(
            "--overleaf", "-O", help="Sync with Overleaf after saving."
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output.")
    ] = False,
):
    """Save paths by committing and pushing.

    This is essentially git/dvc add, commit, and push in one step.
    """
    if not paths and not save_all:
        raise_error("Paths must be provided if not using --all")
    if paths is not None:
        add(paths, to=to)
    elif save_all:
        add(paths=["."], to=to)
    if auto_commit_message and message is None:
        staged_files = calkit.git.get_staged_files_with_status()
        if verbose:
            typer.echo(
                f"Generating commit message for staged files: {staged_files}"
            )
        if not staged_files:
            typer.echo("No changes to commit; exiting")
            raise typer.Exit(0)
        if len(staged_files) != 1:
            raise_error(
                "Automatic commit messages can only be generated when "
                f"changing one file (changed: {staged_files})"
            )
        dvc_paths = calkit.dvc.list_paths()
        # See if this path is in the repo already
        staged_file = staged_files[0]["path"]
        status = staged_files[0]["status"]
        if staged_file in dvc_paths or status == "M":
            message = f"Update {staged_file}"
        else:
            message = f"Add {staged_file}"
    if message is None:
        typer.echo("No message provided; entering interactive mode")
        typer.echo("Creating a commit including the following paths:")
        for path in calkit.git.get_staged_files():
            typer.echo(f"- {path}")
        typer.echo("Please provide a message describing the changes.")
        typer.echo("Example: Add new data to data/raw")
        message = typer.prompt("Message")
    # Figure out if we have any DVC files in this commit, and if not, we can
    # skip pushing to DVC
    staged_files = calkit.git.get_staged_files()
    if not staged_files:
        typer.echo("No changes to commit; exiting")
        return
    any_dvc = any(
        [path == "dvc.lock" or path.endswith(".dvc") for path in staged_files]
    )
    commit(all=True if paths is None else False, message=message)
    if not no_push:
        if verbose and not any_dvc:
            typer.echo("Not pushing to DVC since no DVC files were staged")
        push(
            no_dvc=not any_dvc,
            git_args=git_push_args,
            dvc_args=dvc_push_args,
            no_recursive=no_recursive,
        )
    if sync_overleaf:
        from calkit.cli.overleaf import sync as overleaf_sync

        overleaf_sync(verbose=verbose, no_push=no_push)


@app.command(name="pull")
def pull(
    no_check_auth: Annotated[bool, typer.Option("--no-check-auth")] = False,
    git_args: Annotated[
        list[str],
        typer.Option("--git-arg", help="Additional Git args."),
    ] = [],
    dvc_args: Annotated[
        list[str],
        typer.Option("--dvc-arg", help="Additional DVC args."),
    ] = [],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Force pull, potentially overwriting local changes.",
        ),
    ] = False,
    no_recursive: Annotated[
        bool,
        typer.Option(
            "--no-recursive", help="Do not recursively pull from submodules."
        ),
    ] = False,
):
    """Pull with both Git and DVC."""
    typer.echo("Git pulling")
    if force:
        if "-f" not in git_args and "--force" not in git_args:
            git_args.append("-f")
        if "-f" not in dvc_args and "--force" not in dvc_args:
            dvc_args.append("-f")
    try:
        git_cmd = ["git", "pull"]
        if not no_recursive and "--recurse-submodules" not in git_args:
            git_cmd.append("--recurse-submodules")
        subprocess.check_call(git_cmd + git_args)
    except subprocess.CalledProcessError:
        raise_error("Git pull failed")
    typer.echo("DVC pulling")
    if not no_check_auth:
        # Check that our dvc remotes all have our DVC token set for them
        remotes = calkit.dvc.get_remotes()
        for name, url in remotes.items():
            if calkit.dvc.detect_calkit_remote_type(name, url) == "http":
                typer.echo(f"Checking authentication for DVC remote: {name}")
                calkit.dvc.set_remote_auth(remote_name=name)
    result = run_dvc_command(["pull"] + dvc_args)
    if result != 0:
        raise_error("DVC pull failed")
    calkit.dvc.zip.sync_all(direction="to-workspace")


@app.command(name="push")
def push(
    no_check_auth: Annotated[bool, typer.Option("--no-check-auth")] = False,
    no_dvc: Annotated[bool, typer.Option("--no-dvc")] = False,
    no_git: Annotated[bool, typer.Option("--no-git")] = False,
    git_args: Annotated[
        list[str],
        typer.Option("--git-arg", help="Additional Git args."),
    ] = [],
    dvc_args: Annotated[
        list[str],
        typer.Option("--dvc-arg", help="Additional DVC args."),
    ] = [],
    no_recursive: Annotated[
        bool, typer.Option("--no-recursive", help="Do not push to submodules.")
    ] = False,
):
    """Push with both Git and DVC."""
    if not no_dvc:
        remotes = calkit.dvc.get_remotes()
        if not no_check_auth:
            # Check that our dvc remotes all have our DVC token set for them
            for name, url in remotes.items():
                if calkit.dvc.detect_calkit_remote_type(name, url) == "http":
                    typer.echo(
                        f"Checking authentication for DVC remote: {name}"
                    )
                    calkit.dvc.set_remote_auth(remote_name=name)
        if remotes:
            typer.echo("Pushing to DVC remote")
            result = run_dvc_command(["push"] + dvc_args)
            if result != 0:
                raise_error("DVC push failed")
        else:
            warn("No DVC remotes configured; skipping DVC push")
    if not no_git:
        typer.echo("Pushing to Git remote")
        try:
            git_cmd = ["git", "push"]
            if not no_recursive and "--recurse-submodules" not in git_args:
                git_cmd.append("--recurse-submodules=on-demand")
            subprocess.check_call(git_cmd + git_args)
        except subprocess.CalledProcessError:
            raise_error("Git push failed")


@app.command(name="sync")
def sync(
    no_check_auth: Annotated[bool, typer.Option("--no-check-auth")] = False,
):
    """Sync the project repo by pulling and then pushing."""
    # TODO: Walk users through merge conflicts if they arise
    pull(no_check_auth=no_check_auth)
    push(no_check_auth=no_check_auth)


@app.command(name="ignore")
def ignore(
    path: Annotated[str, typer.Argument(help="Path to ignore.")],
    no_commit: Annotated[
        bool,
        typer.Option(
            "--no-commit", help="Do not commit changes to .gitignore."
        ),
    ] = False,
):
    """Ignore a file, i.e., keep it out of version control."""
    repo = git.Repo()
    # Ensure path makes it into .gitignore as a POSIX path
    path = Path(path).as_posix()
    if repo.ignored(path):
        typer.echo(f"{path} is already ignored")
        return
    typer.echo(f"Adding '{path}' to .gitignore")
    txt = "\n" + path + "\n"
    with open(".gitignore", "a") as f:
        f.write(txt)
    if not no_commit:
        repo = git.Repo()
        repo.git.reset()
        repo.git.add(".gitignore")
        if calkit.git.get_staged_files():
            repo.git.commit(["-m", f"Ignore {path}"])


@app.command(name="local-server")
def run_local_server():
    """Run the local server to interact over HTTP."""
    import uvicorn

    uvicorn.run(
        "calkit.server:app",
        port=8866,
        host="localhost",
        reload=True,
        reload_dirs=[os.path.dirname(os.path.dirname(__file__))],
    )


def _stage_run_info_from_log_content(log_content: str) -> dict:
    def add_stage_info(stage_name: str, key: str, value: str | datetime):
        if isinstance(value, datetime):
            # Convert datetime to ISO format for consistency
            value = value.isoformat()
        if stage_name not in res:
            res[stage_name] = {}
        res[stage_name][key] = value

    res = {}
    errored_timestamp = None
    lines = log_content.splitlines()
    current_stage_name = None
    current_stage_status = None
    for line in lines:
        # Log lines should be able to be split into timestamp, type, message
        ls = line.split(" -", maxsplit=2)
        if len(ls) < 2:
            continue
        timestamp, log_type, message = (
            ls[0].strip(),
            ls[1].strip(),
            ls[2].strip() if len(ls) > 2 else "",
        )
        try:
            timestamp = datetime.fromisoformat(timestamp)
        except ValueError:
            # If the timestamp is not in ISO format, skip this line
            continue
        # If we hit an error, the logs should print a traceback and end
        if log_type == "ERROR":
            errored_timestamp = timestamp
            break
        if message.startswith("Running stage "):
            if (
                current_stage_name is not None
                and current_stage_status == "running"
            ):
                # If we were already running a stage, add its end time
                add_stage_info(current_stage_name, "end_time", timestamp)
                add_stage_info(current_stage_name, "status", "completed")
            # This is a stage run
            current_stage_name = (
                message.removeprefix("Running stage ")
                .replace("'", "")
                .replace(":", "")
            )
            current_stage_status = "running"
            add_stage_info(current_stage_name, "start_time", timestamp)
        elif message.startswith("Stage ") and "skipping" in message:
            if (
                current_stage_name is not None
                and current_stage_status == "running"
            ):
                # If we were already running a stage, add its end time
                add_stage_info(current_stage_name, "end_time", timestamp)
                add_stage_info(current_stage_name, "status", "completed")
            current_stage_name = message.removeprefix("Stage '").split("'")[0]
            current_stage_status = "skipped"
            add_stage_info(current_stage_name, "start_time", timestamp)
            add_stage_info(current_stage_name, "end_time", timestamp)
            add_stage_info(current_stage_name, "status", current_stage_status)
    if errored_timestamp is not None:
        # Figure out which stage failed
        for line in lines[-1::-1]:
            if line.startswith(
                "dvc.exceptions.ReproductionError: failed to reproduce "
            ):
                stage_name = (
                    line.strip()
                    .removeprefix(
                        "dvc.exceptions.ReproductionError: failed to reproduce "
                    )
                    .replace("'", "")
                )
                add_stage_info(stage_name, "end_time", errored_timestamp)
                add_stage_info(stage_name, "status", "failed")
                break
    return res


@app.command(name="run")
def run(
    targets: Annotated[
        list[str] | None,
        typer.Argument(
            help="Stages to run.",
            shell_complete=complete_stage_names,
        ),
    ] = None,
    quiet: Annotated[
        bool, typer.Option("-q", "--quiet", help="Be quiet.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Print verbose output.")
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "-f",
            "--force",
            help="Run even if stages or inputs have not changed.",
        ),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option(
            "-i",
            "--interactive",
            help="Ask for confirmation before running each stage.",
        ),
    ] = False,
    single_item: Annotated[
        bool,
        typer.Option(
            "-s",
            "--single-item",
            help="Run only a single stage without any dependents.",
        ),
    ] = False,
    pipeline: Annotated[
        Optional[str], typer.Option("-p", "--pipeline")
    ] = None,
    all_pipelines: Annotated[
        bool,
        typer.Option(
            "-P", "--all-pipelines", help="Run all pipelines in the repo."
        ),
    ] = False,
    recursive: Annotated[
        bool,
        typer.Option(
            "-R", "--recursive", help="Run pipelines in subdirectories."
        ),
    ] = False,
    downstream: Annotated[
        Optional[list[str]],
        typer.Option(
            "--downstream",
            help="Start from the specified stage and run all downstream.",
            shell_complete=complete_stage_names,
        ),
    ] = None,
    force_downstream: Annotated[
        bool,
        typer.Option(
            "--force-downstream",
            help=(
                "Force downstream stages to run even if "
                "they are still up-to-date."
            ),
        ),
    ] = False,
    pull: Annotated[
        bool,
        typer.Option("--pull", help="Try automatically pulling missing data."),
    ] = False,
    allow_missing: Annotated[
        bool,
        typer.Option("--allow-missing", help="Skip stages with missing data."),
    ] = False,
    dry: Annotated[
        bool,
        typer.Option(
            "--dry",
            "--dry-run",
            help="Only print commands that would execute.",
        ),
    ] = False,
    keep_going: Annotated[
        bool,
        typer.Option(
            "--keep-going",
            "-k",
            help=(
                "Continue executing, skipping stages with failed "
                "inputs from other stages."
            ),
        ),
    ] = False,
    ignore_errors: Annotated[
        bool,
        typer.Option("--ignore-errors", help="Ignore errors from stages."),
    ] = False,
    glob: Annotated[
        bool,
        typer.Option("--glob", help="Match stages with glob-style patterns."),
    ] = False,
    no_commit: Annotated[
        bool, typer.Option("--no-commit", help="Do not save to the run cache.")
    ] = False,
    no_run_cache: Annotated[
        bool, typer.Option("--no-run-cache", help="Ignore the run cache.")
    ] = False,
    save_logs: Annotated[
        bool,
        typer.Option(
            "--log", "-l", help="Log the run and system information."
        ),
    ] = False,
    save_after_run: Annotated[
        bool,
        typer.Option("--save", "-S", help="Save the project after running."),
    ] = False,
    save_message: Annotated[
        str | None,
        typer.Option(
            "--save-message", "-m", help="Commit message for saving."
        ),
    ] = None,
    target_inputs: Annotated[
        list[str],
        typer.Option(
            "--input",
            "--dep",
            help="Run stages that depend on given input dependency path.",
        ),
    ] = [],
    target_outputs: Annotated[
        list[str],
        typer.Option(
            "--output",
            "--out",
            help="Run stages that produce the given output path.",
        ),
    ] = [],
    sync_overleaf: Annotated[
        bool,
        typer.Option(
            "--overleaf",
            "-O",
            help="Sync with Overleaf before and after running.",
        ),
    ] = False,
) -> dict:
    """Check dependencies and run the pipeline."""
    import dvc.log
    import dvc.repo
    import dvc.repo.reproduce
    import dvc.ui
    from dvc.cli import main as dvc_cli_main

    import calkit.dvc.zip
    import calkit.environments
    import calkit.pipeline
    from calkit.cli.overleaf import sync as overleaf_sync

    if (target_inputs or target_outputs) and targets:
        raise_error("Cannot specify both targets and inputs")
    os.environ["CALKIT_PIPELINE_RUNNING"] = "1"
    dotenv.load_dotenv(dotenv_path=".env", verbose=verbose)
    ck_info = calkit.load_calkit_info()
    # Ensure Git is initialized so DVC can be used
    try:
        git.Repo()
    except InvalidGitRepositoryError:
        if not quiet:
            typer.echo("Initializing Git repo")
        try:
            subprocess.check_call(["git", "init"])
        except subprocess.CalledProcessError:
            raise_error("Failed to initialize Git repo")
    # Set env vars
    calkit.set_env_vars(ck_info=ck_info)
    # Clean all notebooks in the pipeline
    try:
        calkit.notebooks.clean_all_in_pipeline(ck_info=ck_info)
    except Exception as e:
        raise_error(f"Failed to clean notebooks: {e.__class__.__name__}: {e}")
    if not quiet:
        typer.echo("Getting system information")
    # Get system information
    system_info = calkit.get_system_info()
    if save_logs:
        # Save the system to .calkit/systems
        if verbose:
            typer.echo("Saving system information:")
            typer.echo(system_info)
        sysinfo_fpath = os.path.join(
            ".calkit", "systems", system_info["id"] + ".json"
        )
        os.makedirs(os.path.dirname(sysinfo_fpath), exist_ok=True)
        with open(sysinfo_fpath, "w") as f:
            json.dump(system_info, f, indent=2)
    # First check any system-level dependencies exist
    if not quiet:
        typer.echo("Checking system-level dependencies")
    try:
        calkit.check_system_deps(ck_info=ck_info, system_info=system_info)
    except Exception as e:
        os.environ.pop("CALKIT_PIPELINE_RUNNING", None)
        raise_error(str(e))
    # Check all environments in the pipeline (with caching)
    # If any failed, warn the user that we might have problems running
    typer.echo("Checking environments")
    env_check_results = calkit.environments.check_all_in_pipeline(
        ck_info=ck_info, targets=targets, force=force
    )
    for env_name, result in env_check_results.items():
        if verbose:
            typer.echo(f"{env_name}: {result}")
        failed = not result.get("success", False)
        if failed:
            warn(f"Failed to check environment '{env_name}'")
    # If specified, perform initial Overleaf sync
    if sync_overleaf:
        overleaf_sync(no_commit=False, no_push=True, verbose=verbose)
    # Compile the DVC pipeline
    dvc_stages = None
    if ck_info.get("pipeline", {}):
        if not quiet:
            typer.echo("Compiling DVC pipeline")
        try:
            dvc_stages = calkit.pipeline.to_dvc(ck_info=ck_info, write=True)
        except Exception as e:
            os.environ.pop("CALKIT_PIPELINE_RUNNING", None)
            raise_error(f"Pipeline compilation failed: {e}")
    # Initialize DVC repo if necessary
    try:
        get_dvc_repo()
    except Exception:
        if not quiet:
            typer.echo("Initializing DVC repo")
        result = run_dvc_command(["init"])
        if result != 0:
            raise_error("Failed to initialize DVC repo")
    # Convert deps into target stage names
    # TODO: This could probably be merged back upstream into DVC
    if dvc_stages is None:
        if os.path.exists("dvc.yaml"):
            with open("dvc.yaml") as f:
                dvc_stages = calkit.ryaml.load(f).get("stages", {})
        else:
            dvc_stages = {}
    if target_inputs or target_outputs:
        targets = []
        input_abs_paths = [os.path.abspath(dep) for dep in target_inputs]
        output_abs_paths = [os.path.abspath(out) for out in target_outputs]
        for dvc_stage_name, dvc_stage in dvc_stages.items():
            stage_deps = dvc_stage.get("deps", [])
            for stage_dep in stage_deps:
                # Check absolute path equality
                abs_stage_dep = os.path.abspath(stage_dep)
                if abs_stage_dep in input_abs_paths:
                    if dvc_stage_name not in targets:
                        typer.echo(
                            f"Detected stage target {dvc_stage_name} "
                            f"from input {stage_dep}"
                        )
                        targets.append(dvc_stage_name)
            stage_outs = dvc_stage.get("outs", [])
            for stage_out in stage_outs:
                if isinstance(stage_out, str):
                    abs_stage_out = os.path.abspath(stage_out)
                elif isinstance(stage_out, dict):
                    abs_stage_out = os.path.abspath(list(stage_out.keys())[0])
                else:
                    raise_error(f"Malformed output in stage: {dvc_stage_name}")
                if abs_stage_out in output_abs_paths:
                    if dvc_stage_name not in targets:
                        typer.echo(
                            f"Detected stage target {dvc_stage_name} "
                            f"from output {stage_out}"
                        )
                        targets.append(dvc_stage_name)
        if not targets:
            raise_error("No stages found to run")
    if save_logs:
        # Get status of Git repo before running
        repo = git.Repo()
        git_rev = repo.head.commit.hexsha
        try:
            git_branch = repo.active_branch.name
        except TypeError:
            # If no branch is checked out, we are in a detached HEAD state
            git_branch = None
        git_changed_files_before = calkit.git.get_changed_files(repo=repo)
        git_staged_files_before = calkit.git.get_staged_files(repo=repo)
        git_untracked_files_before = calkit.git.get_untracked_files(repo=repo)
        # Get status of DVC repo before running
        dvc_repo = get_dvc_repo()
        dvc_status_before = dvc_repo.status()
        dvc_data_status_before = dvc_repo.data_status()
        dvc_data_status_before.pop("git", None)  # Remove git status
    if targets is None:
        targets = []
    args = deepcopy(targets)
    # Extract any boolean args
    for name in [
        "quiet",
        "verbose",
        "force",
        "interactive",
        "single-item",
        "all-pipelines",
        "recursive",
        "pull",
        "allow-missing",
        "dry",
        "keep-going",
        "ignore-errors",
        "force-downstream",
        "glob",
        "no-commit",
        "no-run-cache",
    ]:
        if locals()[name.replace("-", "_")]:
            args.append("--" + name)
    if pipeline is not None:
        args += ["--pipeline", pipeline]
    if downstream is not None:
        args.append("--downstream")
        args += downstream
    start_time_no_tz = calkit.utcnow(remove_tz=True)
    start_time = calkit.utcnow(remove_tz=False)
    run_id = uuid.uuid4().hex
    # Always log output, but only save systems/run data if specified
    log_fpath = os.path.join(
        ".calkit",
        "logs",
        start_time_no_tz.isoformat(timespec="seconds").replace(":", "-")
        + "-"
        + run_id
        + ".log",
    )
    if verbose:
        typer.echo(f"Starting run ID: {run_id}")
        typer.echo(f"Saving logs to {log_fpath}")
    os.makedirs(os.path.dirname(log_fpath), exist_ok=True)
    # Create a file handler for dvc.stage.run logger
    file_handler = logging.FileHandler(log_fpath, mode="w")
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    formatter.converter = time.gmtime  # Use UTC time for asctime
    file_handler.setFormatter(formatter)
    dvc.log.logger.addHandler(file_handler)
    # Remove newline logging in dvc.repo.reproduce
    dvc.repo.reproduce.logger.setLevel(logging.ERROR)
    # Disable other misc DVC output
    dvc.ui.ui.write = lambda *args, **kwargs: None
    res = dvc_cli_main(["repro"] + args)
    failed = res != 0
    # Parse log to get timing and which stages ran
    with open(log_fpath, "r") as f:
        log_content = f.read()
        stage_run_info = _stage_run_info_from_log_content(log_content)
    # Zip dvc-zip outputs for stages that actually ran
    if stage_run_info:
        from calkit.models.io import PathOutput
        from calkit.models.pipeline import Pipeline

        ck_info = calkit.load_calkit_info()
        pipeline_cfg = ck_info.get("pipeline", {})
        if pipeline_cfg:
            try:
                ck_pipeline = Pipeline.model_validate(pipeline_cfg)
                zip_input_paths = []
                for stage_name in stage_run_info:
                    stage = ck_pipeline.stages.get(stage_name)
                    if stage is None:
                        continue
                    for out in stage.outputs:
                        if (
                            isinstance(out, PathOutput)
                            and out.storage == "dvc-zip"
                        ):
                            zip_input_paths.append(out.path)
                if zip_input_paths:
                    calkit.dvc.zip.sync_some(
                        zip_input_paths, direction="to-zip"
                    )
            except Exception:
                # Fall back to syncing all zips if pipeline parsing fails
                calkit.dvc.zip.sync_all(direction="to-zip")
    # Close logger file handler to prevent permissions issues if deleting
    dvc.log.logger.removeHandler(file_handler)
    file_handler.close()
    if save_logs:
        # Get Git status after running
        git_changed_files_after = calkit.git.get_changed_files(repo=repo)
        git_staged_files_after = calkit.git.get_staged_files(repo=repo)
        git_untracked_files_after = calkit.git.get_untracked_files(repo=repo)
        # Get DVC status after running
        dvc_status_after = dvc_repo.status()
        dvc_data_status_after = dvc_repo.data_status()
        dvc_data_status_after.pop("git", None)  # Remove git status
        # Save run information to a file
        if verbose:
            typer.echo("Saving run info")
        run_info = {
            "id": run_id,
            "system_id": system_info["id"],
            "start_time": start_time.isoformat(),
            "end_time": calkit.utcnow(remove_tz=False).isoformat(),
            "targets": targets,
            "force": force,
            "dvc_args": args,
            "status": "failed" if failed else "completed",
            "stages": stage_run_info,
            "git_rev": git_rev,
            "git_branch": git_branch,
            "git_changed_files_before": git_changed_files_before,
            "git_staged_files_before": git_staged_files_before,
            "git_untracked_files_before": git_untracked_files_before,
            "git_changed_files_after": git_changed_files_after,
            "git_staged_files_after": git_staged_files_after,
            "git_untracked_files_after": git_untracked_files_after,
            "dvc_status_before": dvc_status_before,
            "dvc_data_status_before": dvc_data_status_before,
            "dvc_status_after": dvc_status_after,
            "dvc_data_status_after": dvc_data_status_after,
        }
        run_info_fpath = os.path.join(
            ".calkit",
            "runs",
            start_time_no_tz.isoformat(timespec="seconds").replace(":", "-")
            + "-"
            + run_id
            + ".json",
        )
        os.makedirs(os.path.dirname(run_info_fpath), exist_ok=True)
        with open(run_info_fpath, "w") as f:
            json.dump(run_info, f, indent=2)
    else:
        os.remove(log_fpath)
    os.environ.pop("CALKIT_PIPELINE_RUNNING", None)
    if failed:
        raise_error("Pipeline failed")
    else:
        calkit.echo("Pipeline completed successfully ✅")
    if save_after_run or save_message is not None:
        if save_message is None:
            save_message = "Run pipeline"
        if not quiet:
            typer.echo("Saving the project after successful run")
        save(save_all=True, message=save_message)
    # If specified, perform final Overleaf sync
    if sync_overleaf:
        overleaf_sync(
            verbose=verbose,
            no_commit=False,
            no_push=not save_after_run,
        )
    return {"dvc_stages": dvc_stages, "stage_run_info": stage_run_info}


@app.command(name="manual-step", help="Execute a manual step.")
def manual_step(
    message: Annotated[
        str,
        typer.Option(
            "--message",
            "-m",
            help="Message to display as a prompt.",
        ),
    ],
    cmd: Annotated[
        str | None, typer.Option("--cmd", help="Command to run.")
    ] = None,
    show_stdout: Annotated[
        bool, typer.Option("--show-stdout", help="Show stdout.")
    ] = False,
    show_stderr: Annotated[
        bool, typer.Option("--show-stderr", help="Show stderr.")
    ] = False,
) -> None:
    if cmd is not None:
        typer.echo(f"Running command: {cmd}")
        subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE if not show_stderr else None,
            stdout=subprocess.PIPE if not show_stdout else None,
            shell=True,
        )
    input(message + " (press enter to confirm): ")
    typer.echo("Done")


@app.command(
    name="runenv",
    help="Execute a command in an environment (alias for 'xenv').",
    context_settings={"ignore_unknown_options": True},
)
@app.command(
    name="xenv",
    help="Execute a command in an environment.",
    context_settings={"ignore_unknown_options": True},
)
def run_in_env(
    cmd: Annotated[
        list[str], typer.Argument(help="Command to run in the environment.")
    ],
    env_name: Annotated[
        str | None,
        typer.Option(
            "--name",
            "-n",
            help=(
                "Environment name in which to run. "
                "Only necessary if there are multiple in this project and "
                "path is not provided."
            ),
        ),
    ] = None,
    env_path: Annotated[
        str | None,
        typer.Option(
            "--env-path",
            "-p",
            help=(
                "Path of spec of environment in which to run. "
                "Will be added to the project if it doesn't exist."
            ),
        ),
    ] = None,
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
    no_check: Annotated[
        bool,
        typer.Option(
            "--no-check",
            help="Don't check the environment is valid before running in it.",
        ),
    ] = False,
    relaxed_check: Annotated[
        bool,
        typer.Option(
            "--relaxed",
            help="Check the environment in a relaxed way, if applicable.",
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output.")
    ] = False,
):
    from calkit.environments import env_from_name_and_or_path

    dotenv.load_dotenv(dotenv_path=".env", verbose=verbose)
    ck_info = calkit.load_calkit_info(process_includes="environments")
    calkit.set_env_vars(ck_info=ck_info)
    try:
        res = env_from_name_and_or_path(
            name=env_name, path=env_path, ck_info=ck_info
        )
    except Exception as e:
        raise_error(f"Failed to determine environment: {e}")
    envs = ck_info.get("environments", {})
    if not res.exists:
        envs[res.name] = res.env
        ck_info["environments"] = envs
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
    env_name = res.name
    env = envs[env_name]
    image_name = env.get("image", env_name)
    docker_wdir = env.get("wdir", "/work")
    docker_wdir_mount = docker_wdir
    if wdir is not None:
        docker_wdir = posixpath.join(docker_wdir, wdir)
    shell = env.get("shell", "sh")
    platform = env.get("platform")
    if env["kind"] == "docker":
        if "image" not in env:
            raise_error("Image must be defined for Docker environments")
        command_mode = env.get("command_mode", "shell")
        if command_mode not in ["shell", "entrypoint"]:
            raise_error(
                "Invalid Docker environment 'command_mode': "
                f"{command_mode}; Use 'shell' or 'entrypoint'"
            )
        if not no_check:
            check_docker_env(
                tag=env["image"],
                fpath=env.get("path"),
                lock_fpath=get_env_lock_fpath(
                    env=env, env_name=env_name, as_posix=False
                ),
                platform=env.get("platform"),
                deps=env.get("deps", []),
                env_vars=env.get("env_vars", []),
                ports=env.get("ports", []),
                gpus=env.get("gpus"),
                user=env.get("user"),
                wdir=env.get("wdir"),
                args=env.get("args", []),
                quiet=not verbose,
            )
        docker_cmd = [
            "docker",
            "run",
        ]
        if platform:
            docker_cmd += ["--platform", platform]
        env_vars = env.get("env_vars", {})
        if "env-vars" in env:
            warn("The 'env-vars' key is deprecated; use 'env_vars' instead.")
            env_vars.update(env["env-vars"])
        # Add project-level env vars (non-secret)
        env_vars.update(ck_info.get("env_vars", {}))
        # Also add any project-level environmental variable dependencies
        project_env_vars = calkit.get_env_var_dep_names()
        if project_env_vars:
            env_vars.update({k: f"${k}" for k in project_env_vars})
        if env_vars:
            for key, value in env_vars.items():
                if isinstance(value, str):
                    value = os.path.expandvars(value)
                docker_cmd += ["-e", f"{key}={value}"]
        if (gpus := env.get("gpus")) is not None:
            docker_cmd += ["--gpus", gpus]
        if ports := env.get("ports"):
            for port in ports:
                docker_cmd += ["-p", port]
        docker_user = env.get("user")
        if docker_user is None:
            try:
                uid = os.getuid()
                gid = os.getgid()
                docker_user = f"{uid}:{gid}"
            except AttributeError:
                # We're probably on Windows, so there is no UID to map
                pass
        if docker_user is not None:
            docker_cmd += ["--user", docker_user]
        docker_cmd += env.get("args", [])
        docker_cmd += [
            "-it" if sys.stdin.isatty() else "-i",
            "--rm",
            "-w",
            docker_wdir,
            "-v",
            f"{os.getcwd()}:{docker_wdir_mount}",
            image_name,
        ]
        if command_mode == "shell":
            shell_cmd = _to_shell_cmd(cmd)
            docker_cmd += [shell, "-c", shell_cmd]
        else:
            if not cmd:
                raise_error(
                    "No command provided for Docker environment in "
                    "'entrypoint' command mode"
                )
            docker_cmd += cmd
        if verbose:
            typer.echo(f"Running command: {docker_cmd}")
        try:
            subprocess.check_call(docker_cmd, cwd=wdir)
        except subprocess.CalledProcessError:
            raise_error("Failed to run in Docker environment")
    elif env["kind"] == "conda":
        with open(env["path"]) as f:
            conda_env = calkit.ryaml.load(f)
        if not no_check:
            check_conda_env(
                env_fpath=env["path"],
                output_fpath=get_env_lock_fpath(
                    env=env, env_name=env_name, as_posix=False
                ),
                relaxed=relaxed_check,
                quiet=not verbose,
            )
        # TODO: Prefix should only be in the env file or calkit.yaml, not both?
        prefix = env.get("prefix")
        conda_cmd = ["conda", "run"]
        if prefix is not None:
            conda_cmd += ["--prefix", os.path.abspath(prefix)]
        else:
            conda_cmd += ["-n", conda_env["name"]]
        cmd = conda_cmd + cmd
        if verbose:
            typer.echo(f"Running command: {cmd}")
        try:
            subprocess.check_call(cmd, cwd=wdir)
        except subprocess.CalledProcessError:
            raise_error("Failed to run in Conda environment")
    elif env["kind"] == "pixi":
        env_cmd = []
        if "name" in env:
            env_cmd = ["--environment", env["name"]]
        cmd = ["pixi", "run"] + env_cmd + cmd
        if verbose:
            typer.echo(f"Running command: {cmd}")
        try:
            subprocess.check_call(cmd, cwd=wdir)
        except subprocess.CalledProcessError:
            raise_error("Failed to run in Pixi environment")
    elif env["kind"] == "uv":
        env_dir = os.path.dirname(os.path.abspath(env["path"]))
        cmd = ["uv", "run", "--project", env_dir] + cmd
        if verbose:
            typer.echo(f"Running command: {cmd}")
        try:
            subprocess.check_call(cmd, cwd=wdir)
        except subprocess.CalledProcessError:
            raise_error("Failed to run in uv environment")
    elif (kind := env["kind"]) in ["uv-venv", "venv"]:
        if "prefix" not in env:
            raise_error("venv environments require a prefix")
        if "path" not in env:
            raise_error("venv environments require a path")
        prefix = env["prefix"]
        path = env["path"]
        shell_cmd = _to_shell_cmd(cmd)
        if _platform.system() == "Windows":
            activate_cmd = f"{prefix}\\Scripts\\activate"
        else:
            activate_cmd = f". {prefix}/bin/activate"
        if verbose:
            typer.echo(f"Raw command: {cmd}")
            typer.echo(f"Shell command: {shell_cmd}")
        # Check environment
        if not no_check:
            check_venv(
                path=path,
                prefix=prefix,
                use_uv=kind == "uv-venv",
                python=env.get("python"),
                lock_fpath=get_env_lock_fpath(
                    env=env, env_name=env_name, as_posix=False
                ),
                wdir=wdir,
                quiet=True,
                verbose=verbose,
            )
        # Now run the command
        cmd = f"{activate_cmd} && {shell_cmd} && deactivate"  # type: ignore
        if verbose:
            typer.echo(f"Running command: {cmd}")
        try:
            subprocess.check_call(cmd, shell=True, cwd=wdir)
        except subprocess.CalledProcessError:
            raise_error(f"Failed to run in {kind}")
    elif env["kind"] == "julia":
        if not no_check:
            check_environment(env_name=env_name, verbose=verbose)
        env_path = env.get("path")
        if env_path is None:
            raise_error(
                "Julia environments require a path pointing to Project.toml"
            )
        assert isinstance(env_path, str)
        julia_version = env.get("julia")
        env_fname = os.path.basename(env_path)
        if not env_fname == "Project.toml":
            raise_error(
                "Julia environments require a path pointing to Project.toml"
            )
        env_dir = os.path.dirname(env_path)
        if not env_dir:
            env_dir = "."
        # If command starts with 'julia', remove it since we are already
        # calling julia
        if cmd[0] == "julia":
            cmd = cmd[1:]
        # If there are any --project= args, remove them since we are already
        # specifying the project
        cmd = [arg for arg in cmd if not arg.startswith("--project=")]
        julia_cmd = [
            "julia",
            f"+{julia_version}",
            "--project=" + env_dir,
        ] + cmd
        try:
            julia_cmd = calkit.julia.check_version_in_command(julia_cmd)
        except Exception as e:
            raise_error(f"Failed to check Julia version: {e}")
        julia_cmd = calkit.julia.ensure_startup_file_disabled_in_command(
            julia_cmd
        )
        if verbose:
            typer.echo(f"Running command: {julia_cmd}")
        try:
            subprocess.check_call(
                julia_cmd,
                cwd=wdir,
                env=os.environ.copy() | {"JULIA_LOAD_PATH": "@:@stdlib"},
            )
        except subprocess.CalledProcessError:
            raise_error("Failed to run in julia environment")
    elif env["kind"] == "ssh":
        try:
            host = os.path.expandvars(env["host"])
            user = os.path.expandvars(env["user"])
            remote_wdir: str = env["wdir"]
        except KeyError:
            raise_error(
                "Host, user, and wdir must be defined for ssh environments"
            )
        send_paths = env.get("send_paths")
        get_paths = env.get("get_paths")
        key = env.get("key")
        if key is not None:
            key = os.path.expanduser(os.path.expandvars(key))
        remote_shell_cmd = _to_shell_cmd(cmd)
        # Run with nohup so we can disconnect
        # TODO: Should we collect output instead of send to /dev/null?
        remote_cmd = (
            f"cd '{remote_wdir}' ; nohup {remote_shell_cmd} "
            "> /dev/null 2>&1 & echo $! "
        )
        key_cmd = ["-i", key] if key is not None else []
        # Check to see if we've already submitted a job with this command
        jobs_fpath = ".calkit/jobs.yaml"
        job_key = f"{env_name}::{remote_shell_cmd}"
        remote_pid = None
        if os.path.isfile(jobs_fpath):
            with open(jobs_fpath) as f:
                jobs = calkit.ryaml.load(f)
            if jobs is None:
                jobs = {}
        else:
            jobs = {}
        job = jobs.get(job_key, {})
        remote_pid = job.get("remote_pid")
        if remote_pid is None:
            # First make sure the remote working dir exists
            typer.echo("Ensuring remote working directory exists")
            subprocess.check_call(
                ["ssh"]
                + key_cmd
                + [f"{user}@{host}", f"mkdir -p {remote_wdir}"]
            )
            # Now send any necessary files
            if send_paths:
                typer.echo("Sending to remote directory")
                # Accept glob patterns
                paths = []
                for p in send_paths:
                    paths += glob.glob(p)
                scp_cmd = (
                    ["scp", "-r"]
                    + key_cmd
                    + paths
                    + [f"{user}@{host}:{remote_wdir}/"]
                )
                if verbose:
                    typer.echo(f"scp cmd: {scp_cmd}")
                subprocess.check_call(scp_cmd)
            # Now run the command
            typer.echo(f"Running remote command: {remote_shell_cmd}")
            if verbose:
                typer.echo(f"Full command: {remote_cmd}")
            remote_pid = (
                subprocess.check_output(
                    ["ssh"] + key_cmd + [f"{user}@{host}", remote_cmd]
                )
                .decode()
                .strip()
            )
            typer.echo(f"Running with remote PID: {remote_pid}")
            # Save PID to jobs database so we can resume waiting
            typer.echo("Updating jobs database")
            os.makedirs(".calkit", exist_ok=True)
            job["remote_pid"] = remote_pid
            job["submitted"] = time.time()
            job["finished"] = None
            jobs[job_key] = job
            with open(jobs_fpath, "w") as f:
                calkit.ryaml.dump(jobs, f)
        # Now wait for the job to complete
        typer.echo(f"Waiting for remote PID {remote_pid} to finish")
        ps_cmd = ["ssh"] + key_cmd + [f"{user}@{host}", "ps", "-p", remote_pid]
        finished = False
        while not finished:
            try:
                subprocess.check_output(ps_cmd)
                finished = False
                time.sleep(2)
            except subprocess.CalledProcessError:
                finished = True
                typer.echo("Remote process finished")
        # Now sync the files back
        # TODO: Figure out how to do this in one command
        # Getting the syntax right is troublesome since it appears to work
        # differently on different platforms
        if get_paths:
            typer.echo("Copying files back from remote directory")
            for src_path in get_paths:
                src_path = remote_wdir + "/" + src_path  # type: ignore
                src = f"{user}@{host}:{src_path}"
                scp_cmd = ["scp", "-r"] + key_cmd + [src, "."]
                subprocess.check_call(scp_cmd)
        # Now delete the remote PID from the jobs file
        typer.echo("Updating jobs database")
        os.makedirs(".calkit", exist_ok=True)
        job["remote_pid"] = None
        job["finished"] = time.time()
        jobs[job_key] = job
        with open(jobs_fpath, "w") as f:
            calkit.ryaml.dump(jobs, f)
    elif env["kind"] == "renv":
        from calkit.cli.check import check_renv

        env_path = env.get("path")
        if env_path is None:
            raise_error("renv environments require a path to DESCRIPTION")
        assert isinstance(env_path, str)
        if not no_check:
            check_renv(env_path=env_path, verbose=verbose)
        # For renv, we need to run from the renv project directory so renv
        # properly initializes the library, but the script needs to run
        # from its original working directory
        # We set RENV_PROJECT to tell renv where to find its configuration,
        # then create a wrapper command that changes directory before sourcing
        # the script
        env_dir = os.path.dirname(os.path.abspath(env_path))
        if not env_dir:
            env_dir = "."
        abs_wdir = os.path.abspath(wdir) if wdir else os.getcwd()
        env_vars = os.environ.copy()
        env_vars["RENV_PROJECT"] = env_dir
        # Check if the first argument is an R script
        if cmd and cmd[0] == "Rscript" and len(cmd) > 1:
            script_path = cmd[1]
            script_abspath = os.path.abspath(
                os.path.join(abs_wdir, script_path)
            )
            # Use -e to inline the setwd + source command instead of a temp
            # file
            # Properly escape paths for R string literals (backslash and quote
            # escaping)
            escaped_wdir = abs_wdir.replace("\\", "\\\\").replace('"', '\\"')
            escaped_script = script_abspath.replace("\\", "\\\\").replace(
                '"', '\\"'
            )
            wrapper_cmd = (
                f'setwd("{escaped_wdir}"); source("{escaped_script}")'
            )
            cmd = ["Rscript", "-e", wrapper_cmd] + cmd[2:]
        if verbose:
            typer.echo(f"Setting RENV_PROJECT={env_dir}")
        try:
            subprocess.check_call(cmd, cwd=env_dir, env=env_vars)
        except subprocess.CalledProcessError:
            raise_error("Failed to run in renv")
    elif env["kind"] == "matlab":
        if not no_check:
            check_matlab_env(
                env_name=env_name,
                output_fpath=get_env_lock_fpath(
                    env=env, env_name=env_name, as_posix=False
                ),  # type: ignore
            )
        image_name = calkit.matlab.get_docker_image_name(
            ck_info=ck_info,
            env_name=env_name,
        )
        license_server = os.getenv("MATLAB_LICENSE_SERVER")
        if license_server is None:
            raise_error(
                "MATLAB_LICENSE_SERVER environment variable must be set"
            )
        docker_cmd = [
            "docker",
            "run",
            "--platform",
            "linux/amd64",  # Ensure compatibility with MATLAB
            "-it" if sys.stdin.isatty() else "-i",
            "--rm",
            "-w",
            "/work",
            "-v",
            f"{os.getcwd()}:/work",
            "-e",
            f"MLM_LICENSE_FILE={license_server}",
            image_name,
            "-sd",
            "/work",
            "-noFigureWindows",
            "-batch",
            " ".join(cmd),
        ]
        if verbose:
            typer.echo(f"Running command: {docker_cmd}")
        try:
            subprocess.check_call(docker_cmd, cwd=wdir)
        except subprocess.CalledProcessError:
            raise_error("Failed to run in MATLAB environment")
    else:
        raise_error("Environment kind not supported")


@app.command(name="runproc", help="Execute a procedure (alias for 'xproc').")
@app.command(name="xproc", help="Execute a procedure.")
def run_procedure(
    name: Annotated[str, typer.Argument(help="The name of the procedure.")],
    no_commit: Annotated[
        bool,
        typer.Option("--no-commit", help="Do not commit after each action."),
    ] = False,
):
    def wait(seconds):
        typer.echo(f"Wait {seconds} seconds")
        dt = 0.1
        while seconds >= 0:
            mins, secs = divmod(seconds, 60)
            mins, secs = int(mins), int(secs)
            out = f"Time left: {mins:02d}:{secs:02d}\r"
            typer.echo(out, nl=False)
            time.sleep(dt)
            seconds -= dt
        typer.echo("Done")

    def convert_value(value, dtype):
        if dtype == "int":
            return int(value)
        elif dtype == "float":
            return float(value)
        elif dtype == "str":
            return str(value)
        elif dtype == "bool":
            return bool(value)
        return value

    ck_info = calkit.load_calkit_info(process_includes="procedures")
    calkit.set_env_vars(ck_info=ck_info)
    procs = ck_info.get("procedures", {})
    if name not in procs:
        raise_error(f"'{name}' is not defined as a procedure")
    try:
        proc = Procedure.model_validate(procs[name])
    except Exception as e:
        raise_error(f"Procedure '{name}' is invalid: {e}")
    git_repo = git.Repo()
    # Check to make sure the working tree is clean, so we know we ran the
    # committed version of the procedure
    git_status = git_repo.git.status()
    if "working tree clean" not in git_status:
        raise_error(
            f"Cannot execute procedures unless repo is clean:\n\n{git_status}"
        )
    t_start_overall = calkit.utcnow()
    # Formulate headers for CSV file, which must contain all inputs from all
    # steps
    headers = [
        "calkit_version",
        "procedure_name",
        "step",
        "start",
        "end",
    ]
    for step in proc.steps:
        if step.inputs:
            for iname in step.inputs:
                if iname not in headers:
                    headers.append(iname)
    # TODO: Add ability to process periodic logic
    # See if now falls between start and end, and if there is a run with a
    # timestamp corresponding to the period in which now falls
    # If so, exit
    # If not, continue
    # Create empty CSV if one doesn't exist
    t_start_overall_str = t_start_overall.isoformat(timespec="seconds")
    fpath = f".calkit/procedure-runs/{name}/{t_start_overall_str}.csv"
    dirname = os.path.dirname(fpath)
    if not os.path.isdir(dirname):
        os.makedirs(dirname)
    if not os.path.isfile(fpath):
        with open(fpath, "w") as f:
            csv.writer(f).writerow(headers)
    for n, step in enumerate(proc.steps):
        typer.echo(f"Starting step {n}")
        t_start = calkit.utcnow()
        if step.wait_before_s:
            wait(step.wait_before_s)
        # Execute the step
        inputs = step.inputs
        input_vals = {}
        if not inputs:
            input(f"{step.summary} and press enter when complete: ")
        else:
            typer.echo(step.summary)
            for input_name, i in inputs.items():
                msg = f"Enter {input_name}"
                if i.units:
                    msg += f" ({i.units})"
                msg += " and press enter: "
                success = False
                while not success:
                    val = input(msg)
                    if i.dtype:
                        try:
                            val = convert_value(val, i.dtype)
                            success = True
                        except ValueError:
                            typer.echo(
                                typer.style(
                                    f"Invalid {i.dtype} value", fg="red"
                                )
                            )
                    else:
                        success = True
                input_vals[input_name] = val
        t_end = calkit.utcnow()
        # Log step completion
        row = (
            dict(
                procedure_name=name,
                step=n,
                calkit_version=calkit.__version__,
                start=t_start.isoformat(),
                end=t_end.isoformat(),
            )
            | input_vals
        )
        row = {k: row.get(k, "") for k in headers}
        # Log this row to CSV
        with open(fpath, "a") as f:
            csv.writer(f).writerow(row.values())
        typer.echo(f"Logged step {n} to {fpath}")
        if not no_commit:
            typer.echo("Committing to Git repo")
            git_repo.git.reset()
            git_repo.git.add(fpath)
            git_repo.git.commit(
                [
                    "-m",
                    f"Execute procedure {name} step {n}",
                ]
            )
        if step.wait_after_s:
            wait(step.wait_after_s)


@app.command(name="calc")
def run_calculation(
    name: Annotated[str, typer.Argument(help="Calculation name.")],
    inputs: Annotated[
        list[str],
        typer.Option(
            "--input", "-i", help="Inputs defined like x=1 (with no spaces.)"
        ),
    ] = [],
    no_formatting: Annotated[
        bool,
        typer.Option(
            "--no-format", help="Do not format output before printing"
        ),
    ] = False,
):
    """Run a project's calculation."""
    ck_info = calkit.load_calkit_info()
    calcs = ck_info.get("calculations", {})
    if name not in calcs:
        raise_error(f"Calculation '{name}' not defined in calkit.yaml")
    try:
        calc = calkit.calc.parse(calcs[name])
    except Exception as e:
        raise_error(f"Invalid calculation: {e}")
    # Parse inputs
    parsed_inputs = {}
    for i in inputs:
        iname, ival = i.split("=")
        parsed_inputs[iname] = ival
    try:
        if no_formatting:
            typer.echo(calc.evaluate(**parsed_inputs))
        else:
            typer.echo(calc.evaluate_and_format(**parsed_inputs))
    except Exception as e:
        raise_error(f"Calculation failed: {e}")


@app.command(name="set-env-var")
def set_env_var(
    name: Annotated[str, typer.Argument(help="Name of the variable.")],
    value: Annotated[str, typer.Argument(help="Value of the variable.")],
):
    """Set an environmental variable for the project in its '.env' file."""
    # Ensure that .env is ignored by git
    repo = git.Repo()
    if not repo.ignored(".env"):
        typer.echo("Adding .env to .gitignore")
        with open(".gitignore", "a") as f:
            f.write("\n.env\n")
    dotenv.set_key(dotenv_path=".env", key_to_set=name, value_to_set=value)


@app.command(name="upgrade")
def upgrade(
    skills: Annotated[
        bool, typer.Option("--skills", help="Upgrade agent skills as well.")
    ] = False,
):
    """Upgrade Calkit."""
    # First detect how Calkit is installed
    # If installed with uv tool, calkit will be located at something like
    # ~/.local/bin/calkit
    which_calkit = shutil.which("calkit")
    if which_calkit is None:
        raise_error("Calkit is not installed")
    split_path = os.path.normpath(str(which_calkit)).split(os.sep)
    if (
        ".local" in split_path
        and "bin" in split_path
        and calkit.check_dep_exists("uv")
    ):
        # This is a uv tool install
        cmd = [
            "uv",
            "tool",
            "install",
            "--upgrade",
            "calkit-python",
        ]
    elif "pipx" in split_path and calkit.check_dep_exists("pipx"):
        cmd = ["pipx", "upgrade", "calkit-python"]
    else:
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "calkit-python",
        ]
    res = subprocess.run(cmd)
    if res.returncode != 0:
        raise_error("Upgrade failed")
    typer.echo("Success!")
    if skills:
        from calkit.cli.update import update_agent_skills

        update_agent_skills()


@app.command(name="switch-branch")
def switch_branch(name: Annotated[str, typer.Argument(help="Branch name.")]):
    """Switch to a different branch."""
    repo = git.Repo()
    if name not in repo.heads:
        typer.echo(f"Branch '{name}' does not exist; creating")
        cmd = ["-b", name]
    else:
        cmd = [name]
    repo.git.checkout(cmd)
    # After switching branches, DVC-tracked zips may have changed; check out
    # the new branch's DVC data and unzip to the workspace
    run_dvc_command(["checkout"])
    calkit.dvc.zip.sync_all(direction="to-workspace")


@app.command(name="stash")
def stash(
    pop: Annotated[
        bool, typer.Option("--pop", help="Pop the most recent stash.")
    ] = False,
):
    """Stash or restore workspace changes including dvc-zip tracked dirs.

    Without --pop: zips any modified workspace dirs into the DVC cache, then
    git-stashes (saving the updated .dvc files), checks out the committed DVC
    state, and unzips it to the workspace.

    With --pop: pops the git stash (restoring the saved .dvc files), checks
    out the stashed DVC state, and unzips it to the workspace.
    """
    if pop:
        subprocess.check_call(["git", "stash", "pop"])
        run_dvc_command(["checkout"])
        calkit.dvc.zip.sync_all(direction="to-workspace")
    else:
        # Zip any modified workspace dirs so their current state is in the DVC
        # cache (the updated .dvc file will be captured by git stash)
        calkit.dvc.zip.sync_all(direction="to-zip")
        subprocess.check_call(["git", "stash"])
        # Restore the committed zip versions and unzip them
        run_dvc_command(["checkout"])
        calkit.dvc.zip.sync_all(direction="to-workspace")


@app.command(
    name="dvc",
    add_help_option=False,
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
def call_dvc(
    ctx: typer.Context,
    help: Annotated[bool, typer.Option("-h", "--help")] = False,
):
    """Run a command with the DVC CLI.

    Useful if Calkit is installed as a tool, e.g., with `uv tool` or `pipx`,
    and DVC is not installed.
    """
    result = run_dvc_command(sys.argv[2:])
    sys.exit(result)


@app.command(
    name="jupyter",
    add_help_option=False,
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
def run_jupyter(
    ctx: typer.Context,
    help: Annotated[bool, typer.Option("-h", "--help")] = False,
):
    """Run a command with the Jupyter CLI."""
    process = subprocess.run([sys.executable, "-m", "jupyter"] + sys.argv[2:])
    sys.exit(process.returncode)


@app.command(name="map-paths")
def map_paths(
    file_to_file: Annotated[
        list[str],
        typer.Option(
            "--file-to-file",
            help=(
                "Map a file to another file, e.g., "
                "--file-to-file 'results.tex->paper/results.tex'."
            ),
        ),
    ] = [],
    file_to_dir: Annotated[
        list[str],
        typer.Option(
            "--file-to-dir",
            help=(
                "Map a file into a directory, e.g., "
                "--file-to-dir 'results.tex->paper/results'."
            ),
        ),
    ] = [],
    dir_to_dir_replace: Annotated[
        list[str],
        typer.Option(
            "--dir-to-dir-replace",
            help=(
                "Copy directory to another directory and replace it, "
                "e.g., --dir-to-dir-replace 'figures->paper/figures'."
            ),
        ),
    ] = [],
    dir_to_dir_merge: Annotated[
        list[str],
        typer.Option(
            "--dir-to-dir-merge",
            help=(
                "Merge directory into another directory. "
                "This is useful for merging contents of one directory into "
                "another, e.g., --dir-to-dir-merge 'figures->paper/figures'."
            ),
        ),
    ] = [],
):
    """Map paths in a project.

    Currently this is done with copying. Outputs are ensured to be ignored by
    Git.
    """
    repo = git.Repo()

    def validate_and_split(mapping: str) -> tuple[str, str]:
        if "->" not in mapping:
            raise_error(
                f"Invalid path mapping format: '{mapping}'; "
                "Expected format: 'src->dest'"
            )
        parts = mapping.split("->")
        if len(parts) != 2:
            raise_error(
                f"Invalid path mapping format: '{mapping}'; "
                "Expected exactly one '->' separator"
            )
        return parts[0].strip(), parts[1].strip()

    for copy_file in file_to_file:
        src_path, dest_path = validate_and_split(copy_file)
        if os.path.isdir(dest_path):
            raise_error(f"Destination path '{dest_path}' is a directory")
        parent_dir = os.path.dirname(dest_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        shutil.copy2(src_path, dest_path)
        calkit.git.ensure_path_is_ignored(repo, path=dest_path)
    for copy_file in file_to_dir:
        src_path, dest_dir = validate_and_split(copy_file)
        if os.path.isfile(dest_dir):
            raise_error(f"Destination path '{dest_dir}' is a file")
        if not os.path.isdir(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, os.path.basename(src_path))
        shutil.copy2(src_path, dest_path)
        calkit.git.ensure_path_is_ignored(repo, path=dest_path)
    for replace_dir_with_dir in dir_to_dir_replace:
        src_dir, dest_dir = validate_and_split(replace_dir_with_dir)
        if os.path.isfile(dest_dir):
            raise_error(f"Destination path '{dest_dir}' is a file")
        if os.path.isfile(src_dir):
            raise_error(f"Source path '{src_dir}' is a file")
        if os.path.isdir(dest_dir):
            shutil.rmtree(dest_dir)
        parent_dir = os.path.dirname(dest_dir)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        shutil.copytree(src_dir, dest_dir)
        calkit.git.ensure_path_is_ignored(repo, path=dest_dir)
    for merge_dir_to_dir in dir_to_dir_merge:
        src_dir, dest_dir = validate_and_split(merge_dir_to_dir)
        if os.path.isfile(dest_dir):
            raise_error(f"Destination path '{dest_dir}' is a file")
        if os.path.isfile(src_dir):
            raise_error(f"Source path '{src_dir}' is a file")
        if not os.path.isdir(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)
        for item in os.listdir(src_dir):
            if item.startswith("."):
                continue
            src_item = os.path.join(src_dir, item)
            dest_item = os.path.join(dest_dir, item)
            if os.path.isdir(src_item):
                shutil.copytree(src_item, dest_item, dirs_exist_ok=True)
            else:
                shutil.copy2(src_item, dest_item)
            calkit.git.ensure_path_is_ignored(repo, path=dest_item)
