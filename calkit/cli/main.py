"""Main CLI app."""

from __future__ import annotations

import os
import subprocess

import typer
from typing_extensions import Annotated, Optional

import calkit
from calkit.cli import print_sep, run_cmd
from calkit.cli.config import config_app
from calkit.cli.list import list_app
from calkit.cli.new import new_app
from calkit.cli.notebooks import notebooks_app

app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=True,
    context_settings=dict(help_option_names=["-h", "--help"]),
    pretty_exceptions_show_locals=False,
)
app.add_typer(config_app, name="config", help="Configure Calkit.")
app.add_typer(
    new_app, name="new", help="Add new Calkit object (to calkit.yaml)."
)
app.add_typer(notebooks_app, name="nb", help="Work with Jupyter notebooks.")
app.add_typer(list_app, name="list", help="List Calkit objects.")


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", help="Show version and exit."),
    ] = False,
):
    if version:
        typer.echo(calkit.__version__)
        raise typer.Exit()


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
    if to is not None and to not in ["git", "dvc"]:
        typer.echo(f"Invalid option for 'to': {to}")
        raise typer.Exit(1)
    # Ensure autostage is enabled for DVC
    subprocess.call(["dvc", "config", "core.autostage", "true"])
    subprocess.call(["git", "add", ".dvc/config"])
    if to is not None:
        subprocess.call([to, "add"] + paths)
    else:
        dvc_extensions = [
            ".png",
            ".h5",
            ".parquet",
            ".pickle",
            ".mp4",
            ".avi",
            ".webm",
            ".pdf",
        ]
        dvc_size_thresh_bytes = 1_000_000
        if "." in paths and to is None:
            typer.echo("Cannot add '.' with calkit; use git or dvc")
            raise typer.Exit(1)
        if to is None:
            for path in paths:
                if os.path.isdir(path):
                    typer.echo("Cannot auto-add directories; use git or dvc")
                    raise typer.Exit(1)
        for path in paths:
            # Detect if this file should be tracked with Git or DVC
            if os.path.splitext(path)[-1] in dvc_extensions:
                typer.echo(f"Adding {path} to DVC per its extension")
                subprocess.call(["dvc", "add", path])
                continue
            if os.path.getsize(path) > dvc_size_thresh_bytes:
                typer.echo(
                    f"Adding {path} to DVC since it's greater than 1 MB"
                )
                subprocess.call(["dvc", "add", path])
                continue
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
    cmd = ["git", "commit"]
    if all:
        cmd.append("-a")
    if message:
        cmd += ["-m", message]
    subprocess.call(cmd)
    if push_commit:
        push()


@app.command(name="pull", help="Pull with both Git and DVC.")
def pull():
    typer.echo("Git pulling")
    subprocess.call(["git", "pull"])
    typer.echo("DVC pulling")
    subprocess.call(["dvc", "pull"])


@app.command(name="push", help="Push with both Git and DVC.")
def push():
    typer.echo("Pushing to Git remote")
    subprocess.call(["git", "push"])
    typer.echo("Pushing to DVC remote")
    subprocess.call(["dvc", "push"])


@app.command(name="server", help="Run the local server.")
def run_server():
    import uvicorn

    uvicorn.run(
        "calkit.server:app",
        port=8866,
        host="localhost",
        reload=True,
        reload_dirs=[os.path.dirname(__file__)],
    )


@app.command(
    name="run",
    add_help_option=False,
    help="Run DVC pipeline (a wrapper for `dvc repro`).",
)
def run_dvc_repro(
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
    """A simple wrapper for ``dvc repro`` that will automatically create any
    necessary Calkit objects from stage metadata.
    """
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
    subprocess.call(["dvc", "repro"] + args)
    # Now parse stage metadata for calkit objects
    if not os.path.isfile("dvc.yaml"):
        typer.echo("No dvc.yaml file found")
        raise typer.Exit(1)
    objects = []
    with open("dvc.yaml") as f:
        pipeline = calkit.ryaml.load(f)
        for stage_name, stage_info in pipeline.get("stages", {}).items():
            ckmeta = stage_info.get("meta", {}).get("calkit")
            if ckmeta is not None:
                if not isinstance(ckmeta, dict):
                    typer.echo(
                        f"Calkit metadata for {stage_name} is not a dictionary"
                    )
                    typer.Exit(1)
                # Stage must have a single output
                outs = stage_info.get("outs", [])
                if len(outs) != 1:
                    typer.echo(
                        f"Stage {stage_name} does not have exactly one output"
                    )
                    raise typer.Exit(1)
                cktype = ckmeta.get("type")
                if cktype not in ["figure", "dataset", "publication"]:
                    typer.echo(f"Invalid Calkit output type '{cktype}'")
                    raise typer.Exit(1)
                objects.append(
                    dict(path=outs[0]) | ckmeta | dict(stage=stage_name)
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
    shell: Annotated[
        bool,
        typer.Option(
            "--shell",
            help="Whether or not to execute the command in shell mode.",
        ),
    ] = False,
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
            cmd.split() if not shell else cmd,
            stderr=subprocess.PIPE if not show_stderr else None,
            stdout=subprocess.PIPE if not show_stdout else None,
            shell=shell,
        )
    input(message + " (press enter to confirm): ")
    typer.echo("Done")
