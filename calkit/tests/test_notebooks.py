"""Tests for ``calkit.notebooks``."""

import json
import os
import subprocess

import pytest
from git.exc import InvalidGitRepositoryError

import calkit


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


def test_is_marimo_notebook():
    # What marimo itself writes at the top of every notebook it generates
    generated = (
        "import marimo\n"
        "\n"
        '__generated_with = "0.19.4"\n'
        "app = marimo.App()\n"
        "\n"
        "\n"
        "@app.cell\n"
        "def _():\n"
        "    print(1)\n"
        "    return\n"
    )
    assert calkit.notebooks.is_marimo_notebook(generated)
    # Options in the constructor call, and a license banner ahead of it,
    # don't change the answer
    assert calkit.notebooks.is_marimo_notebook(
        '"""Copyright.\n\nA long banner.\n"""\n'
        "import marimo\n"
        'app = marimo.App(width="medium")\n'
    )
    # A script that merely imports or mentions marimo isn't a notebook, which
    # is the case a plain 'marimo' substring check gets wrong
    for not_a_notebook in [
        "import marimo\nprint('not a notebook')\n",
        "# Convert this to marimo someday\nprint(1)\n",
        '"""Utilities for our marimo apps."""\nimport pandas as pd\n',
        "",
    ]:
        assert not calkit.notebooks.is_marimo_notebook(not_a_notebook)


def test_clean_all_in_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    nb = {
        "cells": [
            {
                "cell_type": "code",
                "metadata": {},
                "execution_count": 1,
                "outputs": [{"output_type": "stream", "text": "4"}],
                "source": "print(2 + 2)",
            }
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    os.makedirs("pub")
    for path in ["analysis.ipynb", "pub/index.ipynb", "shown.ipynb"]:
        with open(path, "w") as f:
            json.dump(nb, f)
    stages = {
        "nb": {"kind": "jupyter-notebook", "notebook_path": "analysis.ipynb"},
        # Quarto rendering a notebook with --execute writes its outputs back
        # into it, so it's cleaned too, from the stage's working directory
        "pub": {
            "kind": "quarto",
            "target_path": "index.ipynb",
            "wdir": "pub",
            "args": ["--execute"],
        },
        # Rendered from the outputs saved in it, so it isn't cleaned
        "shown": {"kind": "quarto", "target_path": "shown.ipynb"},
        "report": {"kind": "quarto", "target_path": "report.qmd"},
        "missing": {"kind": "quarto", "target_path": "gone.ipynb"},
    }
    cleaned = calkit.notebooks.clean_all_in_pipeline(
        ck_info={"pipeline": {"stages": stages}}
    )
    assert cleaned == ["analysis.ipynb", "pub/index.ipynb"]
    with open(".calkit/notebooks/cleaned/pub/index.ipynb") as f:
        assert json.load(f)["cells"][0]["outputs"] == []
