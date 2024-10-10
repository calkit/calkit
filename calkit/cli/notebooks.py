"""Notebooks CLI."""

from __future__ import annotations

import os
import subprocess

import typer
from typing_extensions import Annotated

notebooks_app = typer.Typer(no_args_is_help=True)


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
def execute_notebook(
    path: str,
    to: Annotated[
        str, typer.Option("--to", help="Output format ('html' or 'notebook').")
    ] = "notebook",
):
    """Execute notebook and place a copy in the relevant directory.

    This can be useful to use as a preprocessing DVC stage to use a clean
    notebook as a dependency for a stage that caches and executed notebook.
    """
    if os.path.isabs(path):
        raise ValueError("Path must be relative")
    if to == "html":
        subdir = "html"
        fname_out = path.removesuffix(".ipynb") + ".html"
    elif to == "notebook":
        subdir = "executed"
        fname_out = path
    else:
        raise ValueError(f"Invalid output format: '{to}'")
    fpath_out = os.path.join(".calkit", "notebooks", subdir, fname_out)
    folder = os.path.dirname(fpath_out)
    os.makedirs(folder, exist_ok=True)
    subprocess.call(
        [
            "jupyter",
            "nbconvert",
            path,
            "--execute",
            "--to",
            to,
            "--output",
            fpath_out,
        ]
    )
