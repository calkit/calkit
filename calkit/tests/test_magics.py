"""Tests for ``calkit.magics``."""

import os
import shutil
import subprocess

import calkit


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
    # Check DVC stages make sense
    with open("dvc.yaml") as f:
        pipeline = calkit.ryaml.load(f)
    script = ".calkit/notebook-stages/get-data/script.py"
    deps = pipeline["stages"]["get-data"]["deps"]
    assert script in deps
    # Check Calkit metadata makes sense
    ck_info = calkit.load_calkit_info()
    figs = ck_info["figures"]
    fig = figs[0]
    assert fig["path"] == "figures/plot.png"
    assert fig["title"] == "A plot of the data"
    assert fig["description"] == "This is a plot of the data."
    assert fig["stage"] == "plot-fig"
