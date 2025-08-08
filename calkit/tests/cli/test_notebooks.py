"""Tests for ``calkit.cli.notebooks``."""

import json
import os
import shutil
import subprocess

import calkit


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
    # Test we can execute with parameters
    nb_fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "test", "nb-params.ipynb"
    )
    shutil.copy(nb_fpath, "nb-params.ipynb")
    pipeline = {
        "stages": {
            "nb-params": {
                "kind": "jupyter-notebook",
                "notebook_path": "nb-params.ipynb",
                "environment": "main",
                "parameters": {
                    "my_value": 5,
                    "my_list": [1, 2, 3],
                    "my_dict": {"something": 55.5, "else": "b"},
                },
                "html_storage": None,
            }
        }
    }
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = pipeline
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "run"])
    with open("params-out.json") as f:
        params_out = json.load(f)
    assert params_out["my_value"] == 5
    assert params_out["my_list"] == [1, 2, 3]
    assert params_out["my_dict"] == {"something": 55.5, "else": "b"}
