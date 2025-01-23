"""Tests for ``cli.main``."""

import os
import subprocess

import dvc.repo
import git
import pytest
from dvc.exceptions import NotDvcRepoError
from git.exc import InvalidGitRepositoryError

import calkit
from calkit.cli.main import _to_shell_cmd
from calkit.core import ryaml


def test_run_in_env(tmp_dir):
    subprocess.check_call("git init", shell=True)
    subprocess.check_call("dvc init", shell=True)
    # First create a new Docker environment for this bare project
    subprocess.check_call(
        "calkit new docker-env "
        "--name my-image "
        "--stage build-image "
        "--from ubuntu "
        "--add-layer miniforge "
        "--description 'This is a test image'",
        shell=True,
    )
    subprocess.check_call("calkit run", shell=True)
    out = (
        subprocess.check_output("calkit xenv echo sup", shell=True)
        .decode()
        .strip()
    )
    assert out == "sup"
    # Now let's create a 2nd Docker env and make sure we need to call it by
    # name when trying to run
    subprocess.check_call(
        "calkit new docker-env "
        "-n env2 "
        "--image my-image-2 "
        "--stage build-image-2 "
        "--path Dockerfile.2 "
        "--from ubuntu "
        "--add-layer miniforge "
        "--add-layer foampy "
        "--description 'This is a test image 2'",
        shell=True,
    )
    with open("dvc.yaml") as f:
        pipeline = ryaml.load(f)
    stg = pipeline["stages"]["build-image-2"]
    cmd = stg["cmd"]
    assert "-i Dockerfile.2" in cmd
    subprocess.check_call("calkit run", shell=True)
    with pytest.raises(subprocess.CalledProcessError):
        out = (
            subprocess.check_output("calkit xenv echo sup", shell=True)
            .decode()
            .strip()
        )
    out = (
        subprocess.check_output(
            [
                "calkit",
                "xenv",
                "-n",
                "env2",
                "python",
                "-c",
                "import foampy; print(foampy.__version__)",
            ]
        )
        .decode()
        .strip()
    )
    assert out == "0.0.5"
    # Test that we can create a Docker env with no build stage
    subprocess.check_call(
        "calkit new docker-env "
        "--name py3.10 "
        "--image python:3.10.15-bookworm "
        "--description 'Just Python.'",
        shell=True,
    )
    out = (
        subprocess.check_output(
            "calkit xenv -n py3.10 python --version", shell=True
        )
        .decode()
        .strip()
    )
    assert out == "Python 3.10.15"
    ck_info = calkit.load_calkit_info()
    env = ck_info["environments"]["py3.10"]
    assert env.get("path") is None


def test_run_in_venv(tmp_dir):
    subprocess.check_call("git init", shell=True)
    subprocess.check_call("dvc init", shell=True)
    # Test uv venv
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "uv1",
            "--python",
            "3.13",
            "--no-commit",
            "polars==1.18.0",
        ]
    )
    out = (
        subprocess.check_output(
            [
                "calkit",
                "xenv",
                "-n",
                "uv1",
                "--",
                "python",
                "-c",
                "import polars; print(polars.__version__)",
            ]
        )
        .decode()
        .strip()
    )
    assert out == "1.18.0"
    # Test regular venvs
    subprocess.check_call(
        [
            "calkit",
            "new",
            "venv",
            "-n",
            "venv1",
            "--prefix",
            ".venv1",
            "--path",
            "reqs2.txt",
            "polars==1.17.0",
        ]
    )
    out = (
        subprocess.check_output(
            [
                "calkit",
                "xenv",
                "-n",
                "venv1",
                "--",
                "python",
                "-c",
                "import polars; print(polars.__version__)",
            ]
        )
        .decode()
        .strip()
    )
    assert out == "1.17.0"
    # Test pixi envs
    subprocess.check_call(
        [
            "calkit",
            "new",
            "pixi-env",
            "-n",
            "my-pixi",
            "pandas=2.0.0",
            "--pip",
            "polars==1.16.0",
        ]
    )
    ck_info = calkit.load_calkit_info(as_pydantic=True)
    envs = ck_info.environments
    env = envs["my-pixi"]
    out = (
        subprocess.check_output(
            [
                "calkit",
                "xenv",
                "-n",
                "my-pixi",
                "--",
                "python",
                "-c",
                "import pandas; print(pandas.__version__)",
            ]
        )
        .decode()
        .strip()
    )
    assert out == "2.0.0"


def test_to_shell_cmd():
    cmd = ["python", "-c", "import math; print('hello world')"]
    subprocess.check_call(cmd)
    shell_cmd = _to_shell_cmd(cmd)
    assert shell_cmd == "python -c \"import math; print('hello world')\""
    subprocess.check_call(shell_cmd, shell=True)
    cmd = ["echo", "hello world"]
    subprocess.check_call(cmd)
    shell_cmd = _to_shell_cmd(cmd)
    assert shell_cmd == 'echo "hello world"'
    subprocess.check_call(shell_cmd, shell=True)
    cmd = ["python", "-c", "print('sup')"]
    shell_cmd = _to_shell_cmd(cmd)
    assert shell_cmd == "python -c \"print('sup')\""
    cmd = ["python", "-c", 'print("hello world")']
    shell_cmd = _to_shell_cmd(cmd)
    assert shell_cmd == 'python -c "print(\\"hello world\\")"'
    subprocess.check_call(shell_cmd, shell=True)


def test_add(tmp_dir):
    # Create a text file that should be added to Git
    with open("text.txt", "w") as f:
        f.write("Hi")
    # Create a large-ish binary file that should be added to DVC
    with open("large.bin", "wb") as f:
        f.write(os.urandom(2_000_000))
    # Create a small directory that should be added to Git
    os.makedirs("src")
    with open("src/code.py", "w") as f:
        f.write("import os")
    # Create a large data directory that should be added to DVC
    os.makedirs("data/raw")
    with open("data/raw/file1.bin", "wb") as f:
        f.write(os.urandom(2_000_000))
    # Create a file with an extension that should automatically be added to DVC
    with open("data.parquet", "w") as f:
        f.write("This is a fake parquet file")
    # First, if Git and/or DVC have never been initialized, test that happens?
    with pytest.raises(InvalidGitRepositoryError):
        git.Repo()
    with pytest.raises(NotDvcRepoError):
        dvc.repo.Repo()
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(["calkit", "add", "text.txt"])
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["calkit", "add", "text.txt"])
    assert "text.txt" in calkit.git.get_staged_files()
    subprocess.check_call(["calkit", "add", "large.bin"])
    assert "large.bin.dvc" in calkit.git.get_staged_files()
    assert "large.bin" in calkit.dvc.list_paths()
    subprocess.check_call(["calkit", "add", "src"])
    assert "src/code.py" in calkit.git.get_staged_files()
    subprocess.check_call(["calkit", "add", "data.parquet"])
    assert "data.parquet.dvc" in calkit.git.get_staged_files()
    assert "data.parquet" in calkit.dvc.list_paths()
    subprocess.check_call(["calkit", "add", "data"])
    assert "data.dvc" in calkit.git.get_staged_files()
    assert "data" in calkit.dvc.list_paths()
    # Check that we can't run `calkit add .`
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(["calkit", "add", "."])
