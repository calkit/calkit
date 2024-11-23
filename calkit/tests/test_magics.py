"""Tests for ``calkit.magics``."""

import os
import shutil
import subprocess


def test_stage(tmp_dir):
    # Test the stage magic
    # Run git and dvc init in the temp dir
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["dvc", "init"])
    # Copy in a test notebook and run it
    nb_fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "test", "pipeline.ipynb"
    )
    shutil.copy(nb_fpath, "notebook.ipynb")
    subprocess.check_call(
        ["jupyter", "nbconvert", "--execute", "notebook.ipynb", "--to", "html"]
    )
    # TODO: Check DVC stages make sense
    # TODO: Check Calkit metadata makes sense
