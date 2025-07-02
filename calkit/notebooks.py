"""Functionality for working with notebooks."""

import os
from pathlib import PurePosixPath
from typing import Literal

from calkit.models.io import PathOutput


def get_executed_notebook_path(
    notebook_path: str, to: Literal["html", "notebook"], as_posix: bool = True
) -> str:
    """Return the path of an executed notebook."""
    nb_dir = os.path.dirname(notebook_path)
    nb_fname = os.path.basename(notebook_path)
    if to == "html":
        fname_out = nb_fname.removesuffix(".ipynb") + ".html"
    else:
        fname_out = nb_fname
    # Different output types go to different subdirectories
    subdirs = {"html": "html", "notebook": "executed"}
    p = os.path.join(".calkit", "notebooks", subdirs[to], nb_dir, fname_out)
    if as_posix:
        p = PurePosixPath(p).as_posix()
    return p


def get_cleaned_notebook_path(path: str, as_posix: bool = True) -> str:
    """Return the path of a cleaned notebook."""
    p = os.path.join(".calkit", "notebooks", "cleaned", path)
    if as_posix:
        p = PurePosixPath(p).as_posix()
    return p


def declare_notebook(
    path: str,
    stage_name: str,
    environment_name: str,
    inputs: list[str] = [],
    outputs: list[str | PathOutput] = [],
    title: str | None = None,
    description: str | None = None,
    html_storage: Literal["git", "dvc"] | None = "dvc",
    executed_ipynb_storage: Literal["git", "dvc"] | None = "dvc",
    cleaned_ipynb_storage: Literal["git", "dvc"] | None = "git",
):
    """Declare a notebook as part of the current project."""
    # TODO: If pipeline is running, just check that we are running in the
    # correct environment and that the notebook is in the correct location?
    # TODO: Don't do anything if the pipeline is currently running, since this
    # is meant to be run outside of the pipeline
    # Ensure we find the project root (where .git is) and work from there
    # TODO: Check that this content exists in this notebook
    # TODO: Check that the specified environment exists
    # TODO: Change to the correct working directory?
    pass
