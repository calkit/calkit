"""Main CLI app."""

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
import calkit.matlab
import calkit.pipeline
from calkit import (
    AUTO_IGNORE_PATHS,
    AUTO_IGNORE_PREFIXES,
    AUTO_IGNORE_SUFFIXES,
    DVC_EXTENSIONS,
    DVC_SIZE_THRESH_BYTES,
)
from calkit.cli import print_sep, raise_error, run_cmd, warn
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
from calkit.cli.import_ import import_app
from calkit.cli.latex import latex_app
from calkit.cli.list import list_app
from calkit.cli.new import new_app
from calkit.cli.notebooks import notebooks_app
from calkit.cli.office import office_app
from calkit.cli.overleaf import overleaf_app
from calkit.cli.slurm import slurm_app
from calkit.cli.update import update_app
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
    dvc_cmd = [sys.executable, "-m", "dvc", "init"]
    if force:
        dvc_cmd.append("-f")
    subprocess.run(dvc_cmd)
    # Ensure autostage is enabled for DVC
    subprocess.call(
        [sys.executable, "-m", "dvc", "config", "core.autostage", "true"]
    )
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
            subprocess.check_call([sys.executable, "-m", "dvc", "pull"])
        except subprocess.CalledProcessError:
            raise_error("Failed to pull from DVC remote(s)")


@app.command(name="status")
def get_status(
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
):
    """View status (project, version control, and/or pipeline)."""
    ck_info = calkit.load_calkit_info()
    try:
        calkit.pipeline.to_dvc(ck_info=ck_info, write=True)
    except Exception as e:
        warn(f"Failed to compile pipeline: {e.__class__.__name__}: {e}")
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
    # Clean all notebooks in the pipeline
    try:
        calkit.notebooks.clean_all_in_pipeline(ck_info=ck_info)
    except Exception as e:
        warn(f"Failed to clean notebooks: {e.__class__.__name__}: {e}")
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
        run_cmd(["git", "status"])
        typer.echo()
    if "dvc" in categories:
        print_sep("DVC")
        run_cmd([sys.executable, "-m", "dvc", "data", "status"])
        typer.echo()
    if "pipeline" in categories or "dvc" in categories:
        print_sep("Pipeline")
        run_cmd([sys.executable, "-m", "dvc", "status"])


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
    run_cmd([sys.executable, "-m", "dvc", "diff"])


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
            "--to", "-t", help="System with which to add (git or dvc)."
        ),
    ] = None,
):
    """Add paths to the repo.

    Code will be added to Git and data will be added to DVC.

    Note: This will enable the 'autostage' feature of DVC, automatically
    adding any .dvc files to Git when adding to DVC.
    """
    import dvc.repo
    from dvc.exceptions import NotDvcRepoError

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
    if to is not None and to not in ["git", "dvc"]:
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
        dvc_repo = dvc.repo.Repo()
    except NotDvcRepoError:
        warn("DVC not initialized yet; initializing")
        dvc_repo = dvc.repo.Repo.init()
    # Ensure autostage is enabled for DVC
    subprocess.call(
        [sys.executable, "-m", "dvc", "config", "core.autostage", "true"]
    )
    subprocess.call(["git", "add", ".dvc/config"])
    dvc_paths = calkit.dvc.list_paths()
    untracked_git_files = repo.untracked_files
    if auto_commit_message:
        # See if this path is in the repo already
        if paths[0] in dvc_paths or repo.git.ls_files(paths[0]):
            commit_message = f"Update {paths[0]}"
        else:
            commit_message = f"Add {paths[0]}"
    if to is not None:
        if to == "git":
            subprocess.call(["git", "add"] + paths)
        elif to == "dvc":
            subprocess.call([sys.executable, "-m", "dvc", "add"] + paths)
        else:
            raise_error(f"Invalid option for 'to': {to}")
    else:
        if "." in paths:
            paths.remove(".")
            dvc_status = dvc_repo.data_status()
            for dvc_uncommitted in dvc_status["uncommitted"].get(
                "modified", []
            ):
                if os.path.exists(dvc_uncommitted):
                    typer.echo(f"Adding {dvc_uncommitted} to DVC")
                    dvc_repo.commit(dvc_uncommitted, force=True)
                else:
                    warn(
                        f"DVC uncommitted '{dvc_uncommitted}' does not exist; "
                        "skipping"
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
                        typer.echo(f"Automatically ignoring {untracked_file}")
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
        for path in paths:
            # Detect if this file should be tracked with Git or DVC
            # First see if it's in Git
            if repo.git.ls_files(path):
                typer.echo(
                    f"Adding {path} to Git since it's already in the repo"
                )
                subprocess.call(["git", "add", path])
            elif path in dvc_paths:
                typer.echo(
                    f"Adding {path} to DVC since it's already tracked with DVC"
                )
                subprocess.call([sys.executable, "-m", "dvc", "add", path])
            elif os.path.splitext(path)[-1] in DVC_EXTENSIONS:
                typer.echo(f"Adding {path} to DVC per its extension")
                subprocess.call([sys.executable, "-m", "dvc", "add", path])
            elif calkit.get_size(path) > DVC_SIZE_THRESH_BYTES:
                typer.echo(
                    f"Adding {path} to DVC since it's greater than 1 MB"
                )
                subprocess.call([sys.executable, "-m", "dvc", "add", path])
            else:
                typer.echo(f"Adding {path} to Git")
                subprocess.call(["git", "add", path])
    if commit_message is not None:
        subprocess.call(["git", "commit", "-m", commit_message])
    if push_commit:
        push()


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
        add(paths=["."])
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
            if name == "calkit" or name.startswith("calkit:"):
                typer.echo(f"Checking authentication for DVC remote: {name}")
                calkit.dvc.set_remote_auth(remote_name=name)
    try:
        subprocess.check_call([sys.executable, "-m", "dvc", "pull"] + dvc_args)
    except subprocess.CalledProcessError:
        raise_error("DVC pull failed")


@app.command(name="push")
def push(
    no_check_auth: Annotated[bool, typer.Option("--no-check-auth")] = False,
    no_dvc: Annotated[bool, typer.Option("--no-dvc")] = False,
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
    typer.echo("Pushing to Git remote")
    try:
        git_cmd = ["git", "push"]
        if not no_recursive and "--recurse-submodules" not in git_args:
            git_cmd.append("--recurse-submodules=on-demand")
        subprocess.check_call(git_cmd + git_args)
    except subprocess.CalledProcessError:
        raise_error("Git push failed")
    if not no_dvc:
        typer.echo("Pushing to DVC remote")
        if not no_check_auth:
            # Check that our dvc remotes all have our DVC token set for them
            remotes = calkit.dvc.get_remotes()
            for name, url in remotes.items():
                if name == "calkit" or name.startswith("calkit:"):
                    typer.echo(
                        f"Checking authentication for DVC remote: {name}"
                    )
                    calkit.dvc.set_remote_auth(remote_name=name)
        try:
            subprocess.check_call(
                [sys.executable, "-m", "dvc", "push"] + dvc_args
            )
        except subprocess.CalledProcessError:
            raise_error("DVC push failed")


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
        list[str] | None, typer.Argument(help="Stages to run.")
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
        typer.Option("--dry", help="Only print commands that would execute."),
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
        dvc.repo.Repo()
    except Exception:
        if not quiet:
            typer.echo("Initializing DVC repo")
        dvc.repo.Repo.init()
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
        dvc_repo = dvc.repo.Repo()
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
    # Parse log to get timing
    with open(log_fpath, "r") as f:
        log_content = f.read()
        stage_run_info = _stage_run_info_from_log_content(log_content)
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
        typer.echo(
            "Pipeline completed successfully ✅".encode(
                "utf-8", errors="replace"
            )
        )
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
        shell_cmd = _to_shell_cmd(cmd)
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
            shell,
            "-c",
            shell_cmd,
        ]
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
        julia_cmd = [
            "julia",
            f"+{julia_version}",
            "--project=" + env_dir,
        ] + cmd
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


@app.command(name="xr")
def execute_and_record(
    cmd: Annotated[
        list[str],
        typer.Argument(
            help="Command to execute and record. "
            "If the first argument is a script, notebook or LaTeX file, "
            "it will be treated as a stage with that file as "
            "the target. Any command, including arguments, is supported."
        ),
    ],
    environment: Annotated[
        str | None,
        typer.Option(
            "--environment",
            "-e",
            help="Name of or path the spec file for the environment to use.",
        ),
    ] = None,
    inputs: Annotated[
        list[str],
        typer.Option(
            "--input",
            "-i",
            help="Input paths to record.",
        ),
    ] = [],
    outputs: Annotated[
        list[str],
        typer.Option(
            "--output",
            "-o",
            help="Output paths to record.",
        ),
    ] = [],
    no_detect_io: Annotated[
        bool,
        typer.Option(
            "--no-detect-io",
            help=(
                "Don't attempt to detect inputs and outputs from the command, "
                "script, or notebook."
            ),
        ),
    ] = False,
    stage_name: Annotated[
        str | None,
        typer.Option(
            "--stage",
            help=(
                "Name of the DVC stage to create for this command. If not "
                "provided, a name will be generated automatically."
            ),
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-d",
            help=(
                "Print the environment and stage that would be created "
                "without modifying calkit.yaml or executing the command."
            ),
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Force running stage even if it's up-to-date.",
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output.")
    ] = False,
):
    """Execute a command and if successful, record in the pipeline."""
    import io
    import shlex

    from calkit.detect import (
        detect_io,
        generate_stage_name,
    )
    from calkit.environments import detect_env_for_stage
    from calkit.models.io import PathOutput
    from calkit.models.pipeline import (
        JuliaCommandStage,
        JuliaScriptStage,
        JupyterNotebookStage,
        LatexStage,
        MatlabCommandStage,
        MatlabScriptStage,
        PythonScriptStage,
        RScriptStage,
        ShellCommandStage,
        ShellScriptStage,
    )
    from calkit.pipeline import stages_are_similar

    def _determine_output_storage(
        path: str,
        repo: git.Repo | None = None,
        dvc_paths: list[str] | None = None,
    ) -> str:
        """Determine storage type (git or dvc) for an output path.

        Parameters
        ----------
        path : str
            Path to check.
        repo : git.Repo | None
            Git repository. If None, only extension and size are checked.
        dvc_paths : list[str] | None
            List of paths tracked by DVC.

        Returns
        -------
        str
            "git" or "dvc".
        """
        if dvc_paths is None:
            dvc_paths = []
        # If already tracked by git, use git
        if repo is not None and repo.git.ls_files(path):
            return "git"
        # If already tracked by dvc, use dvc
        if path in dvc_paths:
            return "dvc"
        # Check extension
        if os.path.splitext(path)[-1] in DVC_EXTENSIONS:
            return "dvc"
        # Check size if file exists
        if os.path.exists(path):
            try:
                if calkit.get_size(path) > DVC_SIZE_THRESH_BYTES:
                    return "dvc"
            except (OSError, IOError):
                # If we cannot determine file size (e.g., permission
                # or I/O issues), fall back to the default "git"
                # behavior below.
                pass
        # Default to git for small/unknown files
        return "git"

    # First, read the pipeline before running so we can revert if the stage
    # fails
    ck_info = calkit.load_calkit_info()
    ck_info_orig = deepcopy(ck_info)
    pipeline = ck_info.get("pipeline", {})
    stages = pipeline.get("stages", {})
    # Strip and detect uv/pixi run prefix
    if len(cmd) >= 2 and cmd[0] == "uv" and cmd[1] == "run":
        if environment is None and os.path.isfile("pyproject.toml"):
            environment = "pyproject.toml"
        cmd = cmd[2:]
    elif len(cmd) >= 2 and cmd[0] == "pixi" and cmd[1] == "run":
        if environment is None and os.path.isfile("pixi.toml"):
            environment = "pixi.toml"
        cmd = cmd[2:]
    # Guard against empty command after stripping uv/pixi run
    if not cmd:
        raise_error(
            "No command specified after stripping environment prefix. "
            "Usage: calkit xr [uv|pixi run] <command> [args]"
        )
    # Detect what kind of stage this is based on the command
    # If the first argument is a notebook, we'll treat this as a notebook stage
    # If the first argument is `python`, check that the second argument is a
    # script, otherwise it's a shell-command stage
    # If the first argument ends with .tex, we'll treat this as a LaTeX stage
    first_arg = cmd[0]
    stage = {}
    language = None
    if first_arg.endswith(".ipynb"):
        cls = JupyterNotebookStage
        stage["kind"] = "jupyter-notebook"
        stage["notebook_path"] = first_arg
        storage = calkit.notebooks.determine_storage(first_arg)
        stage["html_storage"] = storage
        stage["executed_ipynb_storage"] = storage
    elif first_arg.endswith(".tex"):
        cls = LatexStage
        stage["kind"] = "latex"
        stage["target_path"] = first_arg
        language = "latex"
        # Determine PDF storage based on whether it's already in git
        pdf_path = first_arg.removesuffix(".tex") + ".pdf"
        try:
            repo = git.Repo(".")
            if repo.git.ls_files(pdf_path):
                stage["pdf_storage"] = "git"
            else:
                stage["pdf_storage"] = "dvc"
        except InvalidGitRepositoryError:
            # Not a git repo, default to dvc
            stage["pdf_storage"] = "dvc"
    elif first_arg == "python" and len(cmd) > 1 and cmd[1].endswith(".py"):
        cls = PythonScriptStage
        stage["kind"] = "python-script"
        stage["script_path"] = cmd[1]
        if len(cmd) > 2:
            stage["args"] = cmd[2:]
        language = "python"
    elif first_arg.endswith(".py"):
        cls = PythonScriptStage
        stage["kind"] = "python-script"
        stage["script_path"] = first_arg
        if len(cmd) > 1:
            stage["args"] = cmd[1:]
        language = "python"
    elif first_arg == "julia" and len(cmd) > 1 and cmd[1].endswith(".jl"):
        cls = JuliaScriptStage
        stage["kind"] = "julia-script"
        stage["script_path"] = cmd[1]
        if len(cmd) > 2:
            stage["args"] = cmd[2:]
        language = "julia"
    elif first_arg.endswith(".jl"):
        cls = JuliaScriptStage
        stage["kind"] = "julia-script"
        stage["script_path"] = first_arg
        if len(cmd) > 1:
            stage["args"] = cmd[1:]
        language = "julia"
    elif first_arg == "julia" and len(cmd) > 1:
        cls = JuliaCommandStage
        stage["kind"] = "julia-command"
        stage["command"] = " ".join(cmd[1:])
        language = "julia"
    elif first_arg == "matlab" and len(cmd) > 1 and cmd[1].endswith(".m"):
        cls = MatlabScriptStage
        stage["kind"] = "matlab-script"
        stage["script_path"] = cmd[1]
        language = "matlab"
    elif first_arg.endswith(".m"):
        cls = MatlabScriptStage
        stage["kind"] = "matlab-script"
        stage["script_path"] = first_arg
        language = "matlab"
    elif first_arg == "matlab" and len(cmd) > 1:
        cls = MatlabCommandStage
        stage["kind"] = "matlab-command"
        stage["command"] = " ".join(cmd[1:])
        language = "matlab"
    elif first_arg == "Rscript" and len(cmd) > 1 and cmd[1].endswith(".R"):
        cls = RScriptStage
        stage["kind"] = "r-script"
        stage["script_path"] = cmd[1]
        if len(cmd) > 2:
            stage["args"] = cmd[2:]
        language = "r"
    elif first_arg.endswith(".R"):
        cls = RScriptStage
        stage["kind"] = "r-script"
        stage["script_path"] = first_arg
        if len(cmd) > 1:
            stage["args"] = cmd[1:]
        language = "r"
    elif first_arg.endswith((".sh", ".bash", ".zsh")):
        cls = ShellScriptStage
        stage["kind"] = "shell-script"
        stage["script_path"] = first_arg
        if len(cmd) > 1:
            stage["args"] = cmd[1:]
        # Detect shell type from extension
        if first_arg.endswith(".bash"):
            stage["shell"] = "bash"
        elif first_arg.endswith(".zsh"):
            stage["shell"] = "zsh"
        else:
            stage["shell"] = "sh"
        language = "shell"
    else:
        cls = ShellCommandStage
        stage["kind"] = "shell-command"
        stage["command"] = " ".join(shlex.quote(arg) for arg in cmd)
        language = "shell"
    # Create a stage name if one isn't provided and check for existing similar
    # stages
    if stage_name is None:
        base_stage_name = generate_stage_name(cmd)
        stage_name = base_stage_name
        # If a stage with this name exists and is different, auto-increment
        if stage_name in stages:
            existing_stage = stages[stage_name]
            if not stages_are_similar(existing_stage, stage):
                # Find the next available increment
                counter = 2
                while f"{base_stage_name}-{counter}" in stages:
                    candidate_stage = stages[f"{base_stage_name}-{counter}"]
                    if stages_are_similar(candidate_stage, stage):
                        # Found a matching stage with this incremented name
                        stage_name = f"{base_stage_name}-{counter}"
                        break
                    counter += 1
                else:
                    # No matching stage found, use the next available number
                    stage_name = f"{base_stage_name}-{counter}"
                typer.echo(
                    f"Stage '{base_stage_name}' already exists with different "
                    f"configuration; using '{stage_name}' instead"
                )
    # Check if a similar stage already exists and reuse its environment if not
    # specified
    if stage_name in stages:
        existing_stage = stages[stage_name]
        if not stages_are_similar(existing_stage, stage):
            raise_error(
                f"A stage named '{stage_name}' already exists with "
                "different configuration; "
                f"Please specify a unique stage name with --stage"
            )
            return
        # If no environment was specified and a similar stage exists,
        # reuse its environment
        if environment is None and "environment" in existing_stage:
            environment = existing_stage["environment"]
            typer.echo(
                f"Reusing environment '{environment}' from existing "
                f"stage '{stage_name}'"
            )
    # Detect or create environment for this stage
    env_result = detect_env_for_stage(
        stage=stage,
        environment=environment,
        ck_info=ck_info,
        language=language,
    )
    # If we created an environment from dependencies, write the spec file
    if env_result.created_from_dependencies and not dry_run:
        typer.echo(
            "No existing environment detected; "
            "Attempting to create one based on detected dependencies"
        )
        if env_result.dependencies:
            typer.echo(
                f"Detected {language or 'code'} dependencies: "
                f"{', '.join(env_result.dependencies)}"
            )
        if env_result.spec_path and env_result.spec_content is not None:
            # Create the spec file
            spec_dir = os.path.dirname(env_result.spec_path)
            if spec_dir:
                os.makedirs(spec_dir, exist_ok=True)
            with open(env_result.spec_path, "w") as f:
                f.write(env_result.spec_content)
            typer.echo(f"Created environment spec: {env_result.spec_path}")
    # Add environment to calkit.yaml if it doesn't exist
    if not env_result.exists and not dry_run:
        envs = ck_info.get("environments", {})
        envs[env_result.name] = env_result.env
        ck_info["environments"] = envs
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        ck_info = calkit.load_calkit_info()
    env_name = env_result.name
    stage["environment"] = env_name
    # Detect inputs and outputs if not disabled
    detected_inputs = []
    detected_outputs = []
    if not no_detect_io:
        try:
            io_info = detect_io(stage)
            detected_inputs = io_info["inputs"]
            detected_outputs = io_info["outputs"]
        except Exception as e:
            typer.echo(
                f"Warning: Failed to detect inputs/outputs: {e}",
                err=True,
            )
    # Initialize git repo and get DVC paths for storage determination
    try:
        repo = git.Repo(".")
    except InvalidGitRepositoryError:
        repo = None
    dvc_paths = []
    if repo is not None:
        try:
            dvc_paths = calkit.dvc.list_paths()
        except Exception:
            # DVC might not be initialized
            pass
    # Merge user-specified inputs/outputs with detected ones
    # User-specified take precedence and detected ones are added if not already
    # present
    all_inputs = list(inputs)  # Start with user-specified
    for detected in detected_inputs:
        if detected not in all_inputs:
            all_inputs.append(detected)
    # Convert detected outputs to PathOutput models with storage determination
    detected_output_models: list[str | PathOutput] = []
    for detected in detected_outputs:
        storage = _determine_output_storage(detected, repo, dvc_paths)
        detected_output_models.append(
            PathOutput(
                path=detected,
                storage=storage,  # type: ignore[arg-type]
            )
        )
    # Merge outputs
    all_outputs: list[str | PathOutput] = list(
        outputs
    )  # Start with user-specified
    for detected in detected_output_models:
        # Check if this output path is already present
        detected_path = (
            detected.path if isinstance(detected, PathOutput) else detected
        )
        already_present = False
        for existing in all_outputs:
            existing_path = (
                existing.path if isinstance(existing, PathOutput) else existing
            )
            if existing_path == detected_path:
                already_present = True
                break
        if not already_present:
            all_outputs.append(detected)
    # Add inputs and outputs to stage
    if all_inputs:
        stage["inputs"] = all_inputs
    if all_outputs:
        # Convert PathOutput objects to dicts for serialization
        serialized_outputs = []
        for output in all_outputs:
            if isinstance(output, PathOutput):
                serialized_outputs.append(
                    output.model_dump(exclude_unset=True)
                )
            else:
                serialized_outputs.append(output)
        stage["outputs"] = serialized_outputs
    # Create the stage, write to calkit.yaml, and run it to see if
    # it's successful
    try:
        cls.model_validate(stage)
    except Exception as e:
        raise_error(f"Failed to create stage: {e}")
    # If dry-run, print environment and stage then return
    if dry_run:
        # Print environment info
        if env_result.created_from_dependencies:
            typer.echo("Environment (would be created):")
            if env_result.spec_path and env_result.spec_content is not None:
                typer.echo(f"  Spec file: {env_result.spec_path}")
                typer.echo("  Content:")
                for line in env_result.spec_content.split("\n"):
                    typer.echo(f"    {line}")
        elif not env_result.exists:
            typer.echo("Environment (would be added to calkit.yaml):")
            yaml_output = io.StringIO()
            calkit.ryaml.dump({env_result.name: env_result.env}, yaml_output)
            for line in yaml_output.getvalue().rstrip().split("\n"):
                typer.echo(f"  {line}")
        else:
            typer.echo(f"Environment: {env_name} (already exists)")
        # Print stage
        typer.echo("\nStage (would be added to pipeline):")
        yaml_output = io.StringIO()
        calkit.ryaml.dump({stage_name: stage}, yaml_output)
        for line in yaml_output.getvalue().rstrip().split("\n"):
            typer.echo(f"  {line}")
        return
    stages[stage_name] = stage
    pipeline["stages"] = stages
    ck_info["pipeline"] = pipeline
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    try:
        # Format stage as YAML for display
        yaml_output = io.StringIO()
        calkit.ryaml.dump({stage_name: stage}, yaml_output)
        # Indent YAML by 2 spaces
        indented_yaml = "\n".join(
            "  " + line if line.strip() else line
            for line in yaml_output.getvalue().rstrip().split("\n")
        )
        typer.echo(
            f"Adding stage to pipeline and attempting to execute:"
            f"\n{indented_yaml}"
        )
        run(targets=[stage_name], force=force, verbose=verbose)
    except Exception as e:
        # If the stage failed, write the old ck_info back to calkit.yaml to
        # remove the stage that we added
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info_orig, f)
        raise_error(f"Failed to execute stage: {e}")


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
        typer.echo()

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
def upgrade():
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
    process = subprocess.run([sys.executable, "-m", "dvc"] + sys.argv[2:])
    sys.exit(process.returncode)


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
