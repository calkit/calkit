"""Tests for the ``conda`` module."""

import os
import subprocess

import pytest

import calkit
from calkit.conda import _check_list, _check_single, check_env

ENV_NAME = "main"


def test_check_single():
    assert _check_single("python=3.12", "python=3.12.18", conda=True)
    assert _check_single("python=3", "python=3.12.18", conda=True)
    assert _check_single("python=3.12.18", "python=3.12.18", conda=True)
    assert _check_single("python>=3.12,<3.13", "python==3.12.18", conda=False)


def test_check_list():
    installed = ["python=3.12.1", "numpy=1.0.11"]
    assert _check_list("python=3", installed, conda=True)
    assert _check_list("numpy", installed, conda=True)
    assert not _check_list("pandas", installed, conda=True)
    installed = ["python==3.12.1", "numpy==1.0.11"]
    assert _check_list("python>=3", installed, conda=False)
    assert _check_list("numpy", installed, conda=False)
    assert not _check_list("pandas", installed, conda=False)


def delete_env(name: str):
    subprocess.check_call(["mamba", "env", "remove", "-y", "-n", name])


@pytest.fixture
def conda_env_name():
    name = calkit.to_kebab_case(os.path.basename(os.getcwd())) + "-" + ENV_NAME
    yield name
    # Teardown code
    delete_env(name)


def test_check_env(tmp_dir, conda_env_name):
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["dvc", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "-n",
            ENV_NAME,
            "python",
            "pip",
            "--pip",
            "pxl",
        ]
    )
    res = check_env()
    assert not res.env_exists
    res = check_env()
    assert res.env_exists
    assert not res.env_needs_export
    assert not res.env_needs_rebuild
    # Now let's update the env spec so it needs a rebuild
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "--overwrite",
            "-n",
            ENV_NAME,
            "python=3.11.0",
            "pip",
            "--pip",
            "pxl",
        ]
    )
    res = check_env()
    assert res.env_exists
    assert not res.env_needs_export
    assert res.env_needs_rebuild
    res = check_env()
    assert not res.env_needs_rebuild
    # Check relaxed mode, where we allow dependencies to be in either the pip
    # or conda section
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "--overwrite",
            "-n",
            ENV_NAME,
            "python=3.11.0",
            "pip",
            "sqlalchemy",
        ]
    )
    subprocess.check_call(
        [
            "conda",
            "run",
            "-n",
            ENV_NAME,
            "pip",
            "install",
            "--upgrade",
            "sqlalchemy",
        ]
    )
    res = check_env()
    assert res.env_needs_rebuild
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "--overwrite",
            "-n",
            ENV_NAME,
            "python=3.11.0",
            "pip",
            "sqlalchemy",
        ]
    )
    res = check_env(relaxed=True)
    assert not res.env_needs_rebuild
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "--overwrite",
            "-n",
            ENV_NAME,
            "python=3.11.0",
            "pip",
            "--pip",
            "sqlalchemy",
        ]
    )
    res = check_env(relaxed=True)
    assert not res.env_needs_rebuild
    # Make sure we can handle other ways of specifying versions
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "--overwrite",
            "-n",
            ENV_NAME,
            "python=3.12",
            "--pip",
            "numpy>=1",
        ]
    )
    res = check_env()
    assert res.env_needs_rebuild
    res = check_env()
    assert not res.env_needs_export
    assert not res.env_needs_rebuild
