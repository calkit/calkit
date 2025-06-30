"""Functionality for working with notebooks."""

import os
from pathlib import PurePosixPath
from typing import Literal


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
