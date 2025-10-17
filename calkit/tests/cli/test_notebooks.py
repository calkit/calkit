"""Tests for ``calkit.cli.notebooks``."""

import base64
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
    params1 = {
        "my_value": 5,
        "my_list": [1, 2, 3],
    }
    params2 = {
        "my_dict": {"something": 55.5, "else": "b"},
    }
    subprocess.check_call(
        [
            "calkit",
            "nb",
            "execute",
            "nb-params.ipynb",
            "-e",
            "main",
            "--params-json",
            json.dumps(params1),
            "--params-base64",
            base64.b64encode(json.dumps(params2).encode("utf-8")).decode(
                "utf-8"
            ),
            "--verbose",
        ]
    )
    params = params1 | params2
    with open("params-out.json") as f:
        params_out = json.load(f)
    assert params_out["my_value"] == params["my_value"]
    assert params_out["my_list"] == params["my_list"]
    assert params_out["my_dict"] == params["my_dict"]
    # Test we can execute in the pipeline with params
    pipeline = {
        "stages": {
            "nb-params": {
                "kind": "jupyter-notebook",
                "notebook_path": "nb-params.ipynb",
                "environment": "main",
                "parameters": params,
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
    assert params_out["my_value"] == params["my_value"]
    assert params_out["my_list"] == params["my_list"]
    assert params_out["my_dict"] == params["my_dict"]
    # Test we can patch in a range iteration from project parameters
    project_params = {
        "my_range": {"range": {"start": 1, "stop": 6, "step": 1}},
        "my_project_value": 77,
    }
    pipeline = {
        "stages": {
            "nb-params": {
                "kind": "jupyter-notebook",
                "notebook_path": "nb-params.ipynb",
                "environment": "main",
                "parameters": params
                | {"my_list": "{my_range}", "my_value": "{my_project_value}"},
                "html_storage": None,
            }
        }
    }
    ck_info = calkit.load_calkit_info()
    ck_info["parameters"] = project_params
    ck_info["pipeline"] = pipeline
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    os.remove("params-out.json")
    subprocess.check_call(["calkit", "run"])
    with open("params-out.json") as f:
        params_out = json.load(f)
    assert params_out["my_value"] == project_params["my_project_value"]
    assert params_out["my_list"] == list(range(1, 6))
    assert params_out["my_dict"] == params["my_dict"]


def test_execute_notebook_julia(tmp_dir):
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
        [
            "calkit",
            "new",
            "julia-env",
            "--name",
            "main",
            "--julia",
            "1.11",
            "IJulia",
        ]
    )
    nb_fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "test", "nb-julia.ipynb"
    )
    os.makedirs("notebooks")
    shutil.copy(nb_fpath, "notebooks/main.ipynb")
    subprocess.check_call(
        ["calkit", "nb", "execute", "-e", "main", "notebooks/main.ipynb"]
    )
