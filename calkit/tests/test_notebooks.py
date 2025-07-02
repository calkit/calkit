"""Tests for ``calkit.notebooks``."""

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
