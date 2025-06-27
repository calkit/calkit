"""Tests for ``cli.main``."""

import os
import subprocess
import sys

import dvc.repo
import git
import pytest
from dvc.exceptions import NotDvcRepoError
from git.exc import InvalidGitRepositoryError

import calkit
from calkit.cli.main import _to_shell_cmd


def test_run_in_env(tmp_dir):
    # If running on Windows we need to set stdin for the subprocesses to
    # ensure sys.stdin.isatty() is False, otherwise we will run docker with
    # the -it flag, which will fail due to some strangeness with Pytest
    if sys.platform == "win32":
        stdin = subprocess.PIPE
    else:
        stdin = None
    subprocess.check_call("calkit init", shell=True)
    # First create a new Docker environment for this bare project
    subprocess.check_call(
        "calkit new docker-env "
        "--name my-image "
        "--from ubuntu "
        "--add-layer uv "
        '--description "This is a test image"',
        shell=True,
    )
    proc = subprocess.run(
        ["calkit", "xenv", "echo", "sup"],
        shell=False,
        capture_output=True,
        stdin=stdin,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == "sup"
    # Ensure we can modify a local file
    subprocess.run(
        ["calkit", "xenv", "touch", "test.txt"],
        stdin=stdin,
        check=True,
    )
    # Now let's create a 2nd Docker env and make sure we need to call it by
    # name when trying to run
    subprocess.check_call(
        "calkit new docker-env "
        "-n env2 "
        "--image my-image-2 "
        "--path Dockerfile.2 "
        "--from ubuntu "
        "--add-layer miniforge "
        "--add-layer foampy "
        '--description "This is a test image 2"',
        shell=True,
    )
    with pytest.raises(subprocess.CalledProcessError):
        out = (
            subprocess.check_output(
                "calkit xenv echo sup", shell=True, stdin=stdin
            )
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
            ],
            stdin=stdin,
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
        '--description "Just Python."',
        shell=True,
    )
    subprocess.check_call(["calkit", "check", "env", "-n", "py3.10"])
    out = (
        subprocess.check_output(
            "calkit xenv -n py3.10 python --version",
            shell=True,
            stdin=stdin,
        )
        .decode()
        .strip()
    )
    assert out == "Python 3.10.15"
    ck_info = calkit.load_calkit_info()
    env = ck_info["environments"]["py3.10"]
    assert env.get("path") is None
    # Test that we can run a command that changes directory first
    os.makedirs("my-new-dir/another", exist_ok=True)
    out = (
        subprocess.check_output(
            "calkit xenv -n py3.10 --wdir my-new-dir -- ls",
            shell=True,
            stdin=stdin,
        )
        .decode()
        .strip()
    )
    assert out == "another"
    out = (
        subprocess.check_output(
            "calkit xenv -n py3.10 --wdir my-new-dir -- ls ..",
            shell=True,
            stdin=stdin,
        )
        .decode()
        .strip()
    )
    assert "my-new-dir" in out.split("\n")


def test_run_in_venv(tmp_dir):
    subprocess.check_call("calkit init", shell=True)
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
    ck_info = calkit.load_calkit_info_object()
    envs = ck_info.environments
    assert "my-pixi" in envs
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
    cmd = [
        "sh",
        "-c",
        "cd dir1 && ls",
    ]
    good_shell_cmd = 'sh -c "cd dir1 && ls"'
    assert _to_shell_cmd(cmd) == good_shell_cmd


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
    # Check that we can run `calkit add .`
    subprocess.check_call(["calkit", "add", "."])
    # Test the auto commit message feature
    subprocess.check_call(["git", "reset"])
    subprocess.check_call(["calkit", "add", "large.bin", "-M"])
    repo = git.Repo()
    assert repo.head.commit.message.strip() == "Update large.bin"
    subprocess.check_call(["calkit", "add", "src", "-M"])
    assert repo.head.commit.message.strip() == "Add src"
    with open("src/code.py", "w") as f:
        f.write("# This is the new code")
    subprocess.check_call(["calkit", "add", "src/code.py", "-M"])
    assert repo.head.commit.message.strip() == "Update src/code.py"
    with open("data/raw/file2.bin", "wb") as f:
        f.write(os.urandom(2_000_000))
    subprocess.check_call(["calkit", "add", "data", "-M"])
    assert repo.head.commit.message.strip() == "Update data"
    os.makedirs("data2")
    with open("data2/large2.bin", "wb") as f:
        f.write(os.urandom(2_000_000))
    subprocess.check_call(["calkit", "add", "data2", "-M"])
    assert repo.head.commit.message.strip() == "Add data2"


def test_status(tmp_dir):
    subprocess.check_call(["calkit", "status"])
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(["calkit", "new", "status", "in-progress"])
    subprocess.check_call(["calkit", "status"])
    status = calkit.get_latest_project_status()
    assert status is not None
    assert status.status == "in-progress"
    assert not status.message
    subprocess.check_call(
        ["calkit", "new", "status", "completed", "-m", "We're done."]
    )
    subprocess.check_call(["calkit", "status"])
    status = calkit.get_latest_project_status()
    assert status is not None
    assert status.status == "completed"
    assert status.message == "We're done."
    history = calkit.get_project_status_history()
    assert history[-1] == status
    calkit.get_project_status_history()
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(["calkit", "new", "status", "very-cool"])


def test_save(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    repo = git.Repo()
    assert repo.head.commit.message.strip() == "Initialize DVC"
    with open("test.txt", "w") as f:
        f.write("sup")
    subprocess.check_call(["calkit", "save", "-aM", "--no-push"])
    # Check that the last log message was "Add test.txt"
    last_commit_message = repo.head.commit.message.strip()
    assert last_commit_message == "Add test.txt"
    # Update the file
    with open("test.txt", "w") as f:
        f.write("sup sup")
    subprocess.check_call(["calkit", "save", "-aM", "--no-push"])
    # Check that the last log message was "Update test.txt"
    last_commit_message = repo.head.commit.message.strip()
    assert last_commit_message == "Update test.txt"
    # Check that we fail to save if there are two changed files
    with open("test2.txt", "w") as f:
        f.write("sup")
    with open("test3.txt", "w") as f:
        f.write("sup")
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(["calkit", "save", "-aM", "--no-push"])
    with open("test3.txt", "w") as f:
        f.write("sup2")
    subprocess.check_call(
        ["calkit", "save", "-am", "A unique message", "--no-push"]
    )
    last_commit_message = repo.head.commit.message.strip()
    assert last_commit_message == "A unique message"


def test_call_dvc():
    subprocess.check_call(["calkit", "dvc", "--help"])
    subprocess.check_call(["calkit", "dvc", "stage", "--help"])
