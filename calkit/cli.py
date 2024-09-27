"""The command line interface."""

from __future__ import annotations

import os
import pty
import subprocess
import sys

import git
import typer
from typing_extensions import Annotated, Optional

from calkit.core import ryaml

from . import config
from .dvc import configure_remote, set_remote_auth

app = typer.Typer()
config_app = typer.Typer()
new_app = typer.Typer()
app.add_typer(config_app, name="config", help="Configure Calkit.")
app.add_typer(new_app, name="new", help="Add new Calkit object.")


@config_app.command(name="set")
def set_config_value(key: str, value: str):
    try:
        cfg = config.read()
        cfg = config.Settings.model_validate(cfg.model_dump() | {key: value})
        # Kind of a hack for setting the password computed field
        # Types have been validated above, so this won't hurt to do again
        setattr(cfg, key, value)
    except FileNotFoundError:
        # TODO: This fails if we try to set password before any config has
        # been written
        # Username is fine
        cfg = config.Settings.model_validate({key: value})
    cfg.write()


@config_app.command(name="get")
def get_config_value(key: str) -> None:
    cfg = config.read()
    val = getattr(cfg, key)
    if val is not None:
        print(val)
    else:
        print()


@config_app.command(name="setup-remote")
def setup_remote():
    configure_remote()
    set_remote_auth()


@app.command(name="status")
def get_status():
    """Get a unified Git and DVC status."""

    def print_sep(name: str):
        print(f"------------ {name} ------------")

    print_sep("Code")
    if os.name == "nt":
        subprocess.call(["git", "status"])
        print()
        print_sep("data")
        subprocess.call(["dvc", "status"])
    else:
        pty.spawn(["git", "status"], lambda fd: os.read(fd, 1024))
        print()
        print_sep("Data")
        pty.spawn(["dvc", "status"], lambda fd: os.read(fd, 1024))


@app.command(name="add")
def add(paths: list[str]):
    """Add paths to the repo.

    Code will be added to Git and data will be added to DVC.
    """
    dvc_extensions = [".png", ".h5", ".parquet", ".pickle"]
    dvc_size_thresh_bytes = 1_000_000
    dvc_folders = ["data", "figures"]
    if "." in paths:
        print("ERROR: Cannot add '.' with calkit; use git or dvc")
        sys.exit(1)
    for path in paths:
        if os.path.isdir(path):
            print("ERROR: Cannot add directories with calkit; use git or dvc")
            sys.exit(1)
        # Detect if this file should be tracked with Git or DVC
        # TODO: Add to whatever


@app.command(name="commit")
def commit(
    all: Annotated[Optional[bool], typer.Option("--all", "-a")] = False,
    message: Annotated[Optional[str], typer.Option("--message", "-m")] = None,
):
    """Commit a change to the repo."""
    print(all, message)
    raise NotImplementedError


@new_app.command(name="figure")
def new_figure(
    path: str,
    title: Annotated[str, typer.Option("--title")],
    description: Annotated[str, typer.Option("--desc")] = None,
    commit: Annotated[bool, typer.Option("--commit")] = False,
):
    """Add a new figure to ``calkit.yaml``."""
    if os.path.isfile("calkit.yaml"):
        with open("calkit.yaml") as f:
            ck_info = ryaml.load(f)
    else:
        ck_info = {}
    figures = ck_info.get("figures", [])
    paths = [f.get("path") for f in figures]
    if path in paths:
        raise ValueError(f"Figure at path {path} already exists")
    obj = dict(path=path, title=title)
    if description is not None:
        obj["description"] = description
    figures.append(obj)
    ck_info["figures"] = figures
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    if commit:
        repo = git.Repo()
        repo.git.add("calkit.yaml")
        repo.git.commit(["-m", f"Add figure {path}"])


@new_app.command("question")
def new_question(
    question: str,
    commit: Annotated[bool, typer.Option("--commit")] = False,
):
    if os.path.isfile("calkit.yaml"):
        with open("calkit.yaml") as f:
            ck_info = ryaml.load(f)
    else:
        ck_info = {}
    questions = ck_info.get("questions", [])
    if question in questions:
        raise ValueError("Question already exists")
    if not question.endswith("?"):
        raise ValueError("Questions must end with a question mark")
    questions.append(question)
    ck_info["questions"] = questions
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    if commit:
        repo = git.Repo()
        repo.git.add("calkit.yaml")
        repo.git.commit(["-m", "Add question"])


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
    """A simple wrapper for ``dvc repro``."""
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


def run() -> None:
    app()
