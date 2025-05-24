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
    subprocess.check_call(["conda", "env", "remove", "-y", "-n", name])


@pytest.fixture
def conda_env_name():
    name = calkit.to_kebab_case(os.path.basename(os.getcwd())) + "-" + ENV_NAME
    yield name
    # Teardown code
    delete_env(name)


def test_check_env(tmp_dir, conda_env_name):
    subprocess.check_call(["calkit", "init"])
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
    assert res.env_needs_export
    assert res.env_needs_rebuild
    res = check_env()
    assert not res.env_needs_rebuild
    assert not res.env_needs_export
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
            conda_env_name,
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


@pytest.fixture
def conda_env_prefix():
    prefix = ".conda-envs/my-conda-env"
    yield prefix
    subprocess.check_call(["conda", "env", "remove", "-y", "--prefix", prefix])


def test_check_prefix_env(tmp_dir, conda_env_prefix):
    subprocess.check_call(["calkit", "init"])
    # Test we can use a local prefix
    subprocess.check_call(
        [
            "calkit",
            "new",
            "conda-env",
            "-n",
            "my-conda-env",
            "python=3.12",
            "--prefix",
            conda_env_prefix,
        ]
    )
    res = check_env()
    assert not res.env_exists
    assert res.env_needs_export
    assert os.path.isfile(os.path.join(conda_env_prefix, "env-export.yml"))
    res = check_env()
    assert res.env_exists
    # Env will need to be exported a second time since we save it inside the
    # prefix folder, so the mtime will be slightly after creation of the
    # initial environment
    assert res.env_needs_export
    assert not res.env_needs_rebuild
    # Now the env should be exported okay
    res = check_env()
    assert res.env_exists
    assert not res.env_needs_export
    assert not res.env_needs_rebuild
    subprocess.check_call(
        ["calkit", "xenv", "-n", "my-conda-env", "python", "--version"]
    )
    # Test that we can add a new dependency
    with open("environment.yml") as f:
        env = calkit.ryaml.load(f)
    env["dependencies"].append("requests")
    with open("environment.yml", "w") as f:
        calkit.ryaml.dump(env, f)
    res = check_env()
    assert res.env_exists
    assert res.env_needs_export
    assert res.env_needs_rebuild
    subprocess.check_call(
        [
            "calkit",
            "xenv",
            "-n",
            "my-conda-env",
            "python",
            "-c",
            "import requests",
        ]
    )
    # Test that we can specify --wdir
    os.makedirs("subdir")
    subprocess.check_call(
        [
            "calkit",
            "xenv",
            "--wdir",
            "subdir",
            "-n",
            "my-conda-env",
            "python",
            "-c",
            "import requests",
        ]
    )
