"""Tests for ``calkit.cli.notebooks``."""

import os
import shutil
import subprocess


def test_clean_notebook_outputs(tmp_dir):
    # Copy in a test notebook and run it
    nb_fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "test", "pipeline.ipynb"
    )
    shutil.copy(nb_fpath, "notebook.ipynb")
    subprocess.check_call(["calkit", "nb", "clean", "notebook.ipynb"])
