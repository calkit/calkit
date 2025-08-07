"""Tests for ``calkit.cli.notebooks``."""

import os
import shutil
import subprocess


def test_clean_notebook_outputs(tmp_dir):
    # Copy in a test notebook and clean it
    nb_fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "test", "pipeline.ipynb"
    )
    shutil.copy(nb_fpath, "notebook.ipynb")
    subprocess.check_call(["calkit", "nb", "clean", "notebook.ipynb"])


def test_execute_notebook(tmp_dir):
    subprocess.check_call(
        [
            "calkit",
            "new",
            "project",
            ".",
            "-n",
            "cool-project",
            "--title",
            "Cool project",
        ]
    )
    subprocess.check_call(
        ["calkit", "new", "uv-venv", "-n", "main", "ipykernel"]
    )
    nb_fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "test", "nb-subdir.ipynb"
    )
    os.makedirs("notebooks/results")
    shutil.copy(nb_fpath, "notebooks/main.ipynb")
    subprocess.check_call(
        ["calkit", "nb", "execute", "notebooks/main.ipynb", "-e", "main"]
    )
    assert os.path.isfile("notebooks/results/something.txt")
    os.makedirs("results")
    shutil.copy("notebooks/main.ipynb", "main.ipynb")
    subprocess.check_call(
        ["calkit", "nb", "execute", "main.ipynb", "-e", "main"]
    )
    assert os.path.isfile("results/something.txt")
