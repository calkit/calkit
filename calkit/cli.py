"""The command line interface."""

from __future__ import annotations

import os
import pty
import subprocess
import sys

import git
import typer
from typing_extensions import Annotated, Optional

import calkit
from calkit.core import ryaml

from . import config
from .dvc import configure_remote, set_remote_auth

app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=True,
    context_settings=dict(help_option_names=["-h", "--help"]),
)
config_app = typer.Typer(no_args_is_help=True)
new_app = typer.Typer(no_args_is_help=True)
notebooks_app = typer.Typer(no_args_is_help=True)
app.add_typer(config_app, name="config", help="Configure Calkit.")
app.add_typer(
    new_app, name="new", help="Add new Calkit object (to calkit.yaml)."
)
app.add_typer(notebooks_app, name="nb", help="Work with Jupyter notebooks.")


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
        width = 66
        txt_width = len(name) + 2
        buffer_width = (width - txt_width) // 2
        buffer = "-" * buffer_width
        typer.echo(f"{buffer} {name} {buffer}")

    def run_cmd(cmd: list[str]):
        if os.name == "nt":
            subprocess.call(cmd)
        else:
            pty.spawn(cmd, lambda fd: os.read(fd, 1024))

    print_sep("Code (Git)")
    run_cmd(["git", "status"])
    typer.echo()
    print_sep("Data (DVC)")
    run_cmd(["dvc", "data", "status"])
    typer.echo()
    print_sep("Pipeline (DVC)")
    run_cmd(["dvc", "status"])


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


@new_app.command(name="figure")
def new_figure(
    path: str,
    title: Annotated[str, typer.Option("--title")],
    description: Annotated[str, typer.Option("--desc")] = None,
    commit: Annotated[bool, typer.Option("--commit")] = False,
):
    """Add a new figure."""
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
    """Add a new question."""
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


@new_app.command("notebook")
def new_notebook(
    path: Annotated[str, typer.Argument(help="Notebook path (relative)")],
    title: Annotated[str, typer.Option("--title")],
    description: Annotated[str, typer.Option("--desc")] = None,
    commit: Annotated[bool, typer.Option("--commit")] = False,
):
    """Add a new notebook."""
    if os.path.isabs(path):
        raise ValueError("Path must be relative")
    if not os.path.isfile(path):
        raise ValueError("Path is not a file")
    if not path.endswith(".ipynb"):
        raise ValueError("Path does not have .ipynb extension")
    # TODO: Add option to create stages that run `calkit nb clean` and
    # `calkit nb execute`
    if os.path.isfile("calkit.yaml"):
        with open("calkit.yaml") as f:
            ck_info = ryaml.load(f)
    else:
        ck_info = {}
    notebooks = ck_info.get("notebooks", [])
    paths = [f.get("path") for f in notebooks]
    if path in paths:
        raise ValueError(f"Notebook at path {path} already exists")
    obj = dict(path=path, title=title)
    if description is not None:
        obj["description"] = description
    notebooks.append(obj)
    ck_info["notebooks"] = notebooks
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    if commit:
        repo = git.Repo()
        repo.git.add("calkit.yaml")
        repo.git.commit(["-m", f"Add notebook {path}"])


@notebooks_app.command("clean")
def clean_notebook_outputs(path: str):
    """Clean notebook and place a copy in the cleaned notebooks directory.

    This can be useful to use as a preprocessing DVC stage to use a clean
    notebook as a dependency for a stage that caches and executed notebook.
    """
    if os.path.isabs(path):
        raise ValueError("Path must be relative")
    fpath_out = os.path.join(".calkit", "notebooks", "cleaned", path)
    folder = os.path.dirname(fpath_out)
    os.makedirs(folder, exist_ok=True)
    subprocess.call(
        [
            "jupyter",
            "nbconvert",
            path,
            "--clear-output",
            "--to",
            "notebook",
            "--output",
            fpath_out,
        ]
    )


@notebooks_app.command("execute")
def execute_notebook(path: str):
    """Execute notebook and place a copy in the executed notebooks directory.

    This can be useful to use as a preprocessing DVC stage to use a clean
    notebook as a dependency for a stage that caches and executed notebook.
    """
    if os.path.isabs(path):
        raise ValueError("Path must be relative")
    fpath_out = os.path.join(".calkit", "notebooks", "executed", path)
    folder = os.path.dirname(fpath_out)
    os.makedirs(folder, exist_ok=True)
    subprocess.call(
        [
            "jupyter",
            "nbconvert",
            path,
            "--execute",
            "--to",
            "notebook",
            "--output",
            fpath_out,
        ]
    )


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
