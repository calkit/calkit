"""The command line interface."""

import os
import pty
import subprocess
import sys

import typer
from typing_extensions import Annotated, Optional

import calkit

from . import config
from .dvc import configure_remote, set_remote_auth

app = typer.Typer()
config_app = typer.Typer()
app.add_typer(config_app, name="config", help="Configure Calkit.")


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
    print(getattr(cfg, key))


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


@app.command(name="server")
def run_server():
    import uvicorn

    # Start jupyter server in this directory if one doesn't exist
    # We need to enable all origins so we can embed it in an iframe
    servers = calkit.jupyter.get_servers()
    wdirs = [server.wdir for server in servers]
    if os.getcwd() not in wdirs:
        calkit.jupyter.start_server()
    uvicorn.run(
        "calkit.server:app",
        port=8866,
        host="localhost",
        reload=True,
        reload_dirs=[os.path.dirname(__file__)],
    )


def run() -> None:
    app()
