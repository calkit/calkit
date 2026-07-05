"""Tests for ``cli.main.core``."""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from pprint import pprint

import dvc.repo
import git
import pytest
import yaml
from dvc.exceptions import NotDvcRepoError
from git.exc import InvalidGitRepositoryError

import calkit
import calkit.cli.main
from calkit.cli.core import complete_stage_names
from calkit.cli.main.core import (
    _get_running_pipeline_status,
    _prune_run_logs,
    _stage_run_info_from_log_content,
    _stage_target_from_cmd,
    _to_shell_cmd,
)
from calkit.cli.main.core import (
    app as calkit_app,
)

skipif_windows_docker = pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "TODO: Docker Linux images are unavailable on windows-latest GHA "
        "runners"
    ),
)
skipif_windows_mock_scheduler = pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: mock scheduler is not yet Windows-compatible",
)


def _repo_test_file(name: str) -> Path:
    """Find a file in the repository-level ``test`` directory."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "test" / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Could not find repository test file: test/{name}"
    )


def test_init(tmp_dir):
    # With no calkit.yaml present, init creates an empty one
    assert not os.path.isfile("calkit.yaml")
    subprocess.check_call(["calkit", "init"])
    assert os.path.isfile("calkit.yaml")
    assert calkit.load_calkit_info() == {}
    # Already initialized: init without --force fails and does not clobber
    result = subprocess.run(
        ["calkit", "init"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "already initialized" in result.stderr.lower()
    assert "use --force" in result.stderr.lower()
    assert calkit.load_calkit_info() == {}
    # init must not clobber a pre-existing calkit.yaml
    os.makedirs("sub")
    ck_info = {"name": "test-project"}
    with open(os.path.join("sub", "calkit.yaml"), "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "init"], cwd="sub")
    assert calkit.load_calkit_info(wdir="sub") == ck_info
    # Fully initialized project blocks init without --force
    result = subprocess.run(
        ["calkit", "init"],
        cwd="sub",
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "already initialized" in result.stderr.lower()
    assert calkit.load_calkit_info(wdir="sub") == ck_info
    # --force allows re-initialization without clobbering calkit.yaml
    subprocess.check_call(["calkit", "init", "--force"], cwd="sub")
    assert calkit.load_calkit_info(wdir="sub") == ck_info


@skipif_windows_docker
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


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Julia env init fails on Windows GHA runners (Pkg stdlib missing)",
)
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
    # Test dry run: verify nothing is staged and output describes what would happen
    subprocess.check_call(["git", "reset"])
    with open("dry_small.txt", "w") as f:
        f.write("small")
    with open("dry_large.bin", "wb") as f:
        f.write(os.urandom(binary_size))
    with open("dry_data.parquet", "w") as f:
        f.write("fake parquet")
    staged_before = set(calkit.git.get_staged_files())
    out = subprocess.check_output(
        [
            "calkit",
            "add",
            "--dry-run",
            "dry_small.txt",
            "dry_large.bin",
            "dry_data.parquet",
        ],
        text=True,
    )
    assert "dry_small.txt" in out and "Git" in out
    assert "dry_large.bin" in out and "DVC" in out
    assert "dry_data.parquet" in out and "DVC" in out
    # Nothing should have been staged
    assert set(calkit.git.get_staged_files()) == staged_before
    assert "dry_small.txt" not in calkit.dvc.list_paths()
    # Test --dry-run with --to
    out = subprocess.check_output(
        ["calkit", "add", "--dry-run", "--to", "git", "dry_small.txt"],
        text=True,
    )
    assert "dry_small.txt" in out and "git" in out
    assert set(calkit.git.get_staged_files()) == staged_before


def test_add_pipeline_output_storage(tmp_dir):
    """Test that ``add`` respects pipeline output storage settings.

    Bug: files with DVC extensions (e.g. .png) were routed to DVC even when
    ``storage: git`` was set for that output in calkit.yaml.
    """
    subprocess.check_call(["calkit", "init"])
    # Create a .png file – would normally be routed to DVC by extension.
    # The content is intentionally fake; only the extension matters here.
    with open("figure.png", "w") as f:
        f.write("fake png content")
    # Write a calkit.yaml pipeline that declares this output with storage: git
    pipeline = {
        "pipeline": {
            "stages": {
                "analyze": {
                    "kind": "command",
                    "environment": "_system",
                    "command": "echo done",
                    "outputs": [{"path": "figure.png", "storage": "git"}],
                }
            }
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(pipeline, f)
    # Adding the file should use Git, not DVC, because of pipeline storage
    out = subprocess.check_output(["calkit", "add", "figure.png"], text=True)
    assert "Git" in out or "git" in out
    assert "figure.png" in calkit.git.get_staged_files()
    assert "figure.png" not in calkit.dvc.list_paths()
    # Also verify dry-run output reflects pipeline output storage
    out = subprocess.check_output(
        ["calkit", "add", "--dry-run", "figure.png"], text=True
    )
    assert "Git" in out or "git" in out
    # DVC pipeline output: storage: dvc means the file is tracked via
    # dvc.lock (committed to Git), NOT via dvc add / .dvc files.
    # Unstage figure.png to reset for the DVC storage case
    subprocess.call(["git", "restore", "--staged", "figure.png"])
    pipeline["pipeline"]["stages"]["analyze"]["outputs"] = [
        {"path": "figure.png", "storage": "dvc"}
    ]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(pipeline, f)
    # Simulate dvc.lock being updated by a pipeline run
    with open("dvc.lock", "w") as f:
        f.write("schema: '2.0'\nstages:\n  analyze:\n    cmd: echo done\n")
    subprocess.call(["git", "add", "dvc.lock"])
    subprocess.call(["git", "commit", "-m", "init dvc.lock"])
    # Modify dvc.lock so it is dirty and can be staged
    with open("dvc.lock", "a") as f:
        f.write("# updated\n")
    out = subprocess.check_output(["calkit", "add", "figure.png"], text=True)
    # Should mention dvc.lock, not attempt dvc add on the file
    assert "dvc.lock" in out
    assert not os.path.exists("figure.png.dvc")
    assert "dvc.lock" in calkit.git.get_staged_files()


def test_save_to_git_with_all(tmp_dir):
    """Test that ``save --to git -a`` respects the ``--to`` flag.

    Bug: when ``-a`` / ``--all`` was used together with ``--to git``, the
    ``--to`` value was not forwarded to the internal ``add()`` call, causing
    files to be auto-routed to DVC based on extension instead.

    No pipeline storage override is set so the test relies solely on ``--to``
    to route figure.png to Git; without the fix the extension-based heuristic
    would send it to DVC.
    """
    subprocess.check_call(["calkit", "init"])
    # No pipeline entry — figure.png has no explicit storage override, so
    # only the --to flag can direct it to Git (extension would pick DVC).
    with open("figure.png", "w") as f:
        f.write("fake png content")
    # save --to git -a should add figure.png to Git, not DVC
    subprocess.check_call(
        ["calkit", "save", "--to", "git", "-am", "Add figure", "--no-push"]
    )
    repo = git.Repo()
    # figure.png should be tracked in Git, not DVC
    assert repo.git.ls_files("figure.png")
    assert "figure.png" not in calkit.dvc.list_paths()


def test_large_folder_many_small_files(tmp_dir, tmp_path):
    subprocess.check_call(["calkit", "init"])
    # Set up a bare git remote and a local DVC remote as siblings of the
    # project dir so we can exercise push/pull in this test
    git_remote = tmp_path / "git_remote"
    dvc_remote = tmp_path / "dvc_remote"
    git_remote.mkdir()
    dvc_remote.mkdir()
    subprocess.check_call(["git", "init", "--bare", str(git_remote)])
    repo = git.Repo()
    repo.create_remote("origin", str(git_remote))
    subprocess.check_call(
        ["dvc", "remote", "add", "-d", "origin", str(dvc_remote)]
    )
    subprocess.check_call(["git", "add", ".dvc/config"])
    subprocess.check_call(["git", "commit", "-m", "Add remotes"])
    # Create a folder with large overall size but filled with many small files;
    # when added it should be detected as a zip candidate and stored as a DVC
    # zip
    os.makedirs("many_small_files")
    for i in range(100):
        with open(f"many_small_files/file_{i}.txt", "w") as f:
            # Make each file ~100 kB; 100 files = ~10 MB total, well above the
            # DVC size threshold and with small average file size
            f.write("This is a small file.\n" * 3000)
    subprocess.check_call(["calkit", "add", "many_small_files"])
    staged = calkit.git.get_staged_files()
    assert ".calkit/zip/files/many_small_files.zip.dvc" in staged
    assert ".calkit/zip/paths.json" in staged
    repo = git.Repo()
    assert repo.ignored("many_small_files")
    assert not os.path.isfile("many_small_files.dvc")
    # Test explicit --to dvc-zip flag on a second folder
    os.makedirs("more_small_files")
    for i in range(100):
        with open(f"more_small_files/file_{i}.txt", "w") as f:
            f.write("Another small file.\n" * 3000)
    subprocess.check_call(
        ["calkit", "add", "--to", "dvc-zip", "more_small_files"]
    )
    staged2 = calkit.git.get_staged_files()
    assert ".calkit/zip/files/more_small_files.zip.dvc" in staged2
    subprocess.check_call(["calkit", "commit", "-m", "Initial commit"])
    # Push everything to the remotes
    subprocess.check_call(["calkit", "push"])
    # Create a pipeline stage that uses dvc-zip storage for an output
    stage = {
        "kind": "command",
        "environment": "_system",
        "command": "mkdir -p results && echo 'sup' > results/out.txt",
        "outputs": [{"path": "results", "storage": "dvc-zip"}],
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"pipeline": {"stages": {"stage1": stage}}}, f)
    subprocess.check_call(["calkit", "run"])
    assert repo.ignored("results")
    assert os.path.isdir("results")
    assert os.path.isfile("results/out.txt")
    assert os.path.isfile(".calkit/zip/files/results.zip")
    # The pipeline output zip should be DVC-tracked, not the workspace dir
    assert os.path.isfile(".calkit/zip/files/results.zip.dvc")
    assert not os.path.isfile("results.dvc")
    subprocess.check_call(["calkit", "save", "-am", "Run pipeline"])
    # Clone into a fresh directory, pull DVC data, and verify the zip was
    # transferred; calkit sync would then unzip it to the workspace
    clone_dir = tmp_path / "clone"
    subprocess.check_call(["git", "clone", str(git_remote), str(clone_dir)])
    subprocess.check_call(["dvc", "pull"], cwd=str(clone_dir))
    assert (clone_dir / ".calkit" / "zip" / "files" / "results.zip").is_file()
    # Running calkit run in the clone should unzip before the pipeline runs
    subprocess.check_call(["calkit", "run"], cwd=str(clone_dir))
    assert (clone_dir / "results" / "out.txt").is_file()


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
    assert repo.head.commit.message.strip() == "Initialize Calkit"
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
    script_path = _repo_test_file("script.py")
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
    if sys.platform == "win32":
        # TODO: Julia env init fails on Windows GHA runners (Pkg stdlib missing)
        pytest.skip("Julia portion of test_run not yet supported on Windows")
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


def test_run_ignore_errors(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    # Create a pipeline with a failing stage and an independent stage
    dvc_yaml = {
        "stages": {
            "failing-stage": {
                "cmd": 'python -c "import sys; sys.exit(1)"',
            },
            "independent-stage": {
                "cmd": "python -c \"open('out.txt', 'w').write('done')\"",
                "outs": ["out.txt"],
            },
        }
    }
    with open("dvc.yaml", "w") as f:
        yaml.dump(dvc_yaml, f)
    subprocess.check_call(
        ["calkit", "save", "-am", "Create pipeline", "--no-push"]
    )
    # Without --ignore-errors, the pipeline should fail
    result = subprocess.run(["calkit", "run"])
    assert result.returncode != 0
    # With --ignore-errors, the independent stage should complete
    if os.path.exists("out.txt"):
        os.remove("out.txt")
    subprocess.check_call(["calkit", "run", "--ignore-errors"])
    assert os.path.exists("out.txt")


def test_run_downstream(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    # Create a pipeline: stage-a -> stage-b
    dvc_yaml = {
        "stages": {
            "stage-a": {
                "cmd": "python -c \"open('a.txt', 'w').write('a')\"",
                "outs": ["a.txt"],
            },
            "stage-b": {
                "cmd": (
                    "python -c \"open('b.txt', 'w')"
                    ".write(open('a.txt').read() + 'b')\""
                ),
                "deps": ["a.txt"],
                "outs": ["b.txt"],
            },
        }
    }
    with open("dvc.yaml", "w") as f:
        yaml.dump(dvc_yaml, f)
    # Run all stages to prime the cache
    subprocess.check_call(["calkit", "run"])
    assert os.path.exists("a.txt")
    assert os.path.exists("b.txt")
    # Delete outputs and run with --downstream stage-a: both stages should run
    os.remove("a.txt")
    os.remove("b.txt")
    subprocess.check_call(
        ["calkit", "run", "--downstream", "stage-a", "--force"]
    )
    assert os.path.exists("a.txt")
    assert os.path.exists("b.txt")


def test_stage_run_info_from_log_content():
    fpath = _repo_test_file("test-log.log")
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
    # Stage names containing colons (e.g. inline subproject targets) must keep
    # their colons, not have them stripped out.
    colon_log = (
        "2025-07-11 18:25:43,557 - INFO - Running stage "
        "'sub1/dvc.yaml:stage-a':\n"
        "2025-07-11 18:25:44,000 - INFO - Running stage 'next':\n"
    )
    colon_info = _stage_run_info_from_log_content(colon_log)
    assert "sub1/dvc.yaml:stage-a" in colon_info
    assert colon_info["sub1/dvc.yaml:stage-a"]["status"] == "completed"
    assert "next" in colon_info


def _write_fake_rwlock(pid: int) -> None:
    """Write a DVC rwlock file owned by ``pid`` to simulate a run."""
    _write_rwlock({"out.txt": {"pid": pid, "cmd": "calkit run"}})


def _write_rwlock(entries: dict) -> None:
    """Write a DVC rwlock 'write' section from ``{path: {pid, cmd}}``."""
    tmp = os.path.join(".dvc", "tmp")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "rwlock"), "w") as f:
        json.dump({"write": entries}, f)


def _spawn_lock_holder(*signature: str):
    """Spawn a long-lived process whose argv embeds ``signature``.

    Returns ``(proc, cmd)`` where ``cmd`` mirrors what DVC records for an
    rwlock entry (``" ".join(sys.argv)``) and matches the live process, so it
    is recognized as a genuine holder. ``signature`` lets a test embed e.g.
    ``"dvc", "repro", "--single-item", "sweep@1"`` so both stage-target parsing
    and holder verification see a realistic command. Args must be space-free so
    the recorded command tokenizes the same way DVC's does.
    """
    with open("holder.py", "w") as f:
        f.write("import time\ntime.sleep(120)\n")
    argv = [sys.executable, "holder.py", *signature]
    proc = subprocess.Popen(argv)
    return proc, " ".join(argv)


def _write_fake_run_log() -> None:
    """Write a run log with one finished and one in-progress stage."""
    logs_dir = os.path.join(calkit.ensure_local_dir(), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    now = calkit.utcnow(remove_tz=True)
    ts = now.strftime("%Y-%m-%d %H:%M:%S,") + f"{now.microsecond // 1000:03d}"
    lines = [
        f"{ts} - INFO - Running stage 'preprocess':",
        f"{ts} - INFO - > echo hi",
        f"{ts} - INFO - Running stage 'train':",
        f"{ts} - INFO - > echo train",
    ]
    with open(os.path.join(logs_dir, "20250101-000000-abc.log"), "w") as f:
        f.write("\n".join(lines) + "\n")


def test_get_running_pipeline_status(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    # No rwlock present means no run is in progress
    assert _get_running_pipeline_status() is None
    # A stale rwlock (dead PID) should not register as a running pipeline
    _write_fake_rwlock(pid=2**31 - 1)
    assert calkit.dvc.get_running_pipeline_processes() == []
    assert _get_running_pipeline_status() is None
    # A live process whose command matches the recorded entry means a run is in
    # progress; the log shows which stage is running and which have finished.
    proc, cmd = _spawn_lock_holder()
    try:
        _write_rwlock({"out.txt": {"pid": proc.pid, "cmd": cmd}})
        _write_fake_run_log()
        procs = calkit.dvc.get_running_pipeline_processes()
        assert len(procs) == 1
        assert procs[0]["pid"] == proc.pid
        status = _get_running_pipeline_status()
        assert status is not None
        assert status["running"] is True
        assert status["running_stages"] == ["train"]
        assert status["stages"]["preprocess"]["status"] == "completed"
    finally:
        proc.terminate()
        proc.wait()


def test_reused_pid_is_not_reported_as_running(tmp_dir):
    """A live PID that isn't the recorded run must not show as in progress.

    After a run finishes or is killed, its rwlock entry can linger and the OS
    can reuse its PID for an unrelated process. Liveness alone then reports a
    phantom "Run in progress (PID ...)" whose elapsed time keeps growing from a
    stale run log (issue #942). The entry's recorded command must match the live
    process, so a reused PID running something else is ignored.
    """
    subprocess.check_call(["calkit", "init"])
    # A live process whose command does NOT match the recorded run command,
    # simulating a reused PID.
    proc, _ = _spawn_lock_holder("unrelated", "process")
    try:
        _write_rwlock(
            {
                "out.txt": {
                    "pid": proc.pid,
                    "cmd": "calkit run -s postpro-ParetoFigFunc",
                }
            }
        )
        _write_fake_run_log()
        assert calkit.dvc.get_running_pipeline_processes() == []
        assert _get_running_pipeline_status() is None
    finally:
        proc.terminate()
        proc.wait()


def test_stage_target_from_cmd():
    assert (
        _stage_target_from_cmd(
            "/p/__main__.py dvc repro --single-item sweep@3"
        )
        == "sweep@3"
    )
    assert _stage_target_from_cmd("dvc repro stage-a") == "stage-a"
    assert _stage_target_from_cmd("dvc repro --single-item -f my-stage") == (
        "my-stage"
    )
    # No explicit target (full-pipeline repro) or non-repro commands
    assert _stage_target_from_cmd("dvc repro") is None
    assert _stage_target_from_cmd("/p/calkit run") is None


def test_running_status_names_concurrent_sweep_items(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    # Mimic the concurrent-scheduler prepass: several `dvc repro --single-item
    # <item>` processes hold the lock before any run log exists. Use real
    # sleeper processes so their PIDs register as alive.
    # A stale log from a previous run reports every item as finished. The
    # current sweep runs only items 1 and 3; the stale log must be ignored so
    # finished items don't show as running (and vice versa).
    _write_fake_run_log()
    logs_dir = os.path.join(calkit.ensure_local_dir(), "logs")
    now = calkit.utcnow(remove_tz=True)
    ts = now.strftime("%Y-%m-%d %H:%M:%S,") + f"{now.microsecond // 1000:03d}"
    with open(os.path.join(logs_dir, "20240101-000000-old.log"), "w") as f:
        for item in ["sweep@1", "sweep@2", "sweep@3"]:
            f.write(f"{ts} - INFO - Stage '{item}' didn't change, skipping\n")
    running_now = ["sweep@1", "sweep@3"]
    # Real processes whose command lines match the recorded rwlock entries, as
    # the concurrent prepass's `dvc repro --single-item <item>` workers would.
    holders = []
    try:
        write = {}
        for item in running_now:
            proc, cmd = _spawn_lock_holder(
                "dvc", "repro", "--single-item", item
            )
            holders.append(proc)
            write[f"out-{item}.txt"] = {"pid": proc.pid, "cmd": cmd}
        _write_rwlock(write)
        status = _get_running_pipeline_status()
        assert status is not None
        assert status["running"] is True
        # Only the items actually running now, and no stale log stages
        assert set(status["running_stages"]) == set(running_now)
        assert status["stages"] == {}
    finally:
        for p in holders:
            p.terminate()
            p.wait()


def test_status_reports_running_pipeline(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    proc, cmd = _spawn_lock_holder()
    try:
        _write_rwlock({"out.txt": {"pid": proc.pid, "cmd": cmd}})
        _write_fake_run_log()
        out = subprocess.check_output(
            ["calkit", "status", "-c", "pipeline"], text=True
        )
        assert "Run in progress" in out
        assert str(proc.pid) in out
        assert "preprocess" in out
        assert "train" in out
        # The same information is available as JSON for programmatic/agent use
        out = subprocess.check_output(
            ["calkit", "status", "-c", "pipeline", "--json"], text=True
        )
        data = json.loads(out)
        assert data["pipeline"]["running"] is True
        assert "train" in data["pipeline"]["running_stages"]
    finally:
        proc.terminate()
        proc.wait()


def test_run_writes_private_logs(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    dvc_yaml = {
        "stages": {
            "s1": {
                "cmd": "python -c \"open('out.txt', 'w').write('x')\"",
                "outs": ["out.txt"],
            }
        }
    }
    with open("dvc.yaml", "w") as f:
        yaml.dump(dvc_yaml, f)
    # Without --log, the log is retained privately under .calkit/local/logs
    # (gitignored) and not saved to the tracked .calkit/logs directory
    subprocess.check_call(["calkit", "run"])
    local_logs = os.path.join(".calkit", "local", "logs")
    private = [f for f in os.listdir(local_logs) if f.endswith(".log")]
    # One main run log and one stage log
    assert len(private) == 2
    assert os.path.isfile(os.path.join(".calkit", "local", ".gitignore"))
    tracked_dir = os.path.join(".calkit", "logs")
    assert not os.path.isdir(tracked_dir) or not [
        f for f in os.listdir(tracked_dir) if f.endswith(".log")
    ]
    # Without --log, run info and systems are also saved privately to .calkit/local
    assert os.path.isdir(os.path.join(".calkit", "local", "runs"))
    assert os.path.isdir(os.path.join(".calkit", "local", "systems"))
    # With --log, the log is also saved to the tracked directory plus run info
    subprocess.check_call(["calkit", "run", "--log", "--force"])
    tracked = [f for f in os.listdir(tracked_dir) if f.endswith(".log")]
    assert len(tracked) == 2
    assert os.path.isdir(os.path.join(".calkit", "runs"))
    assert os.path.isdir(os.path.join(".calkit", "systems"))


def test_prune_run_logs(tmp_dir):
    logs_dir = "logs"
    os.makedirs(logs_dir)
    # Logs are named by start timestamp, so name order is time order
    names = [f"2026-05-23T10-00-{i:02d}-abc.log" for i in range(12)]
    for n in names:
        with open(os.path.join(logs_dir, n), "w") as f:
            f.write("x")
    # A non-log file should be left untouched
    with open(os.path.join(logs_dir, "keep.txt"), "w") as f:
        f.write("x")
    _prune_run_logs(logs_dir, keep=10)
    remaining = sorted(f for f in os.listdir(logs_dir) if f.endswith(".log"))
    assert remaining == names[-10:]
    assert os.path.isfile(os.path.join(logs_dir, "keep.txt"))
    # Pruning is a no-op when at or below the cap, and when the dir is missing
    _prune_run_logs(logs_dir, keep=10)
    assert len([f for f in os.listdir(logs_dir) if f.endswith(".log")]) == 10
    _prune_run_logs("does-not-exist", keep=10)
    # The active log is never deleted, even if its name sorts oldest (e.g.
    # clock skew or an unusual name).
    old_active = "1999-01-01T00-00-00-active.log"
    with open(os.path.join(logs_dir, old_active), "w") as f:
        f.write("x")
    _prune_run_logs(logs_dir, keep=10, protect=old_active)
    assert os.path.isfile(os.path.join(logs_dir, old_active))


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


def test_complete_stage_names(tmp_dir):
    subprocess.check_call(["git", "init"])
    # Parent project with one pipeline stage
    ck_info = {
        "pipeline": {
            "stages": {
                "parent-stage": {
                    "kind": "shell-command",
                    "command": "echo hi",
                    "environment": "env",
                }
            }
        },
        "subprojects": [
            {"path": "inline-sp"},
            {"path": "isolated-sp"},
        ],
    }
    os.makedirs("inline-sp")
    os.makedirs("isolated-sp/.dvc", exist_ok=True)
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    # Write calkit.yaml for inline subproject
    with open("inline-sp/calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "pipeline": {
                    "stages": {
                        "stage-a": {
                            "kind": "shell-command",
                            "command": "echo a",
                            "environment": "env",
                        }
                    }
                }
            },
            f,
        )
    # Write calkit.yaml for isolated subproject
    with open("isolated-sp/calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "pipeline": {
                    "stages": {
                        "stage-b": {
                            "kind": "shell-command",
                            "command": "echo b",
                            "environment": "env",
                        }
                    }
                }
            },
            f,
        )
    names = [item.value for item in complete_stage_names(None, None, "")]
    # Parent stage
    assert "parent-stage" in names
    # Subproject shorthand
    assert "inline-sp" in names
    assert "isolated-sp" in names
    # Subproject stage targets
    assert "inline-sp:stage-a" in names
    assert "isolated-sp:stage-b" in names
    # Prefix filtering
    filtered = [
        item.value for item in complete_stage_names(None, None, "inline")
    ]
    assert "inline-sp" in filtered
    assert "inline-sp:stage-a" in filtered
    assert "parent-stage" not in filtered
    assert "isolated-sp" not in filtered


def test_use_version_execs_uvx(monkeypatch):
    # ``calkit --use-version 0.38 run -f`` re-invokes itself under uvx
    # with the requested calkit-python version pinned and the original
    # subcommand/args forwarded.
    captured: dict = {}

    def fake_execvp(file, argv):
        captured["argv"] = argv
        raise SystemExit(0)

    monkeypatch.setattr("os.execvp", fake_execvp)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/uvx")
    monkeypatch.setattr(
        sys, "argv", ["calkit", "--use-version", "0.38", "run", "-f"]
    )
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(calkit_app, ["--use-version", "0.38", "run", "-f"])
    # SystemExit is raised inside fake_execvp; Typer surfaces it as exit 0.
    assert result.exit_code == 0
    argv = captured["argv"]
    assert argv[:4] == ["uvx", "--from", "calkit-python@0.38", "calkit"]
    # ``--use-version`` is stripped so the child doesn't loop.
    assert "--use-version" not in argv
    assert argv[-2:] == ["run", "-f"]


def test_use_version_intercepts_before_typer(monkeypatch):
    # ``calkit --use-version 0.1.1 -- --help`` and ``-- --version`` must
    # re-exec via uvx; if Typer were allowed to parse first, Click's
    # eager ``--help``/``--version`` (or ``no_args_is_help``) would
    # print the *current* CLI's output before the callback ran.
    captured: dict = {}

    def fake_execvp(file, argv):
        captured["argv"] = argv
        raise SystemExit(0)

    monkeypatch.setattr("os.execvp", fake_execvp)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/uvx")
    monkeypatch.setattr(
        sys,
        "argv",
        ["calkit", "--use-version", "0.1.1", "--", "--help"],
    )
    from calkit.cli import run as cli_run

    with pytest.raises(SystemExit):
        cli_run()
    assert captured["argv"][:4] == [
        "uvx",
        "--from",
        "calkit-python@0.1.1",
        "calkit",
    ]
    # The leading ``--`` separator was only needed to escape the parent
    # parser; the forwarded argv must NOT carry it through, or the older
    # child CLI will interpret ``--help`` as a positional subcommand.
    assert "--" not in captured["argv"]
    assert captured["argv"][-1] == "--help"
    # ``--use-version=<v>`` form is also honored.
    captured.clear()
    monkeypatch.setattr(
        sys,
        "argv",
        ["calkit", "--use-version=0.3", "--", "--version"],
    )
    with pytest.raises(SystemExit):
        cli_run()
    assert captured["argv"][:4] == [
        "uvx",
        "--from",
        "calkit-python@0.3",
        "calkit",
    ]
    assert "--" not in captured["argv"]
    assert captured["argv"][-1] == "--version"


def test_use_version_only_scanned_in_group_options(monkeypatch):
    # ``--use-version`` buried after a subcommand (or after ``--``) is
    # a forwarded argument for that subcommand's child process, NOT a
    # request to re-exec under uvx. The pre-Typer intercept must only
    # look at the group's own options region.
    called: dict = {"exec": False}

    def fake_execvp(file, argv):
        called["exec"] = True
        raise SystemExit(0)

    monkeypatch.setattr("os.execvp", fake_execvp)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/uvx")
    from calkit.cli import _maybe_exec_with_version

    # Subcommand precedes ``--use-version``: must NOT re-exec.
    monkeypatch.setattr(
        sys,
        "argv",
        ["calkit", "xenv", "--", "some-tool", "--use-version", "1.0"],
    )
    _maybe_exec_with_version()
    assert called["exec"] is False
    # And a bare ``--`` before ``--use-version`` is forwarded territory.
    monkeypatch.setattr(sys, "argv", ["calkit", "--", "--use-version", "1.0"])
    _maybe_exec_with_version()
    assert called["exec"] is False


def test_use_version_without_uvx(monkeypatch):
    # If uvx isn't on PATH, --use-version fails fast with a clear error
    # instead of falling through to running the local calkit.
    monkeypatch.setattr(shutil, "which", lambda name: None)
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(calkit_app, ["--use-version", "0.38", "run"])
    assert result.exit_code != 0
    # ``raise_error`` writes to stderr but typer's runner merges output.
    assert "uvx" in (result.output + (result.stderr or ""))


@skipif_windows_mock_scheduler
def test_run_concurrent_scheduler_stage_with_mock(tmp_dir):
    # Exercise the full concurrent-scheduler path on a plain host: an
    # iterate_over stage on a SLURM env, run via the mock scheduler so jobs
    # execute locally. Covers concurrent fan-out, granular per-item caching,
    # resume-after-failure, and the queue command.
    env = {**os.environ, "CALKIT_MOCK_SCHEDULER": "1"}
    subprocess.check_call(["calkit", "init"])
    with open("run.sh", "w") as f:
        # Fail for x==3 only while the FAIL sentinel exists. FAIL is not a
        # declared dependency, so removing it leaves the other items cached.
        f.write('if [ "$1" = "3" ] && [ -f FAIL ]; then exit 1; fi\n')
        f.write('echo "$1" > "out-$1.txt"\n')
    ck_info = {
        "environments": {
            "slurm": {"kind": "slurm"},
        },
        "pipeline": {
            "stages": {
                "sweep": {
                    "kind": "shell-script",
                    "script_path": "run.sh",
                    "environment": "slurm",
                    "args": ["{x}"],
                    "iterate_over": [{"arg_name": "x", "values": [1, 2, 3]}],
                    "outputs": ["out-{x}.txt"],
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    # First run: x=3 fails, so the run aborts, but x=1 and x=2 succeed and
    # are cached.
    open("FAIL", "w").close()
    result = subprocess.run(["calkit", "run"], env=env)
    assert result.returncode != 0
    assert os.path.exists("out-1.txt")
    assert os.path.exists("out-2.txt")
    assert not os.path.exists("out-3.txt")
    # Mock job data is isolated under the always-ignored .calkit/local.
    assert os.path.isdir(".calkit/local/mock-scheduler")
    assert not subprocess.check_output(
        ["git", "status", "--porcelain"], text=True
    ).count("mock-scheduler")
    # Resume: dropping the (non-dependency) sentinel reruns only the failed
    # item; the cached items are skipped by DVC.
    os.remove("FAIL")
    out = subprocess.check_output(["calkit", "run"], env=env, text=True)
    assert os.path.exists("out-3.txt")
    assert "Running stage 'sweep@3'" in out
    assert "Running stage 'sweep@1'" not in out
    # The queue command reports the locally tracked mock jobs.
    queue = subprocess.check_output(
        ["calkit", "scheduler", "queue"], env=env, text=True
    )
    assert "sweep@3" in queue


@skipif_windows_mock_scheduler
def test_run_with_mock_scheduler_flag(tmp_dir):
    # The --mock-scheduler/-K flag runs scheduler stages locally without
    # needing CALKIT_MOCK_SCHEDULER in the environment, and records
    # "mocked": true in the scheduler env lock so a mocked run and a real run
    # produce different lock content.
    subprocess.check_call(["calkit", "init"])
    with open("run.sh", "w") as f:
        f.write("echo hello > out.txt\n")
    ck_info = {
        "environments": {"slurm": {"kind": "slurm"}},
        "pipeline": {
            "stages": {
                "do-thing": {
                    "kind": "shell-script",
                    "script_path": "run.sh",
                    "environment": "slurm",
                    "outputs": ["out.txt"],
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    # Ensure the env var is absent so the flag is what enables the mock
    env = {k: v for k, v in os.environ.items() if k != "CALKIT_MOCK_SCHEDULER"}
    subprocess.check_call(["calkit", "run", "-K"], env=env)
    assert os.path.exists("out.txt")
    with open(".calkit/env-locks/slurm/info.json") as f:
        lock = json.load(f)
    assert lock["mocked"] is True


@skipif_windows_mock_scheduler
def test_run_concurrent_scheduler_table_iteration_with_mock(tmp_dir):
    # Table-like iteration (arg_name as a list) compiles to a dict-valued DVC
    # matrix that DVC names by index (sweep@_arg00, ...) while the scheduler
    # job names use the comma-joined values (sweep@1,a). Verify the concurrent
    # path handles both naming schemes and multi-arg output templating.
    env = {**os.environ, "CALKIT_MOCK_SCHEDULER": "1"}
    subprocess.check_call(["calkit", "init"])
    with open("run.sh", "w") as f:
        f.write('echo "$1 $2" > "out-$1-$2.txt"\n')
    ck_info = {
        "environments": {"slurm": {"kind": "slurm"}},
        "pipeline": {
            "stages": {
                "sweep": {
                    "kind": "shell-script",
                    "script_path": "run.sh",
                    "environment": "slurm",
                    "args": ["{var1}", "{var2}"],
                    "iterate_over": [
                        {
                            "arg_name": ["var1", "var2"],
                            "values": [[1, "a"], [2, "b"], [3, "c"]],
                        }
                    ],
                    "outputs": ["out-{var1}-{var2}.txt"],
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    out = subprocess.check_output(["calkit", "run"], env=env, text=True)
    # Every (var1, var2) combination ran and wrote a correctly templated file.
    assert "Submitting 3 'sweep' jobs" in out
    for var1, var2 in [(1, "a"), (2, "b"), (3, "c")]:
        path = f"out-{var1}-{var2}.txt"
        assert os.path.exists(path)
        with open(path) as f:
            assert f.read().strip() == f"{var1} {var2}"
    # Scheduler job names use the comma-joined values, not the DVC index.
    queue = subprocess.check_output(
        ["calkit", "scheduler", "queue"], env=env, text=True
    )
    assert "sweep@1,a" in queue
    assert "sweep@3,c" in queue


@skipif_windows_mock_scheduler
def test_run_concurrent_scheduler_force_runs_each_item_once(tmp_dir):
    # --force must not run a sweep twice (once in the concurrent prepass and
    # again in the main repro). Under --force the prepass is skipped, so each
    # item runs exactly once per `calkit run`, serially via the main repro.
    env = {**os.environ, "CALKIT_MOCK_SCHEDULER": "1"}
    subprocess.check_call(["calkit", "init"])
    with open("run.sh", "w") as f:
        # Append a line each execution so we can count how many times each
        # item actually ran.
        f.write('echo x >> "runs-$1.txt"\n')
        f.write('echo "$1" > "out-$1.txt"\n')
    ck_info = {
        "environments": {"slurm": {"kind": "slurm"}},
        "pipeline": {
            "stages": {
                "sweep": {
                    "kind": "shell-script",
                    "script_path": "run.sh",
                    "environment": "slurm",
                    "args": ["{x}"],
                    "iterate_over": [{"arg_name": "x", "values": [1, 2]}],
                    "outputs": ["out-{x}.txt"],
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "run"], env=env)
    subprocess.check_call(["calkit", "run", "--force"], env=env)
    # One run + one forced run = two executions per item (not three).
    for x in (1, 2):
        with open(f"runs-{x}.txt") as f:
            assert len(f.read().splitlines()) == 2


@skipif_windows_mock_scheduler
def test_run_concurrent_scheduler_resume_after_disconnect(tmp_dir):
    # If the master process is killed while jobs run, a job that already
    # finished on the scheduler must not be resubmitted on the next run: the
    # jobs database lets Calkit recognize the prior submission left the queue
    # and reuse its recorded exit status instead of rerunning the work.
    # We simulate the disconnect by deleting dvc.lock (so DVC re-runs the
    # stage) while the outputs and job records remain on disk.
    env = {**os.environ, "CALKIT_MOCK_SCHEDULER": "1"}
    subprocess.check_call(["calkit", "init"])
    with open("run.sh", "w") as f:
        f.write('echo x >> "runs-$1.txt"\n')
        f.write('echo "$1" > "out-$1.txt"\n')
    ck_info = {
        "environments": {"slurm": {"kind": "slurm"}},
        "pipeline": {
            "stages": {
                "sweep": {
                    "kind": "shell-script",
                    "script_path": "run.sh",
                    "environment": "slurm",
                    "args": ["{x}"],
                    "iterate_over": [{"arg_name": "x", "values": [1, 2]}],
                    "outputs": ["out-{x}.txt"],
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "run"], env=env)
    for x in (1, 2):
        with open(f"runs-{x}.txt") as f:
            assert len(f.read().splitlines()) == 1
    # Simulate a disconnect where dvc.lock never got updated, and where the
    # scheduler has since purged the finished jobs from its history (here, the
    # mock's status sentinels). The recorded exit codes still tell us the jobs
    # succeeded, so they are harvested rather than re-polled or rerun.
    os.remove("dvc.lock")
    shutil.rmtree(os.path.join(".calkit", "local", "mock-scheduler"))
    out = subprocess.check_output(["calkit", "run"], env=env, text=True)
    assert "already left the queue" in out
    # The completed jobs are not resubmitted, so the run counts stay at one.
    for x in (1, 2):
        with open(f"runs-{x}.txt") as f:
            assert len(f.read().splitlines()) == 1


@skipif_windows_mock_scheduler
def test_run_scheduler_reruns_when_exit_status_unknown(tmp_dir):
    # Safety: if a finished job's exit status cannot be determined on a later
    # run---the scheduler purged it from history and we never recorded a code
    # (e.g. disconnected before the job finished)---Calkit must rerun rather
    # than assume success. Otherwise a job that actually failed would be cached
    # as done just because its declared outputs happen to exist on disk.
    from sqlitedict import SqliteDict

    from calkit.cli.scheduler import JOBS_DB_PATH

    env = {**os.environ, "CALKIT_MOCK_SCHEDULER": "1"}
    subprocess.check_call(["calkit", "init"])
    with open("run.sh", "w") as f:
        f.write('echo x >> "runs-$1.txt"\n')
        f.write('echo "$1" > "out-$1.txt"\n')
    ck_info = {
        "environments": {"slurm": {"kind": "slurm"}},
        "pipeline": {
            "stages": {
                "sweep": {
                    "kind": "shell-script",
                    "script_path": "run.sh",
                    "environment": "slurm",
                    "args": ["{x}"],
                    "iterate_over": [{"arg_name": "x", "values": [1, 2]}],
                    "outputs": ["out-{x}.txt"],
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "run"], env=env)
    for x in (1, 2):
        with open(f"runs-{x}.txt") as f:
            assert len(f.read().splitlines()) == 1
    # Wipe the recorded exit codes and the scheduler's status sentinels so the
    # jobs' outcome is unknowable on the next run, as after a long disconnect.
    with SqliteDict(JOBS_DB_PATH, autocommit=True) as jobs:
        for name in list(jobs):
            info = jobs[name]
            info.pop("exit_code", None)
            jobs[name] = info
    shutil.rmtree(os.path.join(".calkit", "local", "mock-scheduler"))
    os.remove("dvc.lock")
    out = subprocess.check_output(["calkit", "run"], env=env, text=True)
    # The unknown-outcome jobs are rerun, not harvested as successful.
    assert "already left the queue" not in out
    for x in (1, 2):
        with open(f"runs-{x}.txt") as f:
            assert len(f.read().splitlines()) == 2


@skipif_windows_mock_scheduler
def test_run_downstream_does_not_submit_unrelated_sweep(tmp_dir):
    # A narrowed run (e.g. --downstream) leaves positional targets empty, so
    # the concurrent prepass must be skipped entirely---otherwise it would
    # submit every iterate_over scheduler stage, launching cluster jobs the
    # user never asked for. Here 'sweep' is unrelated to the requested 'other'
    # stage and must not run.
    env = {**os.environ, "CALKIT_MOCK_SCHEDULER": "1"}
    subprocess.check_call(["calkit", "init"])
    with open("other.sh", "w") as f:
        f.write("echo done > other.txt\n")
    with open("run.sh", "w") as f:
        f.write('echo "$1" > "out-$1.txt"\n')
    ck_info = {
        "environments": {"slurm": {"kind": "slurm"}},
        "pipeline": {
            "stages": {
                "other": {
                    "kind": "shell-script",
                    "script_path": "other.sh",
                    "environment": "slurm",
                    "outputs": ["other.txt"],
                },
                "sweep": {
                    "kind": "shell-script",
                    "script_path": "run.sh",
                    "environment": "slurm",
                    "args": ["{x}"],
                    "iterate_over": [{"arg_name": "x", "values": [1, 2]}],
                    "outputs": ["out-{x}.txt"],
                },
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "run", "--downstream", "other"], env=env)
    # The requested stage ran; the unrelated sweep did not.
    assert os.path.exists("other.txt")
    assert not os.path.exists("out-1.txt")
    assert not os.path.exists("out-2.txt")


def test_add_dvc_pointer_unignored(tmp_dir):
    """Test that calkit add --to=dvc ensures the .dvc pointer is unignored."""
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["calkit", "init"])
    os.makedirs("pubs/defense/ppt")
    with open("pubs/defense/ppt/.gitignore", "w") as f:
        f.write("*.pdf*\n")
    pdf_path = "pubs/defense/ppt/McCabe.pdf"
    with open(pdf_path, "w") as f:
        f.write("dummy pdf content")
    subprocess.check_call(["calkit", "add", "--to=dvc", pdf_path])
    # Assert pointer exists
    dvc_file = f"{pdf_path}.dvc"
    assert os.path.exists(dvc_file)
    # Assert pointer is NOT ignored (should return 1)
    res = subprocess.run(["git", "check-ignore", "-q", dvc_file])
    assert res.returncode == 1
    # Assert data file IS still ignored
    res_data = subprocess.run(["git", "check-ignore", "-q", pdf_path])
    assert res_data.returncode == 0
    # Assert it was staged
    staged = calkit.git.get_staged_files()
    assert dvc_file in staged


def test_add_dvc_pointer_unignored_idempotent(tmp_dir):
    """Test that the unignore logic does not duplicate lines."""
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["calkit", "init"])
    os.makedirs("data")
    with open("data/.gitignore", "w") as f:
        f.write("*.pdf*\n")
    pdf_path = "data/doc.pdf"
    with open(pdf_path, "w") as f:
        f.write("doc")
    subprocess.check_call(["calkit", "add", "--to=dvc", pdf_path])
    with open("data/.gitignore") as f:
        content1 = f.read()
    # Second add should not duplicate
    subprocess.check_call(["calkit", "add", "--to=dvc", pdf_path])
    with open("data/.gitignore") as f:
        content2 = f.read()
    assert content1 == content2
    assert content1.count("!*.dvc") == 1


def test_call_dvc_passthrough_hint(tmp_dir):
    """Test that calkit dvc add prints a hint if .dvc is ignored."""
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["calkit", "init"])
    os.makedirs("data")
    with open("data/.gitignore", "w") as f:
        f.write("*.pdf*\n")
    pdf_path = "data/doc.pdf"
    with open(pdf_path, "w") as f:
        f.write("doc")
    # Run the passthrough dvc add which will fail because it's ignored
    res = subprocess.run(
        ["calkit", "dvc", "add", pdf_path], capture_output=True, text=True
    )
    assert res.returncode != 0
    assert (
        "Hint: If DVC failed because a .dvc pointer file is git-ignored"
        in res.stderr
    )


def test_run_captures_stage_logs(tmp_dir, capsys):
    """Test that stage stdout and stderr are captured and teed to the terminal."""
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["calkit", "init"])
    # Create a Python script that prints to stdout and stderr
    script = (
        "import sys\n"
        "sys.stdout.write('OUT_MARKER\\n')\n"
        "sys.stderr.write('ERR_MARKER\\n')\n"
    )
    with open("stage_script.py", "w") as f:
        f.write(script)
    # Add a stage manually via dvc.yaml
    dvc_yaml = {
        "stages": {
            "test_stage": {
                "cmd": "python stage_script.py",
            }
        }
    }
    with open("dvc.yaml", "w") as f:
        import yaml
        yaml.dump(dvc_yaml, f)
    
    # Run pipeline and capture output at terminal
    res = subprocess.run(["calkit", "run"], capture_output=True, text=True)
    assert res.returncode == 0
    # Both markers should be in the terminal output
    assert "OUT_MARKER" in res.stdout
    assert "ERR_MARKER" in res.stdout  # dvc cmd runner outputs stderr to stdout usually, or we tee stderr to stdout
    
    # Verify the log file was created in .calkit/local/logs
    local_logs = os.path.join(".calkit", "local", "logs")
    log_files = [f for f in os.listdir(local_logs) if "test_stage.log" in f]
    assert len(log_files) == 1
    with open(os.path.join(local_logs, log_files[0])) as f:
        log_content = f.read()
    assert "OUT_MARKER" in log_content
    assert "ERR_MARKER" in log_content


def test_run_captures_stage_logs_failure(tmp_dir):
    """Test that stage output is captured even if the stage fails."""
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["calkit", "init"])
    # Create a Python script that fails
    script = (
        "import sys\n"
        "sys.stdout.write('FAIL_OUT_MARKER\\n')\n"
        "sys.exit(1)\n"
    )
    with open("stage_fail.py", "w") as f:
        f.write(script)
    dvc_yaml = {
        "stages": {
            "fail_stage": {
                "cmd": "python stage_fail.py",
            }
        }
    }
    with open("dvc.yaml", "w") as f:
        import yaml
        yaml.dump(dvc_yaml, f)
    
    res = subprocess.run(["calkit", "run"], capture_output=True, text=True)
    assert res.returncode != 0
    
    local_logs = os.path.join(".calkit", "local", "logs")
    log_files = [f for f in os.listdir(local_logs) if "fail_stage.log" in f]
    assert len(log_files) == 1
    with open(os.path.join(local_logs, log_files[0])) as f:
        log_content = f.read()
    assert "FAIL_OUT_MARKER" in log_content


def test_run_log_flag_copies_stage_logs(tmp_dir):
    """Test that --log copies stage logs to the tracked directory."""
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["calkit", "init"])
    script = (
        "import sys\n"
        "sys.stdout.write('OUT_MARKER\\n')\n"
    )
    with open("stage_script.py", "w") as f:
        f.write(script)
    dvc_yaml = {
        "stages": {
            "test_stage_log": {
                "cmd": "python stage_script.py",
            }
        }
    }
    with open("dvc.yaml", "w") as f:
        import yaml
        yaml.dump(dvc_yaml, f)
    
    res = subprocess.run(["calkit", "run", "--log"])
    assert res.returncode == 0
    
    tracked_logs = os.path.join(".calkit", "logs")
    log_files = [
        f for f in os.listdir(tracked_logs) if "test_stage_log.log" in f
    ]
    assert len(log_files) == 1
    with open(os.path.join(tracked_logs, log_files[0])) as f:
        log_content = f.read()
    assert "OUT_MARKER" in log_content
