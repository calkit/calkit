"""Tests for ``calkit.magics``."""

import os
import shutil
import subprocess
import sys

import pytest

import calkit


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "Slowest test in the suite and the Windows critical path: it runs "
        "four notebook stages, each spawning 'dvc stage add', 'dvc repro', "
        "and a 'calkit xenv' subprocess, which Windows is worst at. The "
        "magic itself is platform-independent enough that passing on Linux "
        "is taken as passing. Note this leaves _posix_path, the one piece "
        "of it that exists for Windows, covered only by Linux runs."
    ),
)
def test_stage(tmp_dir):
    # Test the stage magic
    # Run git and dvc init in the temp dir
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["dvc", "init"])
    # Create a new uv venv for this notebook to run in
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "--name",
            "py1",
            "--path",
            "requirements.txt",
            "pandas",
            "plotly",
            "pyarrow",
            "kaleido",
            "ipykernel",
        ]
    )
    # Add calkit to this environment via its directory
    # To to this we need to know the pytest working directory
    wdir = os.path.dirname(os.path.abspath(calkit.__file__))
    calkit_dir = os.path.abspath(os.path.join(wdir, ".."))
    print("CWD:", os.getcwd())
    print("Calkit dir:", calkit_dir)
    subprocess.check_call(
        ["calkit", "xenv", "-n", "py1", "uv", "pip", "install", calkit_dir]
    )
    # Copy in a test notebook and run it
    nb_fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "test", "pipeline.ipynb"
    )
    shutil.copy(nb_fpath, "notebook.ipynb")
    subprocess.check_call(
        [
            "calkit",
            "xenv",
            "-n",
            "py1",
            "jupyter",
            "nbconvert",
            "--execute",
            "notebook.ipynb",
            "--to",
            "html",
        ]
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
