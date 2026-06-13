"""Tests for ``calkit.notebooks``."""

import json
import subprocess

import pytest
from git.exc import InvalidGitRepositoryError

import calkit
from calkit.cli.notebooks import set_notebook_kernelspec


def test_set_notebook_kernelspec_preserves_unicode(tmp_path):
    # Regression: on Windows, opening the notebook without encoding="utf-8"
    # read/wrote it as cp1252, corrupting non-ASCII code (e.g. the Greek letter
    # "ν") into mojibake ("Î½") and breaking kernel execution.
    nb_path = tmp_path / "nb.ipynb"
    code = "ν=U * 2radius / Re  # viscosity"
    nb = {
        "cells": [
            {
                "cell_type": "code",
                "source": [code],
                "metadata": {},
                "outputs": [],
            }
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    with open(nb_path, "w", encoding="utf-8") as f:
        json.dump(nb, f)
    set_notebook_kernelspec(
        path=str(nb_path),
        kernel_name="my-kernel",
        display_name="My Kernel",
        language="julia",
    )
    with open(nb_path, "r", encoding="utf-8") as f:
        result = json.load(f)
    assert result["metadata"]["kernelspec"]["name"] == "my-kernel"
    # The Greek nu must survive the round-trip intact (no mojibake).
    assert "".join(result["cells"][0]["source"]) == code
    assert "ν" in "".join(result["cells"][0]["source"])
    # Raw file bytes must not contain the cp1252 mojibake escape for "ν".
    raw = nb_path.read_text(encoding="utf-8")
    assert "\\u00ce" not in raw


def test_declare_notebook(tmp_dir):
    with pytest.raises(InvalidGitRepositoryError):
        calkit.declare_notebook(
            path="my-notebook.ipynb",
            stage_name="my-stage",
            environment_name="my-env",
        )
    subprocess.check_call(["calkit", "init"])
    with open("my-notebook.ipynb", "w") as f:
        f.write(
            """{
                "cells": [],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5
            }"""
        )
    # Create a dummy environment
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "environments": {
                    "my-env": {
                        "kind": "uv-venv",
                        "path": "something.txt",
                    }
                },
            },
            f,
        )
    calkit.declare_notebook(
        path="my-notebook.ipynb",
        stage_name="my-stage",
        environment_name="my-env",
        title="My Notebook",
        description="This is a test notebook",
        inputs=["data.txt"],
        outputs=[],
        always_run=False,
        html_storage=None,
        executed_ipynb_storage=None,
        cleaned_ipynb_storage=None,
    )
    ck_info = calkit.load_calkit_info()
    assert ck_info["notebooks"] == [
        {
            "path": "my-notebook.ipynb",
            "title": "My Notebook",
            "description": "This is a test notebook",
            "stage": "my-stage",
        }
    ]
    stage = ck_info["pipeline"]["stages"]["my-stage"]
    assert stage["kind"] == "jupyter-notebook"
    assert stage["notebook_path"] == "my-notebook.ipynb"
    assert stage["environment"] == "my-env"
    assert stage["inputs"] == ["data.txt"]
    assert "always_run" not in stage
    assert "outputs" not in stage
    assert stage["html_storage"] is None


def test_determine_storage(tmp_dir):
    notebook_path = "small.ipynb"
    with open(notebook_path, "w") as f:
        json.dump(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "metadata": {},
                        "source": ["print('hello')\n"],
                    }
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            },
            f,
        )
    assert calkit.notebooks.determine_storage(notebook_path) == "git"
    assert calkit.notebooks.determine_storage("missing.ipynb") == "dvc"
