"""Main CLI app."""

from __future__ import annotations

import csv
import glob
import os
import platform as _platform
import subprocess
import sys
import time

import dotenv
import dvc.repo
import git
import typer
from dvc.exceptions import NotDvcRepoError
from git.exc import InvalidGitRepositoryError
from typing_extensions import Annotated, Optional

import calkit
from calkit.cli import print_sep, raise_error, run_cmd, warn
from calkit.cli.check import check_app, check_conda_env, check_docker_env
from calkit.cli.config import config_app
from calkit.cli.import_ import import_app
from calkit.cli.list import list_app
from calkit.cli.new import new_app
from calkit.cli.notebooks import notebooks_app
from calkit.cli.office import office_app
from calkit.cli.update import update_app
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
    dvc_cmd = ["dvc", "init"]
    if force:
        dvc_cmd.append("-f")
    subprocess.run(dvc_cmd)
    # TODO: Initialize `calkit.yaml`
    # TODO: Initialize `dvc.yaml`
    # TODO: Add a sane .gitignore file
    # TODO: Add a sane LICENSE file?


@app.command(name="clone")
def clone(
    url: Annotated[str, typer.Argument(help="Repo URL.")],
    location: Annotated[
        str,
        typer.Argument(
            help="Location to clone to (default will be ./{repo_name})"
        ),
    ] = None,
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
            subprocess.check_call(["dvc", "pull"])
        except subprocess.CalledProcessError:
            raise_error("Failed to pull from DVC remote(s)")


@app.command(name="status")
def get_status():
    """Get a unified Git and DVC status."""
    print_sep("Code (Git)")
    run_cmd(["git", "status"])
    typer.echo()
    print_sep("Data (DVC)")
    run_cmd(["dvc", "data", "status"])
    typer.echo()
    print_sep("Pipeline (DVC)")
    run_cmd(["dvc", "status"])


@app.command(name="diff")
def diff():
    """Get a unified Git and DVC diff."""
    print_sep("Code (Git)")
    run_cmd(["git", "diff"])
    print_sep("Pipeline (DVC)")
    run_cmd(["dvc", "diff"])


@app.command(name="add")
def add(
    paths: list[str],
    commit_message: Annotated[
        str,
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
        str,
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
    subprocess.call(["dvc", "config", "core.autostage", "true"])
    subprocess.call(["git", "add", ".dvc/config"])
    dvc_paths = [obj.get("path") for obj in dvc_repo.ls(".", dvc_only=True)]
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
            for changed_file in [d.a_path for d in repo.index.diff(None)]:
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
                subprocess.call(["dvc", "add", path])
            elif os.path.splitext(path)[-1] in DVC_EXTENSIONS:
                typer.echo(f"Adding {path} to DVC per its extension")
                subprocess.call(["dvc", "add", path])
            elif calkit.get_size(path) > DVC_SIZE_THRESH_BYTES:
                typer.echo(
                    f"Adding {path} to DVC since it's greater than 1 MB"
                )
                subprocess.call(["dvc", "add", path])
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
    to: Annotated[
        str,
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
    if message is None:
        typer.echo("No message provided; entering interactive mode")
        typer.echo("Creating a commit including the following paths:")
        for path in calkit.git.get_staged_files():
            typer.echo(f"- {path}")
        typer.echo("Please provide a message describing the changes.")
        typer.echo("Example: Add new data to data/raw")
        message = typer.prompt("Message")
    commit(all=True if paths is None else False, message=message)
    if not no_push:
        push()


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
        subprocess.check_call(["dvc", "pull"])
    except subprocess.CalledProcessError:
        raise_error("DVC pull failed")


@app.command(name="push")
def push(
    no_check_auth: Annotated[bool, typer.Option("--no-check-auth")] = False,
):
    """Push with both Git and DVC."""
    typer.echo("Pushing to Git remote")
    try:
        subprocess.check_call(["git", "push"])
    except subprocess.CalledProcessError:
        raise_error("Git push failed")
    typer.echo("Pushing to DVC remote")
    if not no_check_auth:
        # Check that our dvc remotes all have our DVC token set for them
        remotes = calkit.dvc.get_remotes()
        for name, url in remotes.items():
            if name == "calkit" or name.startswith("calkit:"):
                typer.echo(f"Checking authentication for DVC remote: {name}")
                calkit.dvc.set_remote_auth(remote_name=name)
    try:
        subprocess.check_call(["dvc", "push"])
    except subprocess.CalledProcessError:
        raise_error("DVC push failed")


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
        raise_error(e)
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
        subprocess.check_call(["dvc", "repro"] + args)
    except subprocess.CalledProcessError:
        raise_error("DVC pipeline failed")
    # Now parse stage metadata for calkit objects
    if not os.path.isfile("dvc.yaml"):
        raise_error("No dvc.yaml file found")
    objects = []
    with open("dvc.yaml") as f:
        pipeline = calkit.ryaml.load(f)
        if pipeline is None:
            raise_error("Pipeline is empty")
        for stage_name, stage_info in pipeline.get("stages", {}).items():
            ckmeta = stage_info.get("meta", {}).get("calkit")
            if ckmeta is not None:
                if not isinstance(ckmeta, dict):
                    raise_error(
                        f"Calkit metadata for {stage_name} is not a dictionary"
                    )
                # Stage must have a single output
                outs = stage_info.get("outs", [])
                if len(outs) != 1:
                    raise_error(
                        f"Stage {stage_name} does not have exactly one output"
                    )
                cktype = ckmeta.get("type")
                if cktype not in [
                    "figure",
                    "dataset",
                    "publication",
                    "notebook",
                ]:
                    raise_error(f"Invalid Calkit output type '{cktype}'")
                if isinstance(outs[0], str):
                    path = outs[0]
                else:
                    path = str(list(outs[0].keys())[0])
                objects.append(
                    dict(path=path) | ckmeta | dict(stage=stage_name)
                )
    # Now that we've extracted Calkit objects from stage metadata, we can put
    # them into the calkit.yaml file, overwriting objects with the same path
    ck_info = calkit.load_calkit_info()
    for obj in objects:
        cktype = obj.pop("type")
        cktype_plural = cktype + "s"
        existing = ck_info.get(cktype_plural, [])
        new = []
        added = False
        for ex_obj in existing:
            if ex_obj.get("path") == obj["path"]:
                typer.echo(f"Updating {cktype} {ex_obj['path']}")
                new.append(obj)
                added = True
            else:
                new.append(ex_obj)
        if not added:
            typer.echo(f"Adding new {cktype} {obj['path']}")
            new.append(obj)
        ck_info[cktype_plural] = new
    if not dry:
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        run_cmd(["git", "add", "calkit.yaml"])


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
    cmd: Annotated[str, typer.Option("--cmd", help="Command to run.")] = None,
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
        str,
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
        str,
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
    if env_name not in envs:
        raise_error(f"Environment '{env_name}' does not exist")
    env = envs[env_name]
    image_name = env.get("image", env_name)
    docker_wdir = env.get("wdir", "/work")
    docker_wdir_mount = docker_wdir
    if wdir is not None:
        docker_wdir = os.path.join(docker_wdir, wdir)
    shell = env.get("shell", "sh")
    platform = env.get("platform")
    if env["kind"] == "docker":
        if "image" not in env:
            raise_error("Image must be defined for Docker environments")
        if "path" in env and not no_check:
            check_docker_env(
                tag=env["image"],
                fpath=env["path"],
                platform=env.get("platform"),
                deps=env.get("deps", []),
                quiet=True,
            )
        shell_cmd = _to_shell_cmd(cmd)
        docker_cmd = [
            "docker",
            "run",
        ]
        if platform:
            docker_cmd += ["--platform", platform]
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
                env_fpath=env["path"], relaxed=relaxed_check, quiet=True
            )
        cmd = ["conda", "run", "-n", conda_env["name"]] + cmd
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
        if verbose:
            typer.echo(f"Raw command: {cmd}")
            typer.echo(f"Shell command: {shell_cmd}")
        create_cmd = (
            ["uv", "venv"] if kind == "uv-venv" else ["python", "-m", "venv"]
        )
        pip_cmd = "pip" if kind == "venv" else "uv pip"
        pip_install_args = "-q"
        if "python" in env and kind == "uv-venv":
            create_cmd += ["--python", env["python"]]
            pip_install_args += f" --python {env['python']}"
        # Check environment
        if not no_check:
            if not os.path.isdir(prefix):
                if verbose:
                    typer.echo(f"Creating {kind} at {prefix}")
                try:
                    subprocess.check_call(create_cmd + [prefix], cwd=wdir)
                except subprocess.CalledProcessError:
                    raise_error(f"Failed to create {kind} at {prefix}")
                # Put a gitignore file in the env dir if one doesn't exist
                if not os.path.isfile(os.path.join(prefix, ".gitignore")):
                    with open(os.path.join(prefix, ".gitignore"), "w") as f:
                        f.write("*\n")
            fname, ext = os.path.splitext(path)
            lock_fpath = fname + "-lock" + ext
            if _platform.system() == "Windows":
                activate_cmd = f"{prefix}\\Scripts\\activate"
            else:
                activate_cmd = f". {prefix}/bin/activate"
            check_cmd = (
                f"{activate_cmd} "
                f"&& {pip_cmd} install {pip_install_args} -r {path} "
                f"&& {pip_cmd} freeze > {lock_fpath} "
                "&& deactivate"
            )
            try:
                if verbose:
                    typer.echo(f"Running command: {check_cmd}")
                subprocess.check_output(
                    check_cmd,
                    shell=True,
                    cwd=wdir,
                    stderr=subprocess.STDOUT if not verbose else None,
                )
            except subprocess.CalledProcessError:
                raise_error(f"Failed to check {kind}")
        # Now run the command
        cmd = f"{activate_cmd} && {shell_cmd} && deactivate"
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
            remote_wdir = env["wdir"]
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
                src_path = remote_wdir + "/" + src_path
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
