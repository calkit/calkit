"""Functionality for working with notebooks."""

import os
from typing import Literal


def get_executed_notebook_path(
    notebook_path: str, to: Literal["html", "notebook"]
) -> str:
    """Return the path of an executed notebook."""
    nb_dir = os.path.dirname(notebook_path)
    nb_fname = os.path.basename(notebook_path)
    if to == "html":
        fname_out = nb_fname.removesuffix(".ipynb") + ".html"
    else:
        fname_out = nb_fname
    return os.path.join(".calkit", "notebooks", "executed", nb_dir, fname_out)


def get_cleaned_notebook_path(path: str) -> str:
    """Return the path of a cleaned notebook."""
    return os.path.join(".calkit", "notebooks", "cleaned", path)
