"""Tests for ``cli.main``."""

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pprint import pprint

import dvc.repo
import git
import pytest
from dvc.exceptions import NotDvcRepoError
from git.exc import InvalidGitRepositoryError

import calkit
import calkit.cli.main
from calkit.cli.main import _stage_run_info_from_log_content, _to_shell_cmd


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
        "--image my-image "
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
    # Check that we can pass project env vars into the container
    ck_info = calkit.load_calkit_info()
    ck_info["env_vars"] = {"MY_COOL_ENV_VAR": "my cool value"}
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    p = subprocess.run(
        ["calkit", "xenv", "echo", "$MY_COOL_ENV_VAR"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "my cool value" in p.stdout
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
        .split("\n")[-1]
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


def test_run_in_julia_env(tmp_dir):
    subprocess.check_call("calkit init", shell=True)
    subprocess.check_call(
        [
            "calkit",
            "new",
            "julia-env",
            "-n",
            "my-julia",
            "--julia=1.11",
            "--no-commit",
            "Revise",
            "PkgVersion",
        ]
    )
    out = (
        subprocess.check_output(
            [
                "calkit",
                "xenv",
                "-n",
                "my-julia",
                "--",
                "-e",
                (
                    "using Revise; using PkgVersion; "
                    "println(PkgVersion.Version(Revise))"
                ),
            ]
        )
        .decode()
        .strip()
    )
    # Check that we can run a script with arguments
    with open("julia_script.jl", "w") as f:
        f.write(
            "import PkgVersion; "
            " using Revise; "
            'println("PkgVersion: ", PkgVersion.Version(Revise)); '
            'println("Arg1: ", ARGS[1]); '
            'println("Arg2: ", ARGS[2])'
        )
    out = (
        subprocess.check_output(
            [
                "calkit",
                "xenv",
                "--no-check",
                "-n",
                "my-julia",
                "--verbose",
                "--",
                "julia_script.jl",
                "hello",
                "world",
            ]
        )
        .decode()
        .strip()
    )
    assert "PkgVersion" in out
    assert "Arg1: hello" in out
    assert "Arg2: world" in out


def test_run_in_env_by_path(tmp_dir):
    # Test we can run in an environment by its path
    with open("requirements.txt", "w") as f:
        f.write("requests")
    cmd = [
        "calkit",
        "xenv",
        "-p",
        "requirements.txt",
        "--",
        "python",
        "-c",
        "import requests",
    ]
    subprocess.check_call(cmd)
    ck_info = calkit.load_calkit_info()
    env = ck_info["environments"]["main"]
    assert env["kind"] == "uv-venv"
    assert env["path"] == "requirements.txt"
    subprocess.check_call(cmd)
    # Test with a uv project env
    subprocess.check_call(["uv", "init", "--bare"])
    subprocess.check_call(["uv", "add", "requests"])
    cmd = [
        "calkit",
        "xenv",
        "-p",
        "pyproject.toml",
        "--",
        "python",
        "-c",
        "import requests",
    ]
    subprocess.check_call(cmd)
    ck_info = calkit.load_calkit_info()
    envs = ck_info["environments"]
    assert len(envs) == 2
    env = ck_info["environments"]["uv1"]
    assert env["kind"] == "uv"
    assert env["path"] == "pyproject.toml"
    subprocess.check_call(cmd)
    # Create a pixi env
    subprocess.check_call(["git", "init"])
    subprocess.check_call(
        ["calkit", "new", "pixi-env", "-n", "my-pixi", "pandas"]
    )
    cmd = [
        "calkit",
        "xenv",
        "-p",
        "pixi.toml",
        "python",
        "-c",
        "import pandas",
    ]
    subprocess.check_call(cmd)
    ck_info = calkit.load_calkit_info()
    envs = ck_info["environments"]
    assert len(envs) == 3


def test_run_in_env_detect_default(tmp_dir):
    # Check that if we don't specify an environment, we'll find a default one
    # and add it to the project
    subprocess.check_call(["uv", "init", "--bare"])
    subprocess.check_call(["uv", "add", "requests"])
    cmd = [
        "calkit",
        "xenv",
        "--",
        "python",
        "-c",
        "import requests",
    ]
    subprocess.check_call(cmd)
    ck_info = calkit.load_calkit_info()
    env = ck_info["environments"]["main"]
    assert env["kind"] == "uv"
    assert env["path"] == "pyproject.toml"
    # Check that if we run again, we don't modify calkit.yaml since we already
    # have an environment that matches pyproject.toml
    subprocess.check_call(cmd)
    ck_info_2 = calkit.load_calkit_info()
    assert ck_info == ck_info_2


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
    binary_size = 5_100_000
    with open("large.bin", "wb") as f:
        f.write(os.urandom(binary_size))
    # Create a small directory that should be added to Git
    os.makedirs("src")
    with open("src/code.py", "w") as f:
        f.write("import os")
    # Create a large data directory that should be added to DVC
    os.makedirs("data/raw")
    with open("data/raw/file1.bin", "wb") as f:
        f.write(os.urandom(binary_size))
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
        f.write(os.urandom(binary_size))
    subprocess.check_call(["calkit", "add", "data", "-M"])
    assert repo.head.commit.message.strip() == "Update data"
    os.makedirs("data2")
    with open("data2/large2.bin", "wb") as f:
        f.write(os.urandom(binary_size))
    subprocess.check_call(["calkit", "add", "data2", "-M"])
    assert repo.head.commit.message.strip() == "Add data2"
    subprocess.check_call(["calkit", "add", "--to", "dvc", "large.bin"])


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


def test_run(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        ["calkit", "new", "uv-venv", "-n", "main", "requests"]
    )
    # Test that we can run a Python script
    # Copy script.py from the repo's test directory
    script_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "test", "script.py"
    )
    shutil.copy2(script_path, "script.py")
    subprocess.check_call(
        [
            "calkit",
            "new",
            "python-script-stage",
            "--name",
            "stage-1",
            "--script-path",
            "script.py",
            "-e",
            "main",
            "--output",
            "test.txt",
        ]
    )
    subprocess.check_call(
        ["calkit", "save", "-am", "Create pipeline", "--no-push"]
    )
    out = subprocess.check_output(["calkit", "run"], text=True)
    print(out)
    subprocess.check_call(
        ["calkit", "save", "-am", "Run pipeline", "--no-push"]
    )
    # Test that we can set env vars at the project level
    ck_info = calkit.load_calkit_info()
    ck_info["env_vars"] = {"MY_ENV_VAR": "some-value"}
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open("script.py", "a") as f:
        f.write("\nimport os\nprint(os.environ['MY_ENV_VAR'])")
    out = subprocess.check_output(["calkit", "run"], text=True)
    print(out)
    assert "some-value" in out
    subprocess.check_call(
        ["calkit", "save", "-am", "Run pipeline", "--no-push"]
    )
    # Check we can run for inputs and outputs
    subprocess.check_call(["calkit", "run", "--input", "script.py"])
    subprocess.check_call(["calkit", "run", "--output", "test.txt"])
    # Make sure we can run on a detached head
    repo = git.Repo()
    repo.git.checkout("HEAD^")
    out = subprocess.check_output(["calkit", "run"], text=True)
    # Test that we can run a Julia script
    with open("julia_script.jl", "w") as f:
        f.write('println("Hello from julia_script.jl")')
    subprocess.check_call(
        [
            "calkit",
            "new",
            "julia-env",
            "--name",
            "j1",
            "--path",
            "something/Project.toml",
            "PkgVersion",
        ]
    )
    subprocess.check_call(
        [
            "calkit",
            "new",
            "julia-script-stage",
            "--name",
            "stage-2",
            "--script-path",
            "julia_script.jl",
            "-e",
            "j1",
        ]
    )
    subprocess.check_call(["calkit", "run"])
    res = calkit.cli.main.run()
    assert "dvc_stages" in res
    assert "stage_run_info" in res


def test_stage_run_info_from_log_content():
    fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "test", "test-log.log"
    )
    with open(fpath, "r") as f:
        content = f.read()
    info = _stage_run_info_from_log_content(content)
    pprint(info)
    assert info == {
        "_check-env-py": {
            "start_time": datetime.fromisoformat(
                "2025-07-11 18:25:43,557"
            ).isoformat(),
            "end_time": datetime.fromisoformat(
                "2025-07-11 18:25:44,860"
            ).isoformat(),
            "status": "completed",
        },
        "_check-env-tex": {
            "start_time": datetime.fromisoformat(
                "2025-07-11 18:25:44,860"
            ).isoformat(),
            "end_time": datetime.fromisoformat(
                "2025-07-11 18:25:45,710"
            ).isoformat(),
            "status": "completed",
        },
        "collect-data": {
            "start_time": datetime.fromisoformat(
                "2025-07-11 18:25:45,710"
            ).isoformat(),
            "end_time": datetime.fromisoformat(
                "2025-07-11 18:25:45,710"
            ).isoformat(),
            "status": "skipped",
        },
        "plot-voltage": {
            "start_time": datetime.fromisoformat(
                "2025-07-11 18:25:45,714"
            ).isoformat(),
            "end_time": datetime.fromisoformat(
                "2025-07-11 18:25:45,714"
            ).isoformat(),
            "status": "skipped",
        },
        "this-fails": {
            "end_time": datetime.fromisoformat(
                "2025-07-11 18:25:45,722"
            ).isoformat(),
            "status": "failed",
        },
    }


def test_map_paths(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    os.makedirs("paper", exist_ok=True)
    with open("test.txt", "w") as f:
        f.write("This is a test file.")
    subprocess.check_call(
        ["calkit", "map-paths", "--file-to-file", "test.txt->paper/test.txt"]
    )
    assert os.path.isfile("paper/test.txt")
    with open("paper/test.txt", "r") as f:
        content = f.read()
    assert content == "This is a test file."
    with open(".gitignore") as f:
        gitignore = f.read()
    assert "paper/test.txt" in gitignore.split("\n")
    os.makedirs("data", exist_ok=True)
    with open("data/file1.txt", "w") as f:
        f.write("This is file 1.")
    with open("data/file2.txt", "w") as f:
        f.write("This is file 2.")
    subprocess.check_call(
        ["calkit", "map-paths", "--dir-to-dir-merge", "data->paper/data"]
    )
    assert os.path.isfile("paper/data/file1.txt")
    assert os.path.isfile("paper/data/file2.txt")
    os.remove("data/file1.txt")
    subprocess.check_call(
        ["calkit", "map-paths", "--dir-to-dir-replace", "data->paper/data"]
    )
    assert not os.path.isfile("paper/data/file1.txt")
    assert os.path.isfile("paper/data/file2.txt")
    subprocess.check_call(
        ["calkit", "map-paths", "--file-to-dir", "test.txt->paper/data"]
    )
    assert os.path.isfile("paper/data/test.txt")


def test_execute_and_record_python_script(tmp_dir):
    """Test xr command with Python script."""
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "py-env",
            "--python",
            "3.12",
            "setuptools",
        ]
    )
    # Create a simple Python script with I/O
    with open("process.py", "w") as f:
        f.write("""
# Read input
with open('input.txt', 'r') as f:
    data = f.read()

# Write output
with open('output.txt', 'w') as f:
    f.write(data.upper())

print("Processing complete")
""")
    # Create input file
    with open("input.txt", "w") as f:
        f.write("hello world")
    # Execute and record
    result = subprocess.run(
        ["calkit", "xr", "process.py", "-e", "py-env"],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    assert "Processing complete" in result.stdout
    # Verify stage was added to pipeline
    ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    assert "process" in stages
    stage = stages["process"]
    assert stage["kind"] == "python-script"
    assert stage["script_path"] == "process.py"
    assert stage["environment"] == "py-env"
    # Verify I/O detection
    assert "input.txt" in stage["inputs"]
    # Check output was created
    assert os.path.exists("output.txt")
    with open("output.txt", "r") as f:
        assert f.read() == "HELLO WORLD"
    # Verify output was detected
    outputs = stage.get("outputs", [])
    output_paths = [
        out["path"] if isinstance(out, dict) else out for out in outputs
    ]
    assert "output.txt" in output_paths


def test_execute_and_record_shell_command(tmp_dir):
    """Test xr command with shell command."""
    subprocess.check_call(["calkit", "init"])
    # Create a simple docker environment for shell commands
    subprocess.check_call(
        [
            "calkit",
            "new",
            "docker-env",
            "-n",
            "shell-env",
            "--image",
            "shell-env",
            "--from",
            "ubuntu",
        ]
    )
    # Execute shell command
    result = subprocess.run(
        [
            "calkit",
            "xr",
            "echo",
            "Hello World",
            "--stage",
            "greet",
            "-e",
            "shell-env",
        ],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    assert "Hello World" in result.stdout
    # Verify stage was added
    ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    assert "greet" in stages
    stage = stages["greet"]
    assert stage["kind"] == "shell-command"
    assert stage["command"] == "echo 'Hello World'"
    assert stage["environment"] == "shell-env"


def test_execute_and_record_julia_script(tmp_dir):
    """Test xr command with Julia script.

    Tests both with explicit environment and with auto-detection of
    dependencies and Project.toml creation.
    """
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        ["calkit", "new", "julia-env", "-n", "jl-env", "CSV", "DataFrames"]
    )
    # Create a Julia script that uses CSV to read/write
    with open("analyze.jl", "w") as f:
        f.write("""
using CSV
using DataFrames

# Read input CSV
data = CSV.read("input.csv", DataFrame)

# Process: add a new column with doubled values
data.doubled = data.value .* 2

# Write output CSV
CSV.write("output.csv", data)

println("Analysis complete")
""")
    # Create input CSV file
    with open("input.csv", "w") as f:
        f.write("id,value\n1,10\n2,20\n3,30\n")
    # Execute and record with explicit environment
    result = subprocess.run(
        ["calkit", "xr", "analyze.jl", "-e", "jl-env"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    # Verify stage was added with inputs/outputs detected
    ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    assert "analyze" in stages
    stage = stages["analyze"]
    assert stage["kind"] == "julia-script"
    assert stage["script_path"] == "analyze.jl"
    assert stage["environment"] == "jl-env"
    # Verify inputs and outputs were detected
    assert "input.csv" in stage.get("inputs", [])
    assert {"path": "output.csv", "storage": "git"} in stage.get("outputs", [])
    # Verify output file was created
    assert os.path.exists("output.csv")
    # Test auto-detection of dependencies and Project.toml creation
    # First, clean up the previous environment and files
    shutil.rmtree(".calkit", ignore_errors=True)
    os.remove("calkit.yaml")
    os.remove("Project.toml")
    os.remove("Manifest.toml")
    # Run xr without specifying environment
    # This should auto-detect CSV dependency and create Project.toml
    result = subprocess.run(
        ["calkit", "xr", "analyze.jl"],
        capture_output=True,
        text=True,
    )
    assert (
        result.returncode == 0
    ), f"Auto-detect command failed: {result.stderr}"
    # Verify Project.toml was created with CSV as dependency
    assert os.path.exists("Project.toml")
    with open("Project.toml") as f:
        project_content = f.read()
    # Check that CSV is listed as a dependency (either in [deps] or
    # in comments)
    assert "CSV" in project_content
    # Verify stage was added
    ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    assert "analyze" in stages
    stage = stages["analyze"]
    assert stage["kind"] == "julia-script"
    env = ck_info.get("environments", {}).get(stage.get("environment"))
    assert env is not None
    assert env["kind"] == "julia"
    assert env["path"] == "Project.toml"
    assert "input.csv" in stage.get("inputs", [])
    assert {"path": "output.csv", "storage": "git"} in stage.get("outputs", [])


def test_execute_and_record_r_script(tmp_dir):
    """Test xr command with R script using automated environment detection."""
    subprocess.check_call(["calkit", "init"])
    # Create an R script with library dependencies for auto-detection
    with open("analyze.R", "w") as f:
        f.write("""
library(readr)
library(dplyr)

# Read input
data <- read_csv("input.csv")

# Process data
result <- data %>%
  summarise(mean_value = mean(value))

# Write output
write_csv(result, "output.csv")

cat("Analysis complete\\n")
""")
    # Create input file
    with open("input.csv", "w") as f:
        f.write("value\n1\n2\n3\n")
    # Execute and record
    # (no environment specified; should auto-detect dependencies)
    result = subprocess.run(
        ["calkit", "xr", "analyze.R"],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    # Verify stage was added
    ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    assert "analyze" in stages
    stage = stages["analyze"]
    assert stage["kind"] == "r-script"
    assert stage["script_path"] == "analyze.R"
    # Verify environment was auto-created
    assert "environment" in stage
    env_name = stage["environment"]
    envs = ck_info.get("environments", {})
    assert env_name in envs
    env = envs[env_name]
    assert env["kind"] == "renv"
    # Verify DESCRIPTION file was created with detected dependencies
    env_path = env.get("path")
    assert env_path is not None
    assert os.path.isfile(env_path)
    with open(env_path, "r") as f:
        desc_content = f.read()
    # Check that detected packages are in DESCRIPTION
    assert "readr" in desc_content
    assert "dplyr" in desc_content
    # Verify renv.lock was created during environment check
    env_dir = os.path.dirname(env_path)
    lock_path = os.path.join(env_dir, "renv.lock")
    assert os.path.isfile(lock_path), f"renv.lock not found at {lock_path}"
    # Verify I/O detection
    assert "input.csv" in stage["inputs"]
    # Check output was created
    assert os.path.exists("output.csv")
    # Verify output was detected
    outputs = stage.get("outputs", [])
    output_paths = [
        out["path"] if isinstance(out, dict) else out for out in outputs
    ]
    assert "output.csv" in output_paths


@pytest.mark.skipif(
    shutil.which("matlab") is None, reason="MATLAB not installed"
)
def test_execute_and_record_matlab_script(tmp_dir):
    from scipy.io import savemat

    # Create a dependency MATLAB function
    os.makedirs("src", exist_ok=True)
    with open("src/myfunction.m", "w") as f:
        f.write(
            """
function out = myfunction(x)
out = x * 2;
end
"""
        )
    # Create a MATLAB script
    with open("compute.m", "w") as f:
        f.write("""
addpath(genpath('src'));
result = myfunction(1);
data = load('input.mat');
result = data.value * 2 + result;
save('output.mat', 'result');
disp('Computation complete');
""")
    # Create input file
    savemat("input.mat", {"value": 42})
    # Execute and record
    result = subprocess.run(
        ["calkit", "xr", "compute.m"],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    # Verify stage was added
    ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    assert "compute" in stages
    stage = stages["compute"]
    assert stage["kind"] == "matlab-script"
    assert stage["script_path"] == "compute.m"
    assert stage["environment"] == "_system"
    assert "input.mat" in stage["inputs"]
    assert "src/myfunction.m" in stage["inputs"]
    assert "compute.m" not in stage["inputs"]


def test_execute_and_record_with_user_inputs_outputs(tmp_dir):
    """Test xr command with user-specified inputs and outputs."""
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "py-env",
            "--python",
            "3.12",
            "numpy",
        ]
    )
    # Create a script
    with open("calc.py", "w") as f:
        f.write("""
import numpy as np

# This won't be detected automatically
arr = np.array([1, 2, 3])
np.save('data.npy', arr)
""")
    # Create the input file that we'll reference
    with open("config.txt", "w") as f:
        f.write("test config")
    # Execute with explicit inputs/outputs
    result = subprocess.run(
        [
            "calkit",
            "xr",
            "calc.py",
            "-e",
            "py-env",
            "--input",
            "config.txt",
            "--output",
            "data.npy",
        ],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    # Verify inputs/outputs
    ck_info = calkit.load_calkit_info()
    stage = ck_info["pipeline"]["stages"]["calc"]
    assert "config.txt" in stage["inputs"]
    # Find the data.npy output
    outputs = stage["outputs"]
    assert any(
        out["path"] == "data.npy"
        if isinstance(out, dict)
        else out == "data.npy"
        for out in outputs
    )


def test_execute_and_record_failure_rollback(tmp_dir):
    """Test that xr rolls back pipeline changes if execution fails."""
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "py-env",
            "--python",
            "3.12",
            "setuptools",
        ]
    )
    # Create a failing script
    with open("fail.py", "w") as f:
        f.write("""
raise RuntimeError("Intentional failure")
""")
    # Execute and expect failure
    result = subprocess.run(
        ["calkit", "xr", "fail.py", "-e", "py-env"],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode != 0
    # Verify stage was NOT added to pipeline
    ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    assert "fail" not in stages


def test_execute_and_record_no_io_detect(tmp_dir):
    """Test xr command with I/O detection disabled."""
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "py-env",
            "--python",
            "3.12",
            "setuptools",
        ]
    )
    # Create a script with I/O
    with open("script.py", "w") as f:
        f.write("""
with open('input.txt', 'r') as f:
    data = f.read()
with open('output.txt', 'w') as f:
    f.write(data)
""")
    with open("input.txt", "w") as f:
        f.write("test")
    # Execute with detection disabled
    result = subprocess.run(
        ["calkit", "xr", "script.py", "-e", "py-env", "--no-detect-io"],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    assert result.returncode == 0
    # Verify no automatic I/O was detected (inputs will be empty)
    ck_info = calkit.load_calkit_info()
    stage = ck_info["pipeline"]["stages"]["script"]
    # With --no-detect-io, no inputs should be detected (not even the script)
    assert len(stage.get("inputs", [])) == 0


def test_execute_and_record_stage_name_conflict(tmp_dir):
    """Test that xr auto-increments stage names on conflict."""
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "uv-venv",
            "-n",
            "py-env",
            "--python",
            "3.12",
            "setuptools",
        ]
    )
    # Create two different scripts with the same base name
    with open("process.py", "w") as f:
        f.write("print('Version 1')")
    # Execute and record the first version
    result = subprocess.run(
        ["calkit", "xr", "process.py", "-e", "py-env"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    # Now create a different script with a different path but same name
    os.mkdir("scripts")
    with open("scripts/process.py", "w") as f:
        f.write("print('Version 2')")
    # Try to execute the second version without specifying a stage name
    # Should auto-increment to "process-2"
    result = subprocess.run(
        ["calkit", "xr", "scripts/process.py", "-e", "py-env"],
        capture_output=True,
        text=True,
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    # Should succeed with auto-incremented name
    assert result.returncode == 0
    assert "using 'process-2' instead" in result.stdout
    # Verify the stage was created with the incremented name
    ck_info = calkit.load_calkit_info()
    assert "process" in ck_info["pipeline"]["stages"]
    assert "process-2" in ck_info["pipeline"]["stages"]
    assert (
        ck_info["pipeline"]["stages"]["process"]["script_path"] == "process.py"
    )
    assert (
        ck_info["pipeline"]["stages"]["process-2"]["script_path"]
        == "scripts/process.py"
    )
    # Verify we can still add with an explicit stage name
    os.makedirs("other", exist_ok=True)
    with open("other/process.py", "w") as f:
        f.write("print('Version 3')")
    result = subprocess.run(
        [
            "calkit",
            "xr",
            "other/process.py",
            "-e",
            "py-env",
            "--stage",
            "process-v3",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    # Verify all three stages exist
    ck_info = calkit.load_calkit_info()
    stages = ck_info["pipeline"]["stages"]
    assert "process" in stages
    assert "process-2" in stages
    assert "process-v3" in stages
    assert stages["process"]["script_path"] == "process.py"
    assert stages["process-2"]["script_path"] == "scripts/process.py"
    assert stages["process-v3"]["script_path"] == "other/process.py"
