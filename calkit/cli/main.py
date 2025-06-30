"""Main CLI app."""

from __future__ import annotations

import csv
import glob
import os
import platform as _platform
import posixpath
import subprocess
import sys
import time
from pathlib import PurePosixPath

import dotenv
import dvc.repo
import git
import typer
from dvc.exceptions import NotDvcRepoError
from git.exc import InvalidGitRepositoryError
from typing_extensions import Annotated, Optional

import calkit
import calkit.matlab
import calkit.pipeline
from calkit.cli import print_sep, raise_error, run_cmd, warn
from calkit.cli.check import (
    check_app,
    check_conda_env,
    check_docker_env,
    check_matlab_env,
    check_venv,
)
from calkit.cli.cloud import cloud_app
from calkit.cli.config import config_app
from calkit.cli.import_ import import_app
from calkit.cli.list import list_app
from calkit.cli.new import new_app
from calkit.cli.notebooks import notebooks_app
from calkit.cli.office import office_app
from calkit.cli.overleaf import overleaf_app
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
app.add_typer(import_app, name="import", help="Import objects.")
app.add_typer(office_app, name="office", help="Work with Microsoft Office.")
app.add_typer(update_app, name="update", help="Update objects.")
app.add_typer(check_app, name="check", help="Check things.")
app.add_typer(overleaf_app, name="overleaf", help="Interact with Overleaf.")
app.add_typer(cloud_app, name="cloud", help="Interact with a Calkit Cloud.")

# Constants for version control auto-ignore
AUTO_IGNORE_SUFFIXES = [".DS_Store", ".env", ".pyc"]
AUTO_IGNORE_PATHS = [os.path.join(".dvc", "config.local")]
AUTO_IGNORE_PREFIXES = [".venv", "__pycache__"]
# Constants for version control auto-add to DVC
DVC_EXTENSIONS = [
    ".png",
    ".jpeg",
    ".jpg",
    ".gif",
    ".h5",
    ".parquet",
    ".pickle",
    ".mp4",
    ".avi",
    ".webm",
    ".pdf",
    ".xlsx",
    ".docx",
    ".xls",
    ".doc",
    ".nc",
    ".nc4",
    ".zarr",
]
DVC_SIZE_THRESH_BYTES = 1_000_000


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
    recursive: Annotated[
        bool, typer.Option("--recursive", help="Recursively clone submodules.")
    ] = False,
):
    """Clone a Git repo and by default configure and pull from the DVC
    remote.
    """
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
    if recursive:
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
def get_status():
    """Get a unified Git and DVC status."""
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
        status_txt = typer.style(status.status, fg=colors.get(status.status))
        typer.echo(f"Current status: {status_txt} (updated {ts} UTC)")
    else:
        typer.echo(
            'Project status not set. Use "calkit new status" to update.'
        )
    typer.echo()
    print_sep("Code (Git)")
    run_cmd(["git", "status"])
    typer.echo()
    print_sep("Data (DVC)")
    run_cmd([sys.executable, "-m", "dvc", "data", "status"])
    typer.echo()
    print_sep("Pipeline (DVC)")
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
        subprocess.call([to, "add"] + paths)
    else:
        if "." in paths:
            paths.remove(".")
            dvc_status = dvc_repo.data_status()
            for dvc_uncommitted in dvc_status["uncommitted"].get(
                "modified", []
            ):
                typer.echo(f"Adding {dvc_uncommitted} to DVC")
                dvc_repo.commit(dvc_uncommitted, force=True)
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
    any_dvc = any(
        [
            path == "dvc.lock" or path.endswith(".dvc")
            for path in calkit.git.get_staged_files()
        ]
    )
    commit(all=True if paths is None else False, message=message)
    if not no_push:
        if verbose and not any_dvc:
            typer.echo("Not pushing to DVC since no DVC files were staged")
        push(no_dvc=not any_dvc)


@app.command(name="pull")
def pull(
    no_check_auth: Annotated[bool, typer.Option("--no-check-auth")] = False,
):
    """Pull with both Git and DVC."""
    typer.echo("Git pulling")
    try:
        subprocess.check_call(["git", "pull"])
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
        subprocess.check_call([sys.executable, "-m", "dvc", "pull"])
    except subprocess.CalledProcessError:
        raise_error("DVC pull failed")


@app.command(name="push")
def push(
    no_check_auth: Annotated[bool, typer.Option("--no-check-auth")] = False,
    no_dvc: Annotated[bool, typer.Option("--no-dvc")] = False,
):
    """Push with both Git and DVC."""
    typer.echo("Pushing to Git remote")
    try:
        subprocess.check_call(["git", "push"])
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
            subprocess.check_call([sys.executable, "-m", "dvc", "push"])
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
    path = PurePosixPath(path).as_posix()
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


@app.command(
    name="run",
    add_help_option=False,
)
def run(
    targets: Optional[list[str]] = typer.Argument(default=None),
    help: Annotated[bool, typer.Option("-h", "--help")] = False,
    quiet: Annotated[bool, typer.Option("-q", "--quiet")] = False,
    verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False,
    force: Annotated[bool, typer.Option("-f", "--force")] = False,
    interactive: Annotated[bool, typer.Option("-i", "--interactive")] = False,
    single_item: Annotated[bool, typer.Option("-s", "--single-item")] = False,
    pipeline: Annotated[
        Optional[str], typer.Option("-p", "--pipeline")
    ] = None,
    all_pipelines: Annotated[
        bool, typer.Option("-P", "--all-pipelines")
    ] = False,
    recursive: Annotated[bool, typer.Option("-R", "--recursive")] = False,
    downstream: Annotated[
        Optional[list[str]], typer.Option("--downstream")
    ] = None,
    force_downstream: Annotated[
        bool, typer.Option("--force-downstream")
    ] = False,
    pull: Annotated[bool, typer.Option("--pull")] = False,
    allow_missing: Annotated[bool, typer.Option("--allow-missing")] = False,
    dry: Annotated[bool, typer.Option("--dry")] = False,
    keep_going: Annotated[bool, typer.Option("--keep-going", "-k")] = False,
    ignore_errors: Annotated[bool, typer.Option("--ignore-errors")] = False,
    glob: Annotated[bool, typer.Option("--glob")] = False,
    no_commit: Annotated[bool, typer.Option("--no-commit")] = False,
    no_run_cache: Annotated[bool, typer.Option("--no-run-cache")] = False,
):
    """Check dependencies, run DVC pipeline, and update Calkit objects."""
    dotenv.load_dotenv(dotenv_path=".env", verbose=verbose)
    # First check any system-level dependencies exist
    typer.echo("Checking system-level dependencies")
    try:
        calkit.check_system_deps()
    except Exception as e:
        raise_error(str(e))
    # Compile the pipeline
    ck_info = calkit.load_calkit_info()
    if ck_info.get("pipeline", {}):
        typer.echo("Compiling DVC pipeline")
        calkit.pipeline.to_dvc(ck_info=ck_info, write=True)
    if targets is None:
        targets = []
    args = targets
    # Extract any boolean args
    for name in [
        "help",
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
    try:
        subprocess.check_call([sys.executable, "-m", "dvc", "repro"] + args)
    except subprocess.CalledProcessError:
        raise_error("DVC pipeline failed")


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
                "Only necessary if there are multiple in this project."
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
    dotenv.load_dotenv(dotenv_path=".env", verbose=verbose)
    ck_info = calkit.load_calkit_info(process_includes="environments")
    envs = ck_info.get("environments", {})
    if not envs:
        raise_error("No environments defined in calkit.yaml")
    if isinstance(envs, list):
        raise_error("Error: Environments should be a dict, not a list")
    assert isinstance(envs, dict)
    if env_name is None:
        # See if there's a default env, or only one env defined
        default_env_name = None
        for n, e in envs.items():
            if e.get("default"):
                if default_env_name is not None:
                    raise_error(
                        "Only one default environment can be specified"
                    )
                default_env_name = n
        if default_env_name is None and len(envs) == 1:
            default_env_name = list(envs.keys())[0]
        env_name = default_env_name
    if env_name is None:
        raise_error("Environment must be specified if there are multiple")
    assert isinstance(env_name, str)
    if env_name not in envs:
        raise_error(f"Environment '{env_name}' does not exist")
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
                quiet=not verbose,
            )
        shell_cmd = _to_shell_cmd(cmd)
        docker_cmd = [
            "docker",
            "run",
        ]
        if platform:
            docker_cmd += ["--platform", platform]
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
    elif env["kind"] in ["pixi", "uv"]:
        env_cmd = []
        if "name" in env:
            env_cmd = ["--environment", env["name"]]
        cmd = [env["kind"], "run"] + env_cmd + cmd
        if verbose:
            typer.echo(f"Running command: {cmd}")
        try:
            subprocess.check_call(cmd, cwd=wdir)
        except subprocess.CalledProcessError:
            raise_error(f"Failed to run in {env['kind']} environment")
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
        try:
            subprocess.check_call(
                ["Rscript", "-e", "'renv::restore()'"], cwd=wdir
            )
        except subprocess.CalledProcessError:
            raise_error("Failed to check renv")
        try:
            subprocess.check_call(cmd, cwd=wdir)
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
    if calkit.check_dep_exists("pipx"):
        cmd = ["pipx", "upgrade", "calkit-python"]
    elif calkit.check_dep_exists("uv"):
        cmd = [
            "uv",
            "pip",
            "install",
            "--system",
            "--upgrade",
            "calkit-python",
        ]
    else:
        cmd = ["pip", "install", "--upgrade", "calkit-python"]
    subprocess.run(cmd)


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
