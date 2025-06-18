"""Notebooks CLI."""

from __future__ import annotations

import os
import subprocess

import typer
from typing_extensions import Annotated

import calkit.notebooks
from calkit.cli.core import raise_error

notebooks_app = typer.Typer(no_args_is_help=True)


@notebooks_app.command("clean")
def clean_notebook_outputs(path: str):
    """Clean notebook and place a copy in the cleaned notebooks directory.

    This can be useful to use as a preprocessing DVC stage to use a clean
    notebook as a dependency for a stage that caches and executed notebook.
    """
    if os.path.isabs(path):
        raise ValueError("Path must be relative")
    fpath_out = calkit.notebooks.get_cleaned_notebook_path(path)
    folder = os.path.dirname(fpath_out)
    os.makedirs(folder, exist_ok=True)
    fpath_out = os.path.abspath(fpath_out)
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
def execute_notebook(
    path: str,
    env_name: Annotated[
        str,
        typer.Option(
            "--environment",
            "-e",
            help="Environment name in which to run the notebook.",
        ),
    ],
    to: Annotated[
        str, typer.Option("--to", help="Output format ('html' or 'notebook').")
    ] = "notebook",
    no_check: Annotated[
        bool,
        typer.Option(
            "--no-check", help="Do not check environment before executing."
        ),
    ] = False,
):
    """Execute notebook and place a copy in the relevant directory.

    This can be useful to use as a preprocessing DVC stage to use a clean
    notebook as a dependency for a stage that caches and executed notebook.
    """
    from calkit.cli.main import run_in_env

    if os.path.isabs(path):
        raise ValueError("Path must be relative")
    try:
        fpath_out = calkit.notebooks.get_executed_notebook_path(
            notebook_path=path,
            to=to,  # type: ignore
        )
    except ValueError:
        raise_error(f"Invalid output format: '{to}'")
    folder = os.path.dirname(fpath_out)
    os.makedirs(folder, exist_ok=True)
    fpath_out = os.path.abspath(fpath_out)
    cmd = [
        "jupyter",
        "nbconvert",
        path,
        "--execute",
        "--to",
        to,
        "--output",
        fpath_out,
    ]
    run_in_env(cmd=cmd, env_name=env_name, no_check=no_check)
