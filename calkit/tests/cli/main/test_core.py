"""Tests for ``cli.main.core``."""

import json
import os
import platform
import shutil
import socket
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from pprint import pprint
from unittest.mock import Mock, patch

import click
import dvc.repo
import git
import pytest
import typer
import yaml
from dvc.exceptions import NotDvcRepoError
from git.exc import InvalidGitRepositoryError

import calkit
import calkit.cli.main
import calkit.schema
import calkit.windows
from calkit.cli.core import complete_stage_names
from calkit.cli.main.core import (
    STAGE_OUTPUT_END,
    STAGE_OUTPUT_START,
    STAGE_RUNS_FPATH,
    _get_iteration_item_counts,
    _get_matplotlib_font_warnings_by_stage,
    _get_running_pipeline_status,
    _get_subproject_targets_for_run,
    _print_running_pipeline_status,
    _prune_run_logs,
    _run_dvc_repro,
    _stage_run_info_from_log_content,
    _stage_target_from_cmd,
    _to_shell_cmd,
    _warn_on_stale_calkit_env,
)
from calkit.cli.main.core import (
    app as calkit_app,
)
from calkit.cli.main.core import main as calkit_main

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


@pytest.mark.parametrize(
    ("subproject_path", "targets", "include_dvc_yaml_targets", "expected"),
    [
        ("sub1", None, False, (True, None)),
        ("sub1", ["parent-stage"], False, (False, None)),
        ("sub1", ["sub1"], False, (True, None)),
        ("nested/sub1", ["sub1:build"], False, (True, ["build"])),
        (
            "nested/sub1",
            ["nested/sub1:build"],
            False,
            (True, ["build"]),
        ),
        (
            "nested/sub1",
            ["nested/sub1/dvc.yaml"],
            True,
            (True, None),
        ),
        (
            "nested/sub1",
            ["nested/sub1/dvc.yaml:build"],
            True,
            (True, ["build"]),
        ),
        (
            "nested/sub1",
            ["nested/sub1/dvc.yaml:build"],
            False,
            (False, None),
        ),
    ],
)
def test_get_subproject_targets_for_run(
    subproject_path, targets, include_dvc_yaml_targets, expected
):
    assert (
        _get_subproject_targets_for_run(
            subproject_path,
            targets,
            include_dvc_yaml_targets=include_dvc_yaml_targets,
        )
        == expected
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
    # With no calkit.yaml present, init creates one holding only the schema
    # modeline, so editors validate and autocomplete it
    assert not os.path.isfile("calkit.yaml")
    subprocess.check_call(["calkit", "init"])
    assert os.path.isfile("calkit.yaml")
    assert calkit.load_calkit_info() == {}
    with open("calkit.yaml") as f:
        assert f.read() == calkit.schema.MODELINE + "\n"
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
    # An existing DVC repo with no calkit.yaml is left alone rather than
    # failing on DVC's refusal to initialize over an existing .dvc (#1013)
    os.remove(os.path.join("sub", "calkit.yaml"))
    assert os.path.isdir(os.path.join("sub", ".dvc"))
    result = subprocess.run(
        ["calkit", "init"],
        cwd="sub",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "already initialized" in result.stdout.lower()
    assert os.path.isfile(os.path.join("sub", "calkit.yaml"))
    assert calkit.load_calkit_info(wdir="sub") == {}
    # A .dvc directory left behind by an interrupted init has no config in
    # it, so it is re-initialized rather than taken for a working repo
    os.remove(os.path.join("sub", ".dvc", "config"))
    subprocess.check_call(["calkit", "init"], cwd="sub")
    assert os.path.isfile(os.path.join("sub", ".dvc", "config"))
    # --no-commit stages the initial files without committing, so a
    # bootstrap (as run by xr) can be rolled back by restoring files
    os.makedirs("nocommit")
    root_repo = git.Repo(".")
    n_commits_before = root_repo.head.commit.count()
    subprocess.check_call(["calkit", "init", "--no-commit"], cwd="nocommit")
    staged = calkit.git.get_staged_files(repo=root_repo)
    assert "nocommit/.dvc/config" in staged
    assert "nocommit/calkit.yaml" in staged
    assert root_repo.head.commit.count() == n_commits_before


@skipif_windows_docker
@pytest.mark.needs("docker")
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
@pytest.mark.needs("juliaup")
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
            # Example is the registry's trivial test package; nothing here
            # depends on which packages are installed, and heavier ones cost
            # tens of seconds each to download and precompile
            "Example",
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
                    "using Example; using PkgVersion; "
                    "println(PkgVersion.Version(Example))"
                ),
            ]
        )
        .decode()
        .strip()
    )
    assert out.splitlines()[-1].split(".")[0].isdigit()
    # Check that we can run a script with arguments
    with open("julia_script.jl", "w") as f:
        f.write(
            "import PkgVersion; "
            " using Example; "
            'println("PkgVersion: ", PkgVersion.Version(Example)); '
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


def test_run_in_env_uv_extras(tmp_dir):
    def write_extras(extras: list) -> None:
        env = {"kind": "uv", "path": "pyproject.toml", "extras": extras}
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump({"environments": {"main": env}}, f)

    subprocess.check_call(["uv", "init", "--bare"])
    subprocess.check_call(["uv", "add", "--optional", "accel", "six"])
    # Adding it installs it, so start from an environment without it
    subprocess.check_call(["uv", "sync"])
    cmd = ["calkit", "xenv", "-n", "main", "--", "python", "-c", "import six"]
    # An extra meant for another machine, e.g., one with a GPU this one
    # lacks, is neither installed nor an error
    write_extras(
        [{"name": "accel", "when": [{"gpu_arch_is": "calkit-test-no-such"}]}]
    )
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode != 0
    assert "No module named 'six'" in res.stderr
    # A mistake in one is a clean error, not a traceback
    write_extras([{"name": "accel", "when": [{"gpu_arch": "gfx1201"}]}])
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode != 0
    assert "is invalid" in res.stderr and "Traceback" not in res.stderr
    # One meant for this machine is installed by 'uv run', even when the
    # environment isn't checked first
    any_os = ["linux", "macos", "windows"]
    write_extras([{"name": "accel", "when": [{"os_is": any_os}]}])
    subprocess.check_call(cmd[:4] + ["--no-check"] + cmd[4:])
    # And by checking the environment, as is one given by name alone
    subprocess.check_call(["uv", "sync"])
    write_extras(["accel"])
    subprocess.check_call(
        ["calkit", "check", "environment", "-n", "main", "--force"]
    )
    subprocess.check_call(
        ["uv", "run", "--no-sync", "python", "-c", "import six"]
    )


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


def test_run_in_env_system(tmp_dir):
    def _write_envs_to_ck_info(environments: dict) -> None:
        # Dumped rather than written as literal YAML so the test says what
        # the environment is, not how it's spelled
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump({"environments": environments}, f)

    # A named system env runs the command on this machine, like the built-in
    # '_system' env, but with a lock file recording what it pinned
    _write_envs_to_ck_info({"sys": {"kind": "system", "lock": ["os"]}})
    out = subprocess.check_output(
        ["calkit", "xenv", "-n", "sys", "--", "python", "-c", "print('hi')"],
        text=True,
    )
    assert "hi" in out
    sys_lock = os.path.join(".calkit", "env-locks", "sys", "info.json")
    with open(sys_lock) as f:
        assert set(json.load(f)) == {"os"}
    # A lock from another machine stops a run, even with --no-check
    with open(sys_lock, "w") as f:
        json.dump({"os": "SomeOtherOS"}, f)
    for extra in ([], ["--no-check"]):
        res = subprocess.run(
            ["calkit", "xenv", "-n", "sys", *extra, "--", "echo", "hi"],
            capture_output=True,
            text=True,
        )
        assert res.returncode != 0
        assert "locked to a different machine" in res.stdout + res.stderr
        assert "calkit update env -n sys --lock" in res.stdout + res.stderr
        with open(sys_lock) as f:
            assert json.load(f) == {"os": "SomeOtherOS"}
    # The up-front check only warns, so up-to-date stages can be skipped
    res = subprocess.run(
        ["calkit", "check", "env", "-n", "sys"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "locked to a different machine" in res.stdout + res.stderr
    subprocess.check_call(["calkit", "update", "env", "-n", "sys", "--lock"])
    out = subprocess.check_output(
        ["calkit", "xenv", "-n", "sys", "--", "python", "-c", "print('hi')"],
        text=True,
    )
    assert "hi" in out
    # With 'relock: auto' a run there rewrites the lock instead of failing
    with open(sys_lock, "w") as f:
        json.dump({"os": "SomeOtherOS"}, f)
    _write_envs_to_ck_info(
        {"sys": {"kind": "system", "lock": ["os"], "relock": "auto"}}
    )
    subprocess.check_call(
        ["calkit", "xenv", "-n", "sys", "--no-check", "--", "echo", "hi"]
    )
    with open(sys_lock) as f:
        assert json.load(f) != {"os": "SomeOtherOS"}
    # '--setup' runs its commands in the same shell as the command, so
    # what they set is visible there, and it runs in bash by default so
    # 'source' works---the reason most of these exist. What to run is
    # decided by the pipeline compiler, which merges the environment's
    # 'default_setup' with the stage's own; 'calkit xenv' just runs what
    # it is handed.
    with open("setup_env.sh", "w") as f:
        f.write("export CK_TEST_SETUP=from-setup\n")
    _write_envs_to_ck_info(
        {"sys2": {"kind": "system", "inputs": ["setup_env.sh"]}}
    )
    out = subprocess.check_output(
        [
            "calkit",
            "xenv",
            "-n",
            "sys2",
            "--setup",
            "source setup_env.sh",
            "--",
            "python",
            "-c",
            "import os; print(os.environ['CK_TEST_SETUP'])",
        ],
        text=True,
    )
    assert "from-setup" in out
    # Several are chained in order, into the one shell
    out = subprocess.check_output(
        [
            "calkit",
            "xenv",
            "-n",
            "sys2",
            "--setup",
            "export CK_TEST_ORDER=first",
            "--setup",
            "export CK_TEST_ORDER=$CK_TEST_ORDER-second",
            "--",
            "python",
            "-c",
            "import os; print(os.environ['CK_TEST_ORDER'])",
        ],
        text=True,
    )
    assert out.strip() == "first-second"
    # A compiled stage passes a file rather than quoted commands, since a
    # path survives cmd.exe on Windows and a POSIX shell elsewhere while
    # quoted text survives neither
    os.makedirs(os.path.join(".calkit", "stage-setup"), exist_ok=True)
    setup_json = os.path.join(".calkit", "stage-setup", "s.json")
    with open(setup_json, "w") as f:
        json.dump(["source setup_env.sh"], f)
    out = subprocess.check_output(
        [
            "calkit",
            "xenv",
            "-n",
            "sys2",
            "--setup-file",
            setup_json,
            "--",
            "python",
            "-c",
            "import os; print(os.environ['CK_TEST_SETUP'])",
        ],
        text=True,
    )
    assert "from-setup" in out
    # Saying it twice in two ways is refused rather than one winning
    res = subprocess.run(
        [
            "calkit",
            "xenv",
            "-n",
            "sys2",
            "--setup-file",
            setup_json,
            "--setup",
            "true",
            "--",
            "echo",
            "hi",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "not both" in res.stdout + res.stderr
    # Nothing about the machine is locked and the shell is the default, so
    # there is no lock file: the setup commands live in the stage's
    # command, where DVC already watches them
    assert not os.path.isfile(
        os.path.join(".calkit", "env-locks", "sys2", "info.json")
    )
    # Setup commands are refused for an env kind that has nowhere to run
    # them, rather than silently dropped
    _write_envs_to_ck_info({"img": {"kind": "docker", "image": "x"}})
    res = subprocess.run(
        ["calkit", "xenv", "-n", "img", "--setup", "true", "--", "echo", "hi"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "only applies to a 'system' environment" in res.stdout + res.stderr
    # A failing setup command stops the stage rather than running it
    # without whatever the setup was meant to provide
    _write_envs_to_ck_info({"bad": {"kind": "system"}})
    res = subprocess.run(
        [
            "calkit",
            "xenv",
            "-n",
            "bad",
            "--setup",
            "exit 3",
            "--",
            "python",
            "-c",
            "print('ran')",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "ran" not in res.stdout
    # A host naming this machine runs here rather than connecting to it
    _write_envs_to_ck_info(
        {"here": {"kind": "system", "host": socket.gethostname()}}
    )
    out = subprocess.check_output(
        ["calkit", "xenv", "-n", "here", "--", "python", "-c", "print('hi')"],
        text=True,
    )
    assert "hi" in out
    # A workspace directory is derived from the project name, so a project
    # without one has nothing to derive from and says so rather than
    # picking a directory it was never told about. No user is needed: SSH
    # resolves that itself.
    _write_envs_to_ck_info(
        {"remote": {"kind": "system", "host": "not-this-box.invalid"}}
    )
    res = subprocess.run(
        ["calkit", "xenv", "-n", "remote", "--", "echo", "hi"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    combined = res.stdout + res.stderr
    assert "'wdir'" in combined
    assert "'user'" not in combined


def test_open_env_shell(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from calkit.environments import shell as env_shell

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CALKIT_SHELL", raising=False)
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "environments": {
                    "py": {"kind": "uv", "path": "pyproject.toml"},
                    "jl": {"kind": "julia", "path": "Project.toml"},
                }
            },
            f,
        )
    opened = {}

    def start(shell, activation, base_env=None):
        opened["shell"] = shell
        opened["activation"] = activation
        return 4

    monkeypatch.setattr(env_shell, "start", start)

    def shell(*args: str):
        return CliRunner().invoke(calkit_app, ["shell", *args])

    # The environment has to be named
    res = shell()
    assert res.exit_code == 1
    assert "Name the environment to open with '-e', one of: py, jl" in (
        res.output
    )
    # Ones with nothing to activate in a shell are refused
    res = shell("-e", "_system")
    assert res.exit_code == 1
    assert "nothing to activate" in res.output
    res = shell("-e", "nope")
    assert "Environment 'nope' does not exist" in res.output
    res = shell("-e", "jl")
    assert res.exit_code == 1
    assert "calkit xenv -n jl -- <command>" in res.output
    assert not opened
    # The shell opens with the environment activated, and its exit status
    # is this one's
    res = shell("-e", "py", "--no-check", "--shell", "/bin/zsh")
    assert res.exit_code == 4, res.output
    assert "Opening zsh in environment 'py'; run 'exit' to leave" in (
        res.output
    )
    assert opened["shell"] == "/bin/zsh"
    assert opened["activation"].env_vars["VIRTUAL_ENV"] == os.path.join(
        str(tmp_path), ".venv"
    )
    # Not inside another
    monkeypatch.setenv("CALKIT_SHELL", "py")
    res = shell("-e", "py", "--no-check")
    assert res.exit_code == 1
    assert "Already in a shell for environment 'py'" in res.output


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
    # Arguments survive the shell as they were, backslashes and tabs too
    args = [
        "2026-06-09 12:00:00",
        "a b\\",
        "a b\\\\",
        "a\tb",
        'say "hi"',
        'say \\"hi\\"',
        "C:\\My Data\\x",
    ]
    shell_cmd = _to_shell_cmd(
        [
            sys.executable,
            "-c",
            "import json, sys; print(json.dumps(sys.argv[1:]))",
        ]
        + args
    )
    out = subprocess.check_output(shell_cmd, shell=True, text=True)
    assert json.loads(out) == args


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
    # With --existing, only changed files Git already tracks are added, even
    # from a directory
    subprocess.check_call(["git", "reset"])
    with open("src/code.py", "w") as f:
        f.write("# Changed again")
    with open("src/new.py", "w") as f:
        f.write("# New")
    subprocess.check_call(["calkit", "add", "-e", "src", "dry_small.txt"])
    staged = calkit.git.get_staged_files()
    assert "src/code.py" in staged
    assert "src/new.py" not in staged
    assert "dry_small.txt" not in staged
    subprocess.check_call(["git", "reset"])
    subprocess.check_call(["calkit", "add", "--existing", "."])
    staged = calkit.git.get_staged_files()
    assert "src/code.py" in staged
    assert "src/new.py" not in staged
    assert "dry_small.txt" not in staged
    # With --to, '.' doesn't bring untracked files along either
    subprocess.check_call(["git", "reset"])
    subprocess.check_call(["calkit", "add", "-e", "--to", "git", "."])
    staged = calkit.git.get_staged_files()
    assert "src/code.py" in staged
    assert "src/new.py" not in staged
    assert "dry_small.txt" not in staged
    # Paths are relative to the working directory
    subprocess.check_call(["git", "reset"])
    subprocess.check_call(
        ["calkit", "add", "-e", "code.py", "new.py"], cwd="src"
    )
    staged = calkit.git.get_staged_files()
    assert "src/code.py" in staged
    assert "src/new.py" not in staged


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


def test_figure_storage(tmp_dir, monkeypatch, capsys):
    from calkit.cli.main.core import _offer_dvc_for_large_figures

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], text=True)

    subprocess.check_call(["calkit", "init"])
    # A small figure goes in Git and a big one in DVC, saying the real limit
    with open("small.png", "wb") as f:
        f.write(os.urandom(1000))
    with open("big.pdf", "wb") as f:
        f.write(os.urandom(1_100_000))
    out = subprocess.check_output(
        ["calkit", "add", "small.png", "big.pdf"], text=True
    )
    assert "greater than 1 MB" in out
    assert git("ls-files", "small.png").strip() == "small.png"
    assert not git("ls-files", "big.pdf").strip()
    assert os.path.isfile("big.pdf.dvc")
    # An output DVC will cache isn't Git's, even before its first run
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = {
        "stages": {
            "make": {
                "kind": "shell-command",
                "environment": "_system",
                "command": (
                    'python -c "import os; '
                    "[open(p, 'wb').write(os.urandom(1_100_000)) "
                    "for p in ('kept.png', 'moved.png')]; "
                    "open('declared.png', 'wb').write(b'png')\""
                ),
                "outputs": [
                    {"path": "kept.png", "storage": "git"},
                    {"path": "moved.png", "storage": "git"},
                    "declared.png",
                ],
            }
        }
    }
    calkit.save_calkit_info(ck_info)
    subprocess.check_call(["calkit", "status"], stdout=subprocess.DEVNULL)
    with open("declared.png", "wb") as f:
        f.write(b"png")
    subprocess.check_call(
        ["calkit", "add", "declared.png"], stdout=subprocess.DEVNULL
    )
    assert not git("ls-files", "declared.png").strip()
    assert not os.path.isfile("declared.png.dvc")
    subprocess.check_call(["calkit", "run"], stdout=subprocess.DEVNULL)
    git("add", "-A")
    git("reset", "-q", "--", "kept.png", "moved.png")
    git("commit", "-qm", "Set up")
    # Without a terminal it says how
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert _offer_dvc_for_large_figures() == []
    assert "path-storage kept.png --to dvc" in capsys.readouterr().out
    # With one, each is up to the person
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr(
        "typer.confirm", lambda text, default=None: "moved.png" in text
    )
    assert _offer_dvc_for_large_figures() == ["moved.png"]
    assert not git("ls-files", "moved.png").strip()
    stage = calkit.load_calkit_info()["pipeline"]["stages"]["make"]
    assert "moved.png" in stage["outputs"]
    # One left in Git at that size isn't asked about again
    git("add", "-A")
    git("commit", "-qm", "Keep it")

    def fail(*args, **kwargs):
        raise AssertionError("Asked again")

    monkeypatch.setattr("typer.confirm", fail)
    assert _offer_dvc_for_large_figures() == []
    # A pipeline's Python keeps the time out of what it writes
    ck_info = calkit.load_calkit_info()
    ck_info["environments"] = {"sys": {"kind": "system"}}
    calkit.save_calkit_info(ck_info)
    env = os.environ | {"CALKIT_PIPELINE_RUNNING": "1"}
    env.pop("SOURCE_DATE_EPOCH", None)
    code = "import os; print(os.environ.get('SOURCE_DATE_EPOCH'))"
    out = subprocess.check_output(
        ["calkit", "xenv", "-n", "sys", "--", "python", "-c", code],
        env=env,
        text=True,
    )
    assert out.strip().splitlines()[-1] == calkit.core.OUTPUT_SOURCE_DATE_EPOCH


def test_save_moves_large_figure(tmp_dir, monkeypatch, capsys):
    from calkit.cli.main.core import _offer_dvc_for_large_figures, save

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], text=True)

    def run() -> None:
        p = subprocess.run(["calkit", "run"], capture_output=True, text=True)
        assert p.returncode == 0, p.stdout + p.stderr

    # A project in a subdirectory of its repo, where Git runs from above it
    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "Start")
    os.makedirs("proj")
    monkeypatch.chdir("proj")
    subprocess.check_call(["calkit", "init"], stdout=subprocess.DEVNULL)
    with open("make.py", "w") as f:
        f.write(
            "import os\n"
            "n = int(open('size.txt').read())\n"
            "open('fig.png', 'wb').write(os.urandom(n))\n"
        )
    with open("size.txt", "w") as f:
        f.write("1000")
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = {
        "stages": {
            "make": {
                "kind": "shell-command",
                "environment": "_system",
                "command": "python make.py",
                "inputs": ["make.py", "size.txt"],
                "outputs": [{"path": "fig.png", "storage": "git"}],
            }
        }
    }
    calkit.save_calkit_info(ck_info)
    run()
    git("add", "-A", ".")
    git("commit", "-qm", "Set up")
    with open("size.txt", "w") as f:
        f.write("2000000")
    run()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("typer.confirm", lambda text, default=None: True)
    # One that can't move, here since its stage is out of date, says why,
    # and the rest is still saved
    with open("make.py", "a") as f:
        f.write("# Edited\n")
    with open("notes.md", "w") as f:
        f.write("Notes\n")
    git("add", "notes.md")
    save(paths=["notes.md"], message="Notes", no_push=True)
    assert "is out of date" in capsys.readouterr().err
    assert git("log", "-1", "--format=%s").strip() == "Notes"
    assert git("ls-files", "fig.png").strip() == "fig.png"
    # Moving it commits taking it out of Git too, not only what says to
    run()
    with open("notes.md", "a") as f:
        f.write("More\n")
    save(paths=["notes.md", "make.py"], message="Move", no_push=True)
    committed = git("ls-tree", "-r", "--name-only", "HEAD").split()
    assert "proj/fig.png" not in committed
    assert "/fig.png" in git("show", "HEAD:proj/.gitignore")
    assert "proj/calkit.yaml" not in git("diff", "--name-only", "HEAD")
    assert not git("ls-files", "fig.png").strip()
    # One left in Git at that size isn't asked about again
    subprocess.check_call(
        ["calkit", "update", "path-storage", "fig.png", "--to", "git"],
        stdout=subprocess.DEVNULL,
    )
    git("add", "-A", ".")
    git("commit", "-qm", "Keep it in Git")

    def fail(*args, **kwargs):
        raise AssertionError("Asked again")

    monkeypatch.setattr("typer.confirm", fail)
    assert _offer_dvc_for_large_figures() == []


def test_git_outputs_with_ignored_files(
    tmp_dir: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], text=True)

    def run(*args: str) -> str:
        result = subprocess.run(
            ["calkit", *args], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        return result.stdout + result.stderr

    def get_storage_problems() -> list[dict]:
        out = subprocess.check_output(
            ["calkit", "status", "--json", "-c", "dvc"], text=True
        )
        problems: list[dict] = json.loads(out)["storage"]
        return problems

    subprocess.check_call(["calkit", "init"])
    # Outputs ignored as a whole, and files in them by a general rule
    with open(".gitignore", "a") as f:
        f.write("runs/\n*.log\n__pycache__/\n")
    with open(".dvcignore", "a") as f:
        f.write("__pycache__/\n")
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = {
        "stages": {
            # An iterated stage, whose output paths are templates
            "rebuild": {
                "kind": "shell-command",
                "environment": "_system",
                "command": (
                    "mkdir -p runs/{agent}/__pycache__ "
                    "&& echo a > runs/{agent}/a.txt "
                    "&& echo l > runs/{agent}/write.log "
                    "&& echo b > runs/{agent}/x.bak "
                    "&& echo c > runs/{agent}/__pycache__/c.pyc"
                ),
                "iterate_over": [
                    {"arg_name": "agent", "values": ["one", "two"]}
                ],
                "outputs": [
                    {
                        "path": "runs/{agent}",
                        "storage": "git",
                        "ignore": ["*.bak"],
                    }
                ],
            },
        }
    }
    calkit.save_calkit_info(ck_info)
    git("add", "-A")
    git("commit", "-qm", "Set up")
    # Running stages their outputs stored in Git, and with them the files
    # Git ignores, but not what the output's 'ignore' leaves out, nor what
    # .dvcignore excludes too, which DVC doesn't hash either
    out = run("run")
    assert (
        "Force-added 2 files Git ignores in outputs stored in Git, which "
        "would otherwise be in neither Git nor DVC: runs/one/write.log, "
        "runs/two/write.log ('*.log' in .gitignore)"
    ) in out
    staged = git("diff", "--cached", "--name-only").split()
    for agent in ["one", "two"]:
        assert f"runs/{agent}/a.txt" in staged
        assert f"runs/{agent}/write.log" in staged
        assert f"runs/{agent}/x.bak" not in staged
        assert f"runs/{agent}/__pycache__/c.pyc" not in staged
    # With the ignore files compiling and running changed, e.g., what
    # .dvcignore leaves out, which dvc.lock's hashes depend on
    assert ".dvcignore" in staged
    assert ".gitignore" in staged
    git("add", "-A")
    git("commit", "-qm", "Run")
    assert get_storage_problems() == []
    # What 'ignore' leaves out isn't part of the output, so a clone has
    # everything that is
    clone_dir = str(tmp_path_factory.mktemp("clone"))
    # Without converting line endings, which Windows runners do by default,
    # and which a project settles for itself
    git("clone", "-q", "-c", "core.autocrlf=false", ".", clone_dir)
    result = subprocess.run(
        ["dvc", "status", "rebuild"],
        cwd=clone_dir,
        capture_output=True,
        text=True,
    )
    assert "up to date" in result.stdout, result.stdout
    # Saving an output takes .dvcignore with dvc.lock, whose hashes depend on
    # what it excludes
    ck_info["pipeline"]["stages"]["rebuild"]["outputs"][0]["ignore"] = [
        "*.bak",
        "*.txt",
    ]
    calkit.save_calkit_info(ck_info)
    # Which takes files it now leaves out out of Git
    out = run("run")
    assert (
        "Removed 2 files from Git that outputs stored in it leave out: "
        "runs/one/a.txt, runs/two/a.txt"
    ) in out
    run("save", "runs", "-m", "Ignore text", "--no-push")
    committed = git("show", "--name-only", "--format=", "HEAD").split()
    assert ".dvcignore" in committed
    assert "dvc.lock" in committed
    assert "runs/one/a.txt" in committed
    assert not git("ls-files", "--", "runs/one/a.txt").strip()
    # What else was staged stays staged, and out of the commit
    assert ".calkit/stage-runs.json" not in committed
    assert ".calkit/stage-runs.json" in git("diff", "--cached", "--name-only")
    git("add", "-A")
    git("commit", "-qm", "Save the rest")
    # Without autostaging, nothing is staged, so it's only said
    subprocess.check_call(["dvc", "config", "core.autostage", "false"])
    git("rm", "-q", "--cached", "runs/one/write.log")
    git("commit", "-qm", "Drop the log")
    out = run("run", "--force", "rebuild@one")
    assert "will be in neither Git nor DVC" in out
    assert "'calkit fix storage'" in out
    assert not git("diff", "--cached", "--name-only").strip()
    out = run("fix", "storage")
    assert "runs/one/write.log" in git("diff", "--cached", "--name-only")
    git("add", "-A")
    git("commit", "-qm", "Fix")
    subprocess.check_call(["dvc", "config", "core.autostage", "true"])
    # A new ignored file in an output is found by status, and adding it, or
    # what it's in, adds it, but not an ignored file elsewhere
    with open("runs/one/new.log", "w") as f:
        f.write("n")
    with open("other.log", "w") as f:
        f.write("o")
    out = run("status", "-c", "dvc")
    assert (
        "runs/one is stored in Git, but Git ignores 1 file in it: "
        "runs/one/new.log ('*.log' in .gitignore)"
    ) in out
    assert "'calkit fix storage'" in out
    (problem,) = get_storage_problems()
    assert problem["kind"] == "ignored-files"
    assert problem["files"] == ["runs/one/new.log"]
    assert problem["stage"] == "rebuild@one"
    out = run("add", "--dry-run", "runs")
    assert "Would force-add 1 file Git ignores" in out
    assert not git("diff", "--cached", "--name-only").strip()
    out = run("add", ".")
    assert "Force-added 1 file Git ignores" in out
    staged = git("diff", "--cached", "--name-only").split()
    assert "runs/one/new.log" in staged
    assert "other.log" not in staged
    git("commit", "-qm", "Add")
    # One too large for Git is only reported, whether Git ignores it or not
    for fname in ["big.log", "big.bin"]:
        with open(os.path.join("runs", "one", fname), "wb") as f:
            f.truncate(51 * 1024**2)
    out = run("add", "runs")
    for fname in ["big.log", "big.bin"]:
        assert (
            "Not adding 1 file in outputs stored in Git to it, since they're "
            f"larger than 50 MB: runs/one/{fname}"
        ) in out
    staged = git("diff", "--cached", "--name-only")
    assert "runs/one/big.log" not in staged
    assert "runs/one/big.bin" not in staged
    out = run("add", "--to", "git", "runs/one/big.bin")
    assert "runs/one/big.bin" not in git("diff", "--cached", "--name-only")
    os.remove("runs/one/big.bin")
    result = subprocess.run(
        ["calkit", "fix", "storage"], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "Not adding 1 file" in result.stdout + result.stderr
    assert "runs/one/big.log" not in git("diff", "--cached", "--name-only")
    os.remove("runs/one/big.log")
    # A subproject's stages run from here are staged too, as declared in its
    # own calkit.yaml
    os.makedirs("sub")
    with open(os.path.join("sub", "calkit.yaml"), "w") as f:
        calkit.ryaml.dump(
            {
                "pipeline": {
                    "stages": {
                        "c": {
                            "kind": "shell-command",
                            "environment": "_system",
                            "command": (
                                "mkdir -p out && echo c > out/c.txt "
                                "&& echo l > out/c.log"
                            ),
                            "outputs": [{"path": "out", "storage": "git"}],
                        }
                    }
                }
            },
            f,
        )
    ck_info["subprojects"] = [{"path": "sub"}]
    calkit.save_calkit_info(ck_info)
    out = run("run")
    assert "Force-added 1 file Git ignores" in out
    assert "sub/out/c.log" in out
    staged = git("diff", "--cached", "--name-only").split()
    assert "sub/out/c.txt" in staged
    assert "sub/out/c.log" in staged
    git("add", "-A")
    git("commit", "-qm", "Run sub")
    # And found from here, with the name it's run by
    with open(os.path.join("sub", "out", "new.log"), "w") as f:
        f.write("n")
    (problem,) = get_storage_problems()
    assert problem["path"] == "sub/out"
    assert problem["stage"] == "sub/dvc.yaml:c"
    run("fix", "storage")
    assert "sub/out/new.log" in git("diff", "--cached", "--name-only")


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


def test_stash(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    with open("data.csv", "w") as f:
        f.write("1,2\n")
    with open("notes.txt", "w") as f:
        f.write("hi")
    subprocess.check_call(["calkit", "dvc", "add", "-q", "data.csv"])
    repo = git.Repo()
    repo.git.add(["data.csv.dvc", ".gitignore", "notes.txt"])
    repo.git.commit(["-m", "Add data"])
    # Stashing puts back the last commit, DVC-tracked data included, with
    # the changed data kept in the cache for the stash to point at
    with open("data.csv", "w") as f:
        f.write("3,4\n")
    with open("notes.txt", "w") as f:
        f.write("changed")
    subprocess.check_call(["calkit", "stash", "-m", "Work in progress"])
    with open("data.csv") as f:
        assert f.read() == "1,2\n"
    with open("notes.txt") as f:
        assert f.read() == "hi"
    assert "Work in progress" in repo.git.stash("list")
    # Popping brings it all back
    subprocess.check_call(["calkit", "stash", "pop"])
    with open("data.csv") as f:
        assert f.read() == "3,4\n"
    with open("notes.txt") as f:
        assert f.read() == "changed"
    assert repo.git.stash("list") == ""
    # Including data committed to DVC but not to Git, and with the older
    # --pop spelling
    subprocess.check_call(["calkit", "stash", "push"])
    with open("data.csv") as f:
        assert f.read() == "1,2\n"
    subprocess.check_call(["calkit", "stash", "--pop"])
    with open("data.csv") as f:
        assert f.read() == "3,4\n"
    assert subprocess.run(["calkit", "stash", "drop"]).returncode != 0
    # Deleted data comes back too
    os.remove("data.csv")
    subprocess.check_call(["calkit", "stash"])
    with open("data.csv") as f:
        assert f.read() == "1,2\n"
    repo.git.stash("drop")
    # A changed output is stashed without marking its stage up to date, in
    # a project of its own
    os.makedirs("pipeline")
    os.chdir("pipeline")
    subprocess.check_call(["git", "init", "-q"])
    subprocess.check_call(["calkit", "init"])
    with open("input.txt", "w") as f:
        f.write("in")
    with open("dvc.yaml", "w") as f:
        yaml.dump(
            {
                "stages": {
                    "my-stage": {
                        "cmd": (
                            'python -c "import shutil; '
                            "shutil.copy('input.txt', 'output.txt')\""
                        ),
                        "deps": ["input.txt"],
                        "outs": ["output.txt"],
                    }
                }
            },
            f,
        )
    subprocess.check_call(["dvc", "repro", "-q"])
    subprocess.check_call(["git", "add", "-A"])
    subprocess.check_call(["git", "commit", "-qm", "Run"])
    # A modified DVC-tracked output used to make DVC refuse to check out
    # after the Git stash had already happened
    os.chmod("output.txt", stat.S_IWRITE | stat.S_IREAD)
    with open("output.txt", "w") as f:
        f.write("edited")
    with open("input.txt", "w") as f:
        f.write("new in")
    subprocess.check_call(["calkit", "stash"])
    with open("output.txt") as f:
        assert f.read() == "in"
    with open("input.txt") as f:
        assert f.read() == "in"
    assert not git.Repo().is_dirty()
    # Popping brings back both, and the stage is still out of date since
    # its dependency changed
    subprocess.check_call(["calkit", "stash", "--pop"])
    with open("output.txt") as f:
        assert f.read() == "edited"
    with open("input.txt") as f:
        assert f.read() == "new in"
    status = json.loads(
        subprocess.check_output(["dvc", "status", "--json"], text=True)
    )
    assert "my-stage" in status


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
    # Without a calkit.yaml this isn't a project, which status says
    res = subprocess.run(["calkit", "status"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "not a Calkit project" in res.stdout
    # Unless only non-project categories are asked for
    res = subprocess.run(
        ["calkit", "status", "-c", "git"], capture_output=True, text=True
    )
    assert res.returncode == 0
    assert "calkit.yaml" not in res.stdout + res.stderr
    subprocess.check_call(["calkit", "init"])
    # From a subdirectory of the project, it points to the root instead
    os.makedirs("figures")
    res = subprocess.run(
        ["calkit", "status"], capture_output=True, text=True, cwd="figures"
    )
    assert res.returncode == 0
    assert "not a Calkit project" not in res.stdout
    assert "project is at" in res.stdout
    # Every category read from calkit.yaml warns, keeping JSON parseable
    for category in ["questions", "pipeline", "imports"]:
        res = subprocess.run(
            ["calkit", "status", "--json", "-c", category],
            capture_output=True,
            text=True,
            cwd="figures",
        )
        assert res.returncode == 0
        json.loads(res.stdout)
        assert "project is at" in res.stderr
    # A separate Git repo inside the project isn't part of it
    nested_repo_path = os.path.join("vendor", "otherlib")
    os.makedirs(nested_repo_path)
    subprocess.check_call(["git", "init", "-q"], cwd=nested_repo_path)
    res = subprocess.run(
        ["calkit", "status", "-c", "project"],
        capture_output=True,
        text=True,
        cwd=nested_repo_path,
    )
    assert res.returncode == 0
    assert "not a Calkit project" in res.stdout
    assert "project is at" not in res.stdout
    # The search doesn't reach or pass the home directory
    home_path = os.path.join(os.getcwd(), "home")
    home_subdir_path = os.path.join(home_path, "folder")
    os.makedirs(home_subdir_path)
    home_env = {**os.environ, "HOME": home_path, "USERPROFILE": home_path}
    for wdir, stray_yaml in [(home_path, False), (home_subdir_path, True)]:
        if stray_yaml:
            with open(os.path.join(home_path, "calkit.yaml"), "w") as f:
                f.write("")
        res = subprocess.run(
            ["calkit", "status", "-c", "project"],
            capture_output=True,
            text=True,
            cwd=wdir,
            env=home_env,
        )
        assert res.returncode == 0
        assert "not a Calkit project" in res.stdout
        assert "project is at" not in res.stdout
    subprocess.check_call(["calkit", "new", "status", "in-progress"])
    res = subprocess.run(["calkit", "status"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "No calkit.yaml" not in res.stdout
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
    # Questions are summarized in a section of their own
    os.makedirs("results", exist_ok=True)
    with open("results/summary.json", "w") as f:
        json.dump({"r2": 0.985}, f)
    ck_info = calkit.load_calkit_info()
    ck_info["questions"] = [
        {
            "question": "Does it work?",
            "answer": "Yes, $R^2 = {r2:.3f}$.",
            "evidence": [
                {
                    "kind": "value",
                    "path": "results/summary.json",
                    "key": "r2",
                }
            ],
        },
        {"question": "Is there more?"},
    ]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    out = subprocess.check_output(
        ["calkit", "status", "-c", "questions"]
    ).decode()
    assert "Questions" in out
    assert "2 questions, 1 unanswered" in out
    # The value isn't attributed to any stage, which is an error, so the
    # summary says to go look
    assert "calkit check questions" in out
    # A project with no questions gets no section at all
    ck_info.pop("questions")
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    out = subprocess.check_output(
        ["calkit", "status", "-c", "questions"]
    ).decode()
    assert "Questions" not in out
    # Paths tracked where they shouldn't be are pointed out with DVC's status
    with open("data.csv", "w") as f:
        f.write("a,b\n")
    subprocess.check_call(["calkit", "add", "--to", "dvc", "data.csv"])
    subprocess.check_call(["git", "add", "-f", "data.csv"])
    out = subprocess.check_output(["calkit", "status", "-c", "dvc"], text=True)
    assert "data.csv is tracked by both Git and DVC" in out
    status_json = json.loads(
        subprocess.check_output(["calkit", "status", "-c", "dvc", "--json"])
    )
    assert [p["path"] for p in status_json["storage"]] == ["data.csv"]
    # With --check, a stale pipeline fails, saying what changed and the fix
    check_cmd = ["calkit", "status", "-c", "pipeline", "--no-env-check"]
    check_cmd += ["--check"]
    res = subprocess.run(check_cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = {
        "stages": {
            "copy-git": {
                "kind": "shell-command",
                "command": "cat in.txt > out-git.txt",
                "environment": "_system",
                "inputs": ["in.txt"],
                "outputs": [{"path": "out-git.txt", "storage": "git"}],
            },
            "copy-dvc": {
                "kind": "shell-command",
                "command": "cat in.txt > out-dvc.txt",
                "environment": "_system",
                "inputs": ["in.txt"],
                "outputs": [{"path": "out-dvc.txt", "storage": "dvc"}],
            },
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open("in.txt", "w") as f:
        f.write("a\n")
    subprocess.check_call(["calkit", "run"])
    res = subprocess.run(check_cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert "Pipeline is up to date" in res.stdout
    with open("in.txt", "w") as f:
        f.write("b\n")
    res = subprocess.run(check_cmd, capture_output=True, text=True)
    assert res.returncode == 1
    assert "Out of date:" in res.stderr
    assert "copy-git: in.txt modified" in res.stderr
    assert "copy-dvc: in.txt modified" in res.stderr
    assert "Run 'calkit run' and commit." in res.stderr
    # JSON stays parseable, with the result in it
    res = subprocess.run(
        check_cmd + ["--json"], capture_output=True, text=True
    )
    assert res.returncode == 1
    check_json = json.loads(res.stdout)["check"]
    assert not check_json["passed"]
    assert check_json["summary"] == "Out of date"
    assert sorted(check_json["problems"]) == [
        "copy-dvc: in.txt modified",
        "copy-git: in.txt modified",
    ]
    # Without --check, the result isn't in the JSON and status succeeds
    res = subprocess.run(
        check_cmd[:-1] + ["--json"], capture_output=True, text=True
    )
    assert res.returncode == 0
    assert "check" not in json.loads(res.stdout)
    # An output stored with DVC that wasn't pulled is missing, not modified
    subprocess.check_call(["calkit", "run"])
    os.remove("out-dvc.txt")
    res = subprocess.run(check_cmd, capture_output=True, text=True)
    assert res.returncode == 1
    assert "copy-dvc: out-dvc.txt missing" in res.stderr
    assert "copy-git" not in res.stderr
    assert "'calkit pull' for missing outputs" in res.stderr
    # Checking needs the pipeline's status
    res = subprocess.run(
        ["calkit", "status", "-c", "git", "--check"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "--check needs pipeline category" in res.stderr


def test_status_offers_requirements_for_failed_env_check(
    tmp_dir, monkeypatch: pytest.MonkeyPatch
):
    from typer.testing import CliRunner

    from calkit.pipeline import PipelineStatus

    with open("calkit.yaml", "w") as f:
        yaml.safe_dump({"requirements": ["fake-node"]}, f)
    failed = PipelineStatus(
        has_pipeline=True, environment_checks={"dev": {"success": False}}
    )
    ok = PipelineStatus(has_pipeline=True)
    statuses: list[PipelineStatus] = []
    asked: list[bool] = []
    installs: list[bool] = []

    def check_requirements(ck_info=None, interactive=None, **kwargs):
        asked.append(bool(interactive))
        if not (interactive and installs.pop(0)):
            raise ValueError("app 'fake-node' not found on this machine")

    monkeypatch.setattr(
        calkit.pipeline, "get_status", lambda **kwargs: statuses.pop(0)
    )
    monkeypatch.setattr(calkit, "check_requirements", check_requirements)
    runner = CliRunner()
    # Without a terminal, what's missing is named, but nothing is offered
    monkeypatch.setattr(calkit.core, "is_tty", lambda: False)
    statuses[:] = [failed]
    res = runner.invoke(calkit_app, ["status", "-c", "pipeline"])
    assert res.exit_code == 0, res.output
    assert asked == [False]
    assert "app 'fake-node' not found" in res.output
    assert "'calkit check reqs'" in res.output
    # With one, it's offered, and once installed the status is checked again
    monkeypatch.setattr(calkit.core, "is_tty", lambda: True)
    asked.clear()
    statuses[:] = [failed, ok]
    installs[:] = [True]
    res = runner.invoke(calkit_app, ["status", "-c", "pipeline"])
    assert res.exit_code == 0, res.output
    assert asked == [False, True] and not statuses
    assert "Failed pipeline environment checks" not in res.output
    # Declined, it's reported as without a terminal
    asked.clear()
    statuses[:] = [failed]
    installs[:] = [False]
    res = runner.invoke(calkit_app, ["status", "-c", "pipeline"])
    assert res.exit_code == 0, res.output
    assert asked == [False, True]
    assert "Failed pipeline environment checks for: dev" in res.output
    assert "app 'fake-node' not found" in res.output


def test_no_dvc_repo(tmp_dir, tmp_path):
    # A project with no pipeline, e.g., a website showing imported results,
    # needn't become a DVC repo to run or pull
    git_remote = tmp_path / "git_remote"
    subprocess.check_call(["git", "init", "--bare", str(git_remote)])
    repo = git.Repo.init()
    repo.create_remote("origin", str(git_remote))
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"name": "site"}, f)
    repo.git.add(A=True)
    repo.git.commit(m="Add project")
    repo.git.push("-u", "origin", "HEAD")

    def assert_no_dvc() -> None:
        for path in [".dvc", ".dvcignore", "dvc.yaml"]:
            assert not os.path.exists(path), path

    # Not even checking status, as an editor does when the project opens
    subprocess.check_call(["calkit", "status", "--json", "-c", "pipeline"])
    assert_no_dvc()
    subprocess.check_call(["calkit", "run"])
    assert_no_dvc()
    # A stage that isn't there is still an error
    assert subprocess.run(["calkit", "run", "nope"]).returncode != 0
    out = subprocess.check_output(["calkit", "pull"], text=True)
    assert "DVC" not in out
    assert_no_dvc()
    # In a DVC repo, a pipeline Calkit doesn't declare still runs
    subprocess.check_call(["dvc", "init", "-q"])
    os.makedirs("analysis")
    with open("analysis/dvc.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "stages": {
                    "build": {"cmd": "echo hi > out.txt", "outs": ["out.txt"]}
                }
            },
            f,
        )
    subprocess.check_call(["calkit", "run", "--all-pipelines"])
    assert os.path.isfile("analysis/out.txt")
    # Once there's something for DVC to run, a run makes it a DVC repo
    ck_info = {
        "name": "site",
        "pipeline": {
            "stages": {
                "echo": {
                    "kind": "command",
                    "environment": "_system",
                    "command": "echo hi",
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "run"])
    assert os.path.isdir(".dvc")
    assert os.path.isfile("dvc.yaml")


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
    # With --existing, new files are left out
    with open("test.txt", "w") as f:
        f.write("sup sup sup")
    with open("test4.txt", "w") as f:
        f.write("sup")
    subprocess.check_call(["calkit", "save", "-aeM", "--no-push"])
    assert repo.head.commit.message.strip() == "Update test.txt"
    assert not repo.git.ls_files("test4.txt")
    assert "test4.txt" in repo.untracked_files
    # Explicit paths that aren't in the repo yet are left out too
    with open("test.txt", "w") as f:
        f.write("sup again")
    subprocess.check_call(
        [
            "calkit",
            "save",
            "-e",
            "test.txt",
            "test4.txt",
            "-m",
            "Existing only",
            "--no-push",
        ]
    )
    assert repo.head.commit.message.strip() == "Existing only"
    assert not repo.git.ls_files("test4.txt")
    # A dry run says what would be saved without staging or committing
    with open("test.txt", "w") as f:
        f.write("dry")
    head_before = repo.head.commit.hexsha
    for args in [["-a"], ["test.txt", "test4.txt"], ["--dry", "-ae"]]:
        out = subprocess.check_output(
            ["calkit", "save", "--dry-run", "-m", "Dry", *args], text=True
        )
        assert "test.txt" in out
        assert "Would commit and push" in out
        assert ("test4.txt" in out) == ("-ae" not in args)
        assert repo.head.commit.hexsha == head_before
        assert not calkit.git.get_staged_files()
    out = subprocess.check_output(
        ["calkit", "save", "--dry", "-a", "--no-push"], text=True
    )
    assert "Would commit\n" in out
    # A dry run outside a Git repo doesn't create one
    os.rename(".git", ".git-moved")
    try:
        out = subprocess.check_output(
            ["calkit", "save", "--dry", "-a"], text=True
        )
        assert "would offer to init" in out
        assert not os.path.exists(".git")
    finally:
        os.rename(".git-moved", ".git")


def test_save_ignores_nested_notebook_checkpoints(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    os.makedirs("notebooks/.ipynb_checkpoints")
    with open("notebooks/fade.ipynb", "w") as f:
        f.write("{}")
    for name in ["fade-checkpoint.ipynb", "other-checkpoint.ipynb"]:
        with open(
            os.path.join("notebooks/.ipynb_checkpoints", name), "w"
        ) as f:
            f.write("{}")
    subprocess.check_call(
        ["calkit", "save", "-am", "Add notebook", "--no-push"]
    )
    repo = git.Repo()
    assert repo.git.ls_files("notebooks/fade.ipynb")
    assert not repo.git.ls_files("notebooks/.ipynb_checkpoints")
    with open(".gitignore") as f:
        lines = f.read().splitlines()
    assert lines.count("notebooks/.ipynb_checkpoints/") == 1


def test_save_data_not_in_cache(tmp_dir):
    # We should skip DVC-tracked paths that are missing from both the
    # workspace and the cache, e.g., because they were never pulled
    subprocess.check_call(["calkit", "init"])
    with open("data.csv", "w") as f:
        f.write("a,b\n1,2\n")
    subprocess.check_call(
        [
            "calkit",
            "save",
            "data.csv",
            "-t",
            "dvc",
            "-m",
            "Add data",
            "--no-push",
        ]
    )
    with open("data.csv.dvc") as f:
        dvc_out_before = f.read()
    # Delete the data and its cache, simulating a machine onto which it was
    # never pulled
    os.remove("data.csv")
    cache_dir = os.path.join(".dvc", "cache")
    # DVC protects cached files by making them read-only, which stops them
    # from being deleted on Windows
    for dirpath, _, fnames in os.walk(cache_dir):
        for fname in fnames:
            os.chmod(
                os.path.join(dirpath, fname), stat.S_IWRITE | stat.S_IREAD
            )
    shutil.rmtree(cache_dir)
    with open("README.md", "a") as f:
        f.write("\nSome more info.\n")
    out = subprocess.check_output(
        ["calkit", "save", "-am", "Update README", "--no-push"], text=True
    )
    assert "data.csv" in out and "not in the cache" in out
    # The DVC pointer file should be untouched, since there's nothing to commit
    with open("data.csv.dvc") as f:
        assert f.read() == dvc_out_before
    repo = git.Repo()
    assert not repo.git.status("--porcelain")


def test_call_dvc():
    subprocess.check_call(["calkit", "dvc", "--help"])
    subprocess.check_call(["calkit", "dvc", "stage", "--help"])


def test_run_with_output_outside_code_page(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    ck_info = calkit.load_calkit_info()
    # Writes a quote to the run log as UTF-8, which cp1252, Windows' default,
    # can't decode
    script = (
        "import glob; [open(p, 'ab').write(b'\\xe2\\x80\\x9d\\n') "
        "for p in glob.glob('.calkit/local/logs/*.log')]"
    )
    with open("quote.py", "w") as f:
        f.write(script)
    ck_info["pipeline"] = {
        "stages": {
            "quote": {
                "kind": "shell-command",
                "environment": "_system",
                "command": f'"{Path(sys.executable).as_posix()}" quote.py',
                "outputs": [],
            }
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    res = subprocess.run(["calkit", "run"], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr


@pytest.mark.needs("juliaup")
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
    # A DVC repo that can't be opened is reported as such, not mistaken for
    # a missing one that 'dvc init' would then refuse to create
    with open("not-a-dir", "w") as f:
        f.write("")
    proc = subprocess.run(
        ["calkit", "run"],
        env=os.environ | {"DVC_SITE_CACHE_DIR": "not-a-dir/cache"},
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "Failed to open DVC repo" in proc.stdout + proc.stderr
    assert "Initializing DVC repo" not in proc.stdout
    os.remove("not-a-dir")
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
            "Example",
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


def test_run_dvc_repro_tolerates_teardown_failure(monkeypatch, capsys):
    import dvc.cli

    # Normal invocation returns DVC's exit code unchanged, after clearing the
    # hub's token from remotes off the hub, since --pull sends it
    clear = Mock(return_value=[])
    monkeypatch.setattr(calkit.dvc, "clear_off_hub_auth", clear)
    monkeypatch.setattr(dvc.cli, "main", Mock(return_value=7))
    assert _run_dvc_repro(["repro", "--pull", "my-stage"]) == 7
    clear.assert_called_once_with()
    # DVC lazily imports ``dvc.daemon`` and ``dvc.repo.open_repo`` for
    # analytics/cleanup only after the command has already run. On a broken
    # install those imports fail (issue #1018), crashing the run once the
    # pipeline has finished, so tolerate them and report ``None`` instead.
    for missing in ["dvc.daemon", "dvc.repo.open_repo"]:
        monkeypatch.setattr(
            dvc.cli,
            "main",
            Mock(
                side_effect=ModuleNotFoundError(
                    f"No module named {missing!r}", name=missing
                )
            ),
        )
        assert _run_dvc_repro(["repro"]) is None
        assert "teardown failed" in capsys.readouterr().out
    # A module DVC imports *before* running the command (dvc._debug, dvc.config,
    # dvc.logger) failing means the pipeline never ran at all. Swallowing that
    # would leave an empty log and report success, so it must propagate.
    monkeypatch.setattr(
        dvc.cli,
        "main",
        Mock(
            side_effect=ModuleNotFoundError(
                "No module named 'dvc._debug'", name="dvc._debug"
            )
        ),
    )
    with pytest.raises(ModuleNotFoundError, match="dvc._debug"):
        _run_dvc_repro(["repro"])
    # Non-import errors are unexpected too -- DVC turns real command failures
    # into an exit code -- so they must propagate rather than be masked.
    monkeypatch.setattr(
        dvc.cli, "main", Mock(side_effect=RuntimeError("boom"))
    )
    with pytest.raises(RuntimeError, match="boom"):
        _run_dvc_repro(["repro"])


def test_run_isolated_subproject_stage_exit_code(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    # An isolated subproject is its own Git/DVC repo, so its stage targets run
    # directly inside it rather than through the parent pipeline
    os.makedirs("isolated-sp", exist_ok=True)
    subprocess.check_call(["git", "init"], cwd="isolated-sp")
    subprocess.check_call(["calkit", "init"], cwd="isolated-sp")
    ck_info = calkit.load_calkit_info()
    ck_info["subprojects"] = [{"path": "isolated-sp"}]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    # A failing subproject stage must exit nonzero; the isolated-target path
    # returns before the parent pipeline runs, and used to skip raising
    with open("isolated-sp/dvc.yaml", "w") as f:
        yaml.dump(
            {
                "stages": {
                    "stage-b": {"cmd": 'python -c "import sys; sys.exit(1)"'}
                }
            },
            f,
        )
    result = subprocess.run(["calkit", "run", "isolated-sp:stage-b"])
    assert result.returncode != 0
    # A passing one still exits zero
    with open("isolated-sp/dvc.yaml", "w") as f:
        yaml.dump(
            {"stages": {"stage-b": {"cmd": "python -c \"print('ok')\""}}}, f
        )
    subprocess.check_call(["calkit", "run", "isolated-sp:stage-b"])


def test_status_in_subdir_uses_the_parent_dvc_repo(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    # A subproject that is a plain subdirectory shares the parent's repos
    os.makedirs("sub", exist_ok=True)
    with open(os.path.join("sub", "calkit.yaml"), "w") as f:
        calkit.ryaml.dump({"name": "sub"}, f)
    proc = subprocess.run(
        ["calkit", "status"], cwd="sub", capture_output=True, text=True
    )
    # Looking for ./.dvc rather than asking DVC used to nest a second repo
    assert "Initializing DVC repository" not in proc.stdout + proc.stderr
    assert not os.path.exists(os.path.join("sub", ".dvc"))
    assert not os.path.exists(os.path.join("sub", ".dvcignore"))
    assert os.path.isfile(os.path.join(".dvc", "config"))
    # With no DVC repo anywhere above it, one is still created for a
    # pipeline
    shutil.rmtree(".dvc")
    with open(os.path.join("sub", "calkit.yaml"), "w") as f:
        calkit.ryaml.dump(
            {
                "name": "sub",
                "pipeline": {
                    "stages": {
                        "echo": {
                            "kind": "command",
                            "environment": "_system",
                            "command": "echo hi",
                        }
                    }
                },
            },
            f,
        )
    proc = subprocess.run(
        ["calkit", "status"], cwd="sub", capture_output=True, text=True
    )
    assert "Initializing DVC repository" in proc.stdout + proc.stderr
    assert os.path.isfile(os.path.join("sub", ".dvc", "config"))


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
        calkit.ryaml.dump(dvc_yaml, f)
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
    # An inline subproject's pipeline doesn't run in full alongside
    os.makedirs("sub")
    with open("sub/calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "pipeline": {
                    "stages": {
                        "other": {
                            "kind": "shell-command",
                            "command": "echo other > other.txt",
                            "environment": "_system",
                            "outputs": [
                                {"path": "other.txt", "storage": "git"}
                            ],
                        }
                    }
                }
            },
            f,
        )
    with open("calkit.yaml") as f:
        ck_info = calkit.ryaml.load(f) or {}
    ck_info["subprojects"] = [{"path": "sub"}]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(
        ["calkit", "run", "--downstream", "stage-a", "--force"]
    )
    assert not os.path.exists("sub/other.txt")


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
    from calkit.dvc.core import _rwlock_holder_is_live

    with open("holder.py", "w") as f:
        f.write("import time\ntime.sleep(120)\n")
    argv = [sys.executable, "holder.py", *signature]
    proc = subprocess.Popen(argv)
    cmd = " ".join(argv)
    # Until it's recognized, e.g., on a busy runner where it's still
    # starting, a test would see one fewer holder than it spawned
    deadline = time.monotonic() + 10
    while not _rwlock_holder_is_live(proc.pid, cmd):
        if time.monotonic() > deadline:
            raise RuntimeError(f"Lock holder never started: {cmd}")
        time.sleep(0.05)
    return proc, cmd


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


def test_stage_run_info_ignores_stage_output():
    # Stage output shares the log with DVC's records and can be shaped exactly
    # like one, so it must not be parsed as one
    ts = "2025-01-01 00:00:0"
    content = "\n".join(
        [
            f"{ts}0,000 - INFO - Running stage 'a':",
            STAGE_OUTPUT_START,
            f"{ts}1,000 - ERROR - a warning from the stage's own logger",
            f"{ts}1,500 - INFO - Running stage 'not-a-stage':",
            # Output with no final newline shares a line with the end marker
            "no trailing newline here" + STAGE_OUTPUT_END,
            f"{ts}2,000 - INFO - Running stage 'b':",
            STAGE_OUTPUT_START,
            "plain output",
            STAGE_OUTPUT_END,
            f"{ts}3,000 - INFO - Stage 'c' didn't change, skipping",
        ]
    )
    info = _stage_run_info_from_log_content(content)
    assert list(info) == ["a", "b", "c"]
    assert info["a"]["status"] == "completed"
    assert info["b"]["status"] == "completed"
    assert info["c"]["status"] == "skipped"


def test_stage_run_info_last_stage():
    ts = "2025-01-01 00:00:0"
    content = "\n".join(
        [
            f"{ts}0,000 - INFO - Running stage 'a':",
            f"{ts}1,000 - INFO - Updating lock file 'dvc.lock'",
        ]
    )
    # While the run is in progress, the last stage stays open---that's how
    # status knows it's the one running
    assert "status" not in _stage_run_info_from_log_content(content)["a"]
    # Once the run is over, it's closed out with the final record's timestamp
    info = _stage_run_info_from_log_content(content, run_finished=True)["a"]
    assert info["status"] == "completed"
    assert info["end_time"] == datetime.fromisoformat(f"{ts}1,000").isoformat()


def test_stage_run_info_last_stage_failed():
    # A failed last stage must not be closed out as completed
    ts = "2025-01-01 00:00:0"
    content = "\n".join(
        [
            f"{ts}0,000 - INFO - Running stage 'a':",
            f"{ts}1,000 - ERROR - failed to reproduce 'a': boom",
            "dvc.exceptions.ReproductionError: failed to reproduce 'a'",
        ]
    )
    info = _stage_run_info_from_log_content(content, run_finished=True)
    assert info["a"]["status"] == "failed"


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


def test_get_iteration_item_counts():
    ck_info = {
        "parameters": {"seeds": [1, 2]},
        "pipeline": {
            "stages": {
                "plain": {"kind": "shell-command", "command": "echo"},
                "sweep": {
                    "kind": "shell-command",
                    "command": "echo {month} {seed}",
                    "iterate_over": [
                        {"arg_name": "month", "values": ["a", "b", "c"]},
                        {"arg_name": "seed", "values": [1, 2]},
                    ],
                },
            }
        },
    }
    assert _get_iteration_item_counts(ck_info) == {"sweep": 6}


def test_print_running_pipeline_status_groups_items(capsys):
    start = calkit.utcnow(remove_tz=True).isoformat()
    done = {"status": "completed", "start_time": start, "end_time": start}
    stages = {f"fetch@{m:02d}": done for m in range(1, 13)}
    stages["prep"] = done
    stages |= {"model@a": done, "model@b": {"start_time": start}}
    _print_running_pipeline_status(
        {
            "processes": [{"pid": 1}],
            "stages": stages,
            "running_stages": ["model@b"],
            "item_counts": {"fetch": 14, "model": 3},
        }
    )
    out = click.unstyle(capsys.readouterr().out)
    assert "completed: fetch (12/14), prep\n" in out
    assert "running:   model (1/3, " in out
    assert "fetch@" not in out and "model@" not in out
    # Concurrent items of a sweep, before the run log knows of them
    _print_running_pipeline_status(
        {
            "processes": [{"pid": 1}, {"pid": 2}],
            "stages": {},
            "running_stages": ["sweep@1", "sweep@3"],
            "item_counts": {"sweep": 4},
        }
    )
    out = click.unstyle(capsys.readouterr().out)
    assert "running:   sweep (0/4, 2 running)\n" in out


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
        calkit.ryaml.dump(dvc_yaml, f)
    # Without --log, the log is retained privately under .calkit/local/logs
    # (gitignored) and not saved to the tracked .calkit/logs directory
    subprocess.check_call(["calkit", "run"])
    local_logs = os.path.join(".calkit", "local", "logs")
    private = [f for f in os.listdir(local_logs) if f.endswith(".log")]
    assert len(private) == 1
    assert os.path.isfile(os.path.join(".calkit", "local", ".gitignore"))
    tracked_dir = os.path.join(".calkit", "logs")
    assert not os.path.isdir(tracked_dir) or not [
        f for f in os.listdir(tracked_dir) if f.endswith(".log")
    ]
    # Run info is saved privately without --log too, with the system inline
    local_runs = os.path.join(".calkit", "local", "runs")
    with open(os.path.join(local_runs, os.listdir(local_runs)[0])) as f:
        assert json.load(f)["system"]["os"] == platform.system()
    assert not os.path.exists(os.path.join(".calkit", "local", "systems"))
    # How each stage's outputs were made is kept with the project, staged
    with open(STAGE_RUNS_FPATH) as f:
        stage_runs = json.load(f)
    entry = stage_runs["s1"]
    assert list(stage_runs) == ["s1"]
    assert "environment" not in entry
    assert entry["calkit_version"] == calkit.__version__
    assert entry["dvc_lock_hash"] == calkit.dvc.stage_lock_hash(
        calkit.dvc.read_lock_stages()["s1"]
    )
    assert entry["system"]["os"] == platform.system()
    assert entry["system"]["machine_id"] == calkit.get_machine_id()
    assert entry["start_time"] <= entry["end_time"]
    staged = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only"], text=True
    )
    assert ".calkit/stage-runs.json" in staged.splitlines()
    # A stage that's skipped as up to date keeps its entry, as does --dry
    subprocess.check_call(["calkit", "run"])
    subprocess.check_call(["calkit", "run", "--dry", "--force"])
    with open(STAGE_RUNS_FPATH) as f:
        assert json.load(f) == stage_runs
    # With --log, the log is also saved to the tracked directory plus run info
    subprocess.check_call(["calkit", "run", "--log", "--force"])
    tracked = [f for f in os.listdir(tracked_dir) if f.endswith(".log")]
    assert len(tracked) == 1
    assert os.path.isdir(os.path.join(".calkit", "runs"))
    assert not os.path.exists(os.path.join(".calkit", "systems"))
    with open(STAGE_RUNS_FPATH) as f:
        assert json.load(f)["s1"]["start_time"] > entry["start_time"]


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


def test_prune_run_logs_json_suffix(tmp_dir):
    runs_dir = "runs"
    os.makedirs(runs_dir)
    for i in range(15):
        name = f"2025-01-01T00-00-{i:02d}-{i:02d}.json"
        with open(os.path.join(runs_dir, name), "w") as f:
            f.write("{}")
    _prune_run_logs(runs_dir, keep=10, suffix=".json")
    remaining = sorted(os.listdir(runs_dir))
    assert len(remaining) == 10
    # Oldest by name are removed; newest 10 kept
    assert remaining[0] == "2025-01-01T00-00-05-05.json"
    assert remaining[-1] == "2025-01-01T00-00-14-14.json"
    # A .log file in the same dir must be untouched by a .json prune
    with open(os.path.join(runs_dir, "keep.log"), "w") as f:
        f.write("x")
    _prune_run_logs(runs_dir, keep=10, suffix=".json")
    assert os.path.isfile(os.path.join(runs_dir, "keep.log"))


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
    names = complete_stage_names("")
    # Parent stage
    assert "parent-stage" in names
    # Subproject shorthand
    assert "inline-sp" in names
    assert "isolated-sp" in names
    # Subproject stage targets
    assert "inline-sp:stage-a" in names
    assert "isolated-sp:stage-b" in names
    # Prefix filtering
    filtered = complete_stage_names("inline")
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


def test_only_invoked() -> None:
    import typer.main
    from typer.core import TyperGroup

    from calkit.cli import _only_invoked
    from calkit.cli.main import app

    def built(args: list[str]) -> dict:
        group = typer.main.get_command(_only_invoked(app, args))
        assert isinstance(group, TyperGroup)
        return {
            name: sorted(getattr(cmd, "commands", {}))
            for name, cmd in group.commands.items()
        }

    # A command, by name or alias, after the top level's options
    assert built(["status"]) == {"status|st": []}
    assert built(["-C", "sub", "--use-version=1", "st", "-c", "dvc"]) == {
        "status|st": []
    }
    # A command in a group, by the group's alias
    assert built(["create", "project", "--help"]) == {
        "new|create": ["project"]
    }
    # Help, or a command that doesn't exist, keeps everything
    everything = built(["--help"])
    assert len(everything) > 20
    assert len(everything["new|create"]) > 1
    assert built(["new", "--help"]) == {"new|create": everything["new|create"]}
    assert built(["new", "projetc"]) == built(["new", "--help"])
    assert built(["statsu"]) == everything
    assert built([]) == everything


def test_run_offers_git_install(monkeypatch: pytest.MonkeyPatch) -> None:
    from calkit.cli import run as cli_run

    error = ImportError("Failed to initialize: Bad git executable.")

    def fail() -> None:
        raise error

    monkeypatch.setattr("calkit.cli._only_invoked", lambda app, args: fail)
    monkeypatch.setattr(sys, "argv", ["calkit", "config", "github-ssh"])
    # Where it can be installed, it's offered, then the command runs again,
    # unless Git still doesn't run, which would only offer it again
    for installed, runs in [(True, True), (True, False), (False, False)]:
        with (
            patch("calkit.install.can_run_git", side_effect=[False, runs]),
            patch("calkit.install.get_unsupported_message", return_value=None),
            patch(
                "calkit.install.prompt_and_install", return_value=installed
            ) as m_prompt,
            patch("subprocess.call", return_value=0) as m_call,
            pytest.raises(SystemExit) as exc,
        ):
            cli_run()
        assert m_prompt.call_args.args[0] == "git"
        assert exc.value.code == (0 if runs else 1)
        assert m_call.called is runs
        if runs:
            assert m_call.call_args.args[0] == [
                *calkit.get_calkit_cmd(),
                "config",
                "github-ssh",
            ]
    # Where it can't, it says what to run
    monkeypatch.setattr("calkit.install.can_run_git", lambda: False)
    with (
        patch("calkit.install.get_unsupported_message", return_value="apt"),
        patch("calkit.install.prompt_and_install") as m_prompt,
        pytest.raises(SystemExit),
    ):
        cli_run()
    m_prompt.assert_not_called()
    # Where Git runs, installing it won't help, so the error is raised
    monkeypatch.setattr("calkit.install.can_run_git", lambda: True)
    with (
        patch("calkit.install.prompt_and_install") as m_prompt,
        pytest.raises(ImportError),
    ):
        cli_run()
    m_prompt.assert_not_called()
    # Other import errors aren't caught
    error = ImportError("No module named 'x'")
    with pytest.raises(ImportError):
        cli_run()


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


def _read_only_log(logs_dir: str) -> str:
    log_files = [f for f in os.listdir(logs_dir) if f.endswith(".log")]
    assert len(log_files) == 1
    with open(os.path.join(logs_dir, log_files[0])) as f:
        return f.read()


def _read_only_run_info() -> dict:
    runs_dir = os.path.join(".calkit", "local", "runs")
    fnames = os.listdir(runs_dir)
    assert len(fnames) == 1
    with open(os.path.join(runs_dir, fnames[0])) as f:
        return json.load(f)


def test_run_captures_stage_logs(tmp_dir):
    """Test stage stdout and stderr are teed to the terminal and run log."""
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["calkit", "init"])
    # A stage that writes to both streams, the second line shaped like a log
    # record so it would be misread as one if it weren't bracketed, and no
    # final newline so the end marker shares its line
    script = (
        "import sys\n"
        "sys.stdout.write('OUT_MARKER\\n')\n"
        "sys.stderr.write('2026-05-23 10:00:00,000 - ERROR - ERR_MARKER')\n"
    )
    with open("stage_script.py", "w") as f:
        f.write(script)
    dvc_yaml = {"stages": {"test_stage": {"cmd": "python stage_script.py"}}}
    with open("dvc.yaml", "w") as f:
        calkit.ryaml.dump(dvc_yaml, f)
    res = subprocess.run(["calkit", "run"], capture_output=True, text=True)
    assert res.returncode == 0
    # Both markers reach the terminal, since stage stderr is teed into stdout
    assert "OUT_MARKER" in res.stdout
    assert "ERR_MARKER" in res.stdout
    # Stage output and DVC's own records share one log
    log_content = _read_only_log(os.path.join(".calkit", "local", "logs"))
    assert "OUT_MARKER" in log_content
    assert "ERR_MARKER" in log_content
    assert "Running stage 'test_stage'" in log_content
    # The stage's ERROR line isn't taken for a DVC one, which would leave the
    # stage unfinished
    stage_info = _read_only_run_info()["stages"]["test_stage"]
    assert stage_info["status"] == "completed"
    assert stage_info["end_time"] >= stage_info["start_time"]
    assert "fallback font" not in res.stdout
    # A font Matplotlib couldn't find is reported once the run is done,
    # whether or not the stage failed
    for exit_code in [0, 1]:
        with open("stage_script.py", "w") as f:
            f.write(
                "import logging, sys\n"
                "log = logging.getLogger('matplotlib.font_manager')\n"
                "for _ in range(3):\n"
                "    log.warning(\"findfont: Font family 'Arial' not "
                'found.")\n'
                f"sys.exit({exit_code})\n"
            )
        res = subprocess.run(["calkit", "run"], capture_output=True, text=True)
        assert res.returncode == exit_code
        warning = res.stdout.split("Matplotlib in stage 'test_stage'")[-1]
        assert warning.startswith(" used a fallback font")
        assert warning.count("Font family 'Arial' not found") == 1
        assert "not found; see https://docs.calkit.org/" in warning


def test_run_captures_stage_logs_failure(tmp_dir):
    """Test that stage output is captured even if the stage fails."""
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["calkit", "init"])
    script = (
        "import sys\nsys.stdout.write('FAIL_OUT_MARKER\\n')\nsys.exit(1)\n"
    )
    with open("stage_fail.py", "w") as f:
        f.write(script)
    dvc_yaml = {"stages": {"fail_stage": {"cmd": "python stage_fail.py"}}}
    with open("dvc.yaml", "w") as f:
        calkit.ryaml.dump(dvc_yaml, f)
    res = subprocess.run(["calkit", "run"], capture_output=True, text=True)
    assert res.returncode != 0
    log_content = _read_only_log(os.path.join(".calkit", "local", "logs"))
    assert "FAIL_OUT_MARKER" in log_content
    # An ordinary failure isn't blamed on Windows App Control
    assert "Smart App Control" not in res.stderr
    # One that Windows App Control caused is explained
    with open("stage_fail.py", "w") as f:
        f.write(
            "import sys\n"
            "print('ImportError: DLL load failed while importing _sqlite3: "
            "An Application Control policy has blocked this file.')\n"
            "sys.exit(1)\n"
        )
    res = subprocess.run(["calkit", "run"], capture_output=True, text=True)
    assert res.returncode != 0
    assert "Windows blocked a file from running" in res.stderr
    assert calkit.windows.SMART_APP_CONTROL_DOCS_URL in res.stderr


def test_run_log_flag_copies_stage_logs(tmp_dir):
    """Test that --log copies the log with stage output to the tracked dir."""
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["calkit", "init"])
    script = "import sys\nsys.stdout.write('OUT_MARKER\\n')\n"
    with open("stage_script.py", "w") as f:
        f.write(script)
    dvc_yaml = {
        "stages": {"test_stage_log": {"cmd": "python stage_script.py"}}
    }
    with open("dvc.yaml", "w") as f:
        calkit.ryaml.dump(dvc_yaml, f)
    res = subprocess.run(
        ["calkit", "run", "--log"], capture_output=True, text=True
    )
    assert res.returncode == 0
    log_content = _read_only_log(os.path.join(".calkit", "logs"))
    assert "OUT_MARKER" in log_content


@skipif_windows_mock_scheduler
def test_run_scheduler_stage_respects_max_concurrent_jobs(tmp_dir):
    # An iterate_over stage on a scheduler env normally submits every job at
    # once. With max_concurrent_jobs set, submissions are paced so the project
    # never occupies more than that many queue slots---the point being not to
    # monopolize a shared cluster.
    env = {**os.environ, "CALKIT_MOCK_SCHEDULER": "1"}
    subprocess.check_call(["calkit", "init"])
    with open("run.sh", "w") as f:
        # Each job announces itself, holds long enough to overlap with any
        # concurrently running sibling, records how many were running at that
        # moment, then leaves.
        f.write('touch "running-$1"\n')
        f.write("sleep 1\n")
        f.write("ls running-* | wc -l >> counts.txt\n")
        f.write('rm "running-$1"\n')
        f.write('echo "$1" > "out-$1.txt"\n')
    ck_info = {
        "environments": {"slurm": {"kind": "slurm", "max_concurrent_jobs": 2}},
        "pipeline": {
            "stages": {
                "sweep": {
                    "kind": "shell-script",
                    "script_path": "run.sh",
                    "environment": "slurm",
                    "args": ["{x}"],
                    "iterate_over": [
                        {"arg_name": "x", "values": [1, 2, 3, 4, 5, 6]}
                    ],
                    "outputs": ["out-{x}.txt"],
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "run"], env=env)
    # Every case still runs to completion---the limit paces the pipeline, it
    # does not drop work.
    for x in range(1, 7):
        assert os.path.exists(f"out-{x}.txt")
    with open("counts.txt") as f:
        observed = [int(line) for line in f.read().split() if line]
    assert len(observed) == 6
    # Without the limit all six would be in flight together; with it, never
    # more than two.
    assert max(observed) <= 2


def test_dotenv_is_loaded_for_every_command(tmp_dir):
    # Which hub a command targets must not depend on whether that command
    # happens to read a secret: 'calkit run' loaded .env and 'calkit push'
    # didn't, so a CALKIT_HUB in .env sent the two to different hubs
    with open(".env", "w") as f:
        f.write("CALKIT_HUB=hub.example.edu\nSOME_PROJECT_SECRET=abc123\n")
    # patch.dict restores the whole environment, which monkeypatch can't
    # do for variables load_dotenv puts there itself
    with patch.dict(os.environ):
        os.environ.pop("CALKIT_HUB", None)
        os.environ.pop("SOME_PROJECT_SECRET", None)
        calkit_main(
            Mock(invoked_subcommand=None), version=False, use_version=None
        )
        assert os.environ["CALKIT_HUB"] == "hub.example.edu"
        assert os.environ["SOME_PROJECT_SECRET"] == "abc123"
        assert calkit.config.get_hub() == "https://hub.example.edu"


def test_calkit_env_no_longer_selects_a_hub(tmp_dir, capsys):
    # It used to, so a leftover one shouldn't silently stop doing anything
    with patch.dict(os.environ):
        os.environ.pop("CALKIT_HUB", None)
        os.environ["CALKIT_ENV"] = "staging"
        _warn_on_stale_calkit_env()
        assert (
            "CALKIT_ENV=staging no longer selects a hub"
            in capsys.readouterr().err
        )
        # The test environment is the one name that still means something
        os.environ["CALKIT_ENV"] = "test"
        _warn_on_stale_calkit_env()
        assert capsys.readouterr().err == ""


def test_stage_stdout_from_log_content():
    # Stage output is read back out of the run log, not captured twice.
    from calkit.cli.main.core import (
        STAGE_OUTPUT_END,
        STAGE_OUTPUT_START,
        _stage_stdout_from_log_content,
    )

    log = "\n".join(
        [
            "2025-01-01T00:00:00 - INFO - Running stage 'README.md/a':",
            STAGE_OUTPUT_START,
            "hello",
            "world" + STAGE_OUTPUT_END,
            "2025-01-01T00:00:01 - INFO - Running stage 'README.md/b':",
            STAGE_OUTPUT_START,
            STAGE_OUTPUT_END,
            "2025-01-01T00:00:02 - INFO - Stage 'other' didn't change, "
            "skipping",
        ]
    )
    res = _stage_stdout_from_log_content(log)
    # Output lacking a final newline shares its line with the end marker
    assert res["README.md/a"] == "hello\nworld"
    # A stage that ran but printed nothing is still recorded, so its block
    # can be emptied rather than left stale
    assert res["README.md/b"] == ""
    # A skipped stage produced no output this run, so it must not be
    # listed---its block should keep what it has
    assert "other" not in res


def test_get_matplotlib_font_warnings_by_stage() -> None:
    log = "\n".join(
        [
            "2025-01-01T00:00:00 - INFO - Running stage 'plot':",
            STAGE_OUTPUT_START,
            # Logged once per text drawn, and reported once
            "findfont: Font family 'Arial' not found.",
            "findfont: Font family 'Arial' not found.",
            "findfont: Generic family 'sans-serif' not found because none "
            "of the following families were found: Arial, Helvetica",
            # A script's own logging format, and Matplotlib's other
            # message, reported once per family whichever form says it
            "WARNING:matplotlib.font_manager:findfont: Font family "
            "['Arial'] not found. Falling back to DejaVu Sans.",
            "findfont: Font family ['Times New Roman'] not found. Falling "
            "back to DejaVu Sans.",
            "findfont: Font family 'Times New Roman' not found.",
            # Papermill's progress bar can share the line
            "Executing:   0%|   | 0/1 [00:00<?, ?cell/s]findfont: Font "
            "family 'CMU Serif' not found.",
            "findfont: score(FontEntry(name='DejaVu Sans')) = 0.05",
            STAGE_OUTPUT_END,
            "2025-01-01T00:00:01 - INFO - Running stage 'clean':",
            STAGE_OUTPUT_START,
            "Font family 'Arial' not found, but not from Matplotlib",
            STAGE_OUTPUT_END,
            # Matplotlib's messages from DVC itself aren't a stage's
            "2025-01-01T00:00:02 - WARNING - findfont: Font family 'X' "
            "not found.",
        ]
    )
    assert _get_matplotlib_font_warnings_by_stage(log) == {
        "plot": [
            "Font family 'Arial' not found",
            "Generic family 'sans-serif' not found because none of the "
            "following families were found: Arial, Helvetica",
            "Font family ['Times New Roman'] not found. Falling back to "
            "DejaVu Sans",
            "Font family 'CMU Serif' not found",
        ]
    }
    assert _get_matplotlib_font_warnings_by_stage("") == {}


def test_run_refuses_outside_a_project(tmp_dir):
    # `calkit run` must not initialize anything outside a project.
    #
    # It initializes Git and DVC as needed, so a wrong working directory
    # would otherwise scatter a .dvc directory into an unrelated folder ---
    # and inside an existing Git repo that now succeeds, since DVC is told
    # the project is a subdirectory.
    result = subprocess.run(["calkit", "run"], capture_output=True, text=True)
    assert result.returncode != 0
    assert "no calkit.yaml or dvc.yaml" in result.stderr.lower()
    assert not os.path.exists(".dvc")
    # Same inside an existing Git repo, which is the case that would now
    # otherwise succeed rather than failing on DVC's own check
    subprocess.check_call(["git", "init", "-q", "."])
    os.makedirs("sub")
    result = subprocess.run(
        ["calkit", "run"], cwd="sub", capture_output=True, text=True
    )
    assert result.returncode != 0
    assert not os.path.exists(os.path.join("sub", ".dvc"))
    # A project with only a dvc.yaml is still a project
    with open(os.path.join("sub", "dvc.yaml"), "w") as f:
        f.write("stages: {}\n")
    result = subprocess.run(
        ["calkit", "run"], cwd="sub", capture_output=True, text=True
    )
    assert "no calkit.yaml or dvc.yaml" not in result.stderr.lower()


def test_project_dir_option(tmp_dir):
    # `-C` changes directory before anything reads the filesystem.
    os.makedirs("proj")
    with open(os.path.join("proj", "calkit.yaml"), "w") as f:
        f.write("name: from-subdir\n")
    subprocess.check_call(["git", "init", "-q", "."])
    # The project is initialized inside proj, not wherever we were standing
    result = subprocess.run(
        ["calkit", "-C", "proj", "init"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert os.path.isdir(os.path.join("proj", ".dvc"))
    assert not os.path.isdir(".dvc")
    # The long spelling matches make/tar/git/uv, which all mean chdir
    result = subprocess.run(
        ["calkit", "--directory", "proj", "status"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    # A missing directory is reported rather than silently ignored
    result = subprocess.run(
        ["calkit", "-C", "nope", "status"], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "does not exist" in result.stderr


def test_commit(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    os.makedirs("test")
    Path("test/yo.txt").touch()
    Path("test/sup.txt").touch()
    Path("hey.txt").touch()
    subprocess.check_call(["calkit", "add", "hey.txt"])
    subprocess.check_call(["calkit", "add", "test/sup.txt"])
    subprocess.check_call(["calkit", "commit", "hey.txt", "-M"])
    assert calkit.git.get_staged_files() == ["test/sup.txt"]
    # Test committing to DVC, where the path itself is kept out of Git, so
    # only its pointer and ignore rule can be committed for it
    Path("data.csv").write_text("data\n")
    subprocess.check_call(
        ["calkit", "save", "data.csv", "-t", "dvc", "-M", "--no-push"]
    )
    repo = calkit.git.get_repo()
    assert repo.head.commit.message.strip() == "Add data.csv"
    committed = repo.git.show("--name-only", "--format=", "HEAD").split("\n")
    assert "data.csv.dvc" in committed
    assert ".gitignore" in committed
    assert "data.csv" not in committed
    # Paths that weren't asked for are left alone
    assert calkit.git.get_staged_files() == ["test/sup.txt"]
    assert calkit.git.get_untracked_files() == ["test/yo.txt"]
    # Changing a DVC-tracked path is an update, not an add
    Path("data.csv").write_text("more data\n")
    subprocess.check_call(["calkit", "save", "data.csv", "-M", "--no-push"])
    assert (
        calkit.git.get_repo().head.commit.message.strip() == "Update data.csv"
    )
    # Paths are interpreted relative to the working directory
    Path("test/deep.txt").write_text("deep\n")
    subprocess.check_call(
        ["calkit", "save", "deep.txt", "-M", "--no-push"], cwd="test"
    )
    assert (
        calkit.git.get_repo().head.commit.message.strip()
        == "Add test/deep.txt"
    )
    # A path with nothing staged for it is called out, and nothing else gets
    # committed in its place
    Path("hey.txt").write_text("changed\n")
    result = subprocess.run(
        ["calkit", "commit", "hey.txt", "-m", "Update hey.txt"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "No changes staged" in result.stdout
    assert calkit.git.get_staged_files() == ["test/sup.txt"]
    # Committing without paths commits what was staged, not what's in the
    # working tree
    Path("partial.txt").write_text("staged\n")
    subprocess.check_call(["calkit", "add", "partial.txt"])
    Path("partial.txt").write_text("unstaged\n")
    subprocess.check_call(["calkit", "commit", "-m", "Add partial.txt"])
    repo = calkit.git.get_repo()
    assert repo.git.show("HEAD:partial.txt") == "staged"
    # Saving a tracked path after deleting it, by the path that's now gone
    Path("gone.txt").write_text("gone\n")
    subprocess.check_call(
        ["calkit", "save", "gone.txt", "-m", "Add gone.txt", "--no-push"]
    )
    os.remove("gone.txt")
    subprocess.check_call(
        ["calkit", "save", "gone.txt", "-m", "Remove gone.txt", "--no-push"]
    )
    repo = calkit.git.get_repo()
    assert repo.head.commit.message.strip() == "Remove gone.txt"
    assert "D\tgone.txt" in repo.git.show(
        "--name-status", "--format=", "HEAD"
    ).split("\n")
    assert calkit.git.get_staged_files() == []
    # Resolving a merge is still possible, though Git refuses to commit only
    # some paths while one is in progress
    subprocess.check_call(["git", "checkout", "--", "."])
    default_branch = repo.active_branch.name
    repo.git.checkout("-b", "other", "HEAD~1")
    Path("conflict.txt").write_text("other\n")
    subprocess.check_call(
        ["calkit", "save", "conflict.txt", "-m", "Add conflict", "--no-push"]
    )
    repo.git.checkout(default_branch)
    Path("conflict.txt").write_text("main\n")
    subprocess.check_call(
        ["calkit", "save", "conflict.txt", "-m", "Add conflict", "--no-push"]
    )
    subprocess.run(["git", "merge", "other"], capture_output=True)
    Path("conflict.txt").write_text("resolved\n")
    subprocess.check_call(
        [
            "calkit",
            "save",
            "conflict.txt",
            "-m",
            "Resolve conflict",
            "--no-push",
        ]
    )
    repo = calkit.git.get_repo()
    assert repo.head.commit.message.strip() == "Resolve conflict"
    assert not repo.is_dirty()


def test_push_only_reports_to_a_connected_hub(monkeypatch, tmp_dir):
    import calkit.cli.main.core as cli_core

    posted: list[str] = []
    monkeypatch.setattr(
        calkit.hub, "post", lambda path, **kw: posted.append(path)
    )
    monkeypatch.setattr(calkit, "detect_project_name", lambda: "o/p")
    monkeypatch.setattr(calkit.dvc, "get_remotes", lambda: {})

    # A project that names no hub and stores nothing on one is not connected,
    # and Calkit works perfectly well that way: say nothing to anyone
    monkeypatch.setattr(calkit, "load_calkit_info", lambda: {})
    cli_core._tell_hub_we_pushed(["git"], [])
    assert posted == []

    # Declaring a hub in calkit.yaml connects it
    monkeypatch.setattr(
        calkit, "load_calkit_info", lambda: {"hub": "https://calkit.io"}
    )
    cli_core._tell_hub_we_pushed(["git"], [])
    assert posted == ["/projects/o/p/events/push"]

    # So does keeping data on a Calkit DVC remote, with no hub key at all
    posted.clear()
    monkeypatch.setattr(calkit, "load_calkit_info", lambda: {})
    monkeypatch.setattr(
        calkit.dvc, "get_remotes", lambda: {"calkit": "ck://o/p"}
    )
    monkeypatch.setattr(
        calkit.dvc, "detect_calkit_remote_type", lambda name, url: "ck"
    )
    cli_core._tell_hub_we_pushed(["git"], [])
    assert posted == ["/projects/o/p/events/push"]

    # A remote that isn't Calkit's doesn't connect anything
    posted.clear()
    monkeypatch.setattr(
        calkit.dvc, "get_remotes", lambda: {"s3": "s3://somewhere"}
    )
    monkeypatch.setattr(
        calkit.dvc, "detect_calkit_remote_type", lambda name, url: None
    )
    cli_core._tell_hub_we_pushed(["git"], [])
    assert posted == []


def test_push_reports_what_was_pushed(monkeypatch, tmp_dir):
    import calkit.cli.main.core as cli_core

    sent: list[dict] = []
    monkeypatch.setattr(
        calkit.hub, "post", lambda path, **kw: sent.append(kw["json"])
    )
    monkeypatch.setattr(calkit, "detect_project_name", lambda: "o/p")
    monkeypatch.setattr(
        calkit, "load_calkit_info", lambda: {"hub": "https://calkit.io"}
    )
    monkeypatch.setattr(calkit.dvc, "get_remotes", lambda: {})
    # A push that only sent data still gets reported: it changes what the
    # project resolves to without moving a commit, and the hub has no other
    # way to know that
    cli_core._tell_hub_we_pushed(["dvc"], [])
    assert sent[-1]["targets"] == ["dvc"]
    cli_core._tell_hub_we_pushed(["dvc", "docker", "git"], [])
    assert sent[-1]["targets"] == ["dvc", "docker", "git"]


def test_save_offers_hub_before_committing(
    tmp_dir, tmp_path_factory, monkeypatch
):
    from typer.testing import CliRunner

    import calkit.cli.main.core as core
    import calkit.cli.update
    import calkit.core

    # The first push must work without push.autoSetupRemote, which CI sets
    # globally, and which no other config can turn back off
    git_config = tmp_path_factory.mktemp("git") / "config"
    git_config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(git_config))
    for role in ["AUTHOR", "COMMITTER"]:
        monkeypatch.setenv(f"GIT_{role}_NAME", "Calkit Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@calkit.org")
    subprocess.check_call(["calkit", "init"])
    monkeypatch.setattr(calkit.core, "is_tty", lambda: True)
    bare = str(tmp_path_factory.mktemp("remote") / "repo.git")
    subprocess.check_call(["git", "init", "-q", "--bare", bare])
    events: list[str] = []

    def connect():
        events.append("connect")
        subprocess.check_call(["git", "remote", "add", "origin", bare])
        # As update_hub does, the connection is committed on its own
        with open("connection.txt", "a") as f:
            f.write("x\n")
        subprocess.check_call(["git", "add", "connection.txt"])
        subprocess.check_call(["git", "commit", "-q", "-m", "Connect"])

    real_add = core.add

    def add(*args, **kwargs):
        events.append("add")
        return real_add(*args, **kwargs)

    monkeypatch.setattr(calkit.cli.update, "update_hub", connect)
    monkeypatch.setattr(core, "add", add)
    runner = CliRunner()
    # Asked before anything runs, since the Git and DVC commands save
    # starts read the same terminal and would swallow an answer typed ahead
    with open("a.txt", "w") as f:
        f.write("a")
    result = runner.invoke(calkit_app, ["save", "-am", "Add a"], input="y\n")
    assert result.exit_code == 0, result.output
    assert events == ["connect", "add"]
    repo = git.Repo()
    assert repo.head.commit.message.strip() == "Add a"
    assert git.Repo(bare).head.commit.hexsha == repo.head.commit.hexsha
    # Declining still commits, and skips the push
    subprocess.check_call(["git", "remote", "remove", "origin"])
    events.clear()
    with open("b.txt", "w") as f:
        f.write("b")
    result = runner.invoke(calkit_app, ["save", "-am", "Add b"], input="n\n")
    assert result.exit_code == 0, result.output
    assert events == ["add"]
    assert repo.head.commit.message.strip() == "Add b"
    assert git.Repo(bare).head.commit.message.strip() == "Add a"
    # Connecting can leave nothing else to commit, and is pushed anyway
    result = runner.invoke(calkit_app, ["save", "-am", "None"], input="y\n")
    assert result.exit_code == 0, result.output
    assert repo.head.commit.message.strip() == "Connect"
    assert git.Repo(bare).head.commit.hexsha == repo.head.commit.hexsha


def test_save_offers_dvc_storage_for_data_with_nowhere_to_go(
    tmp_dir, tmp_path_factory, monkeypatch
):
    from typer.testing import CliRunner

    import calkit.cli.update
    import calkit.core

    git_config = tmp_path_factory.mktemp("git") / "config"
    git_config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(git_config))
    for role in ["AUTHOR", "COMMITTER"]:
        monkeypatch.setenv(f"GIT_{role}_NAME", "Calkit Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@calkit.org")
    subprocess.check_call(["calkit", "init"])
    monkeypatch.setattr(calkit.core, "is_tty", lambda: True)
    bare = str(tmp_path_factory.mktemp("remote") / "repo.git")
    subprocess.check_call(["git", "init", "-q", "--bare", bare])
    subprocess.check_call(["git", "remote", "add", "origin", bare])
    storage = str(tmp_path_factory.mktemp("storage"))
    events: list[str] = []
    declined_path = ".calkit/local/declined-dvc-storage"
    runner = CliRunner()

    def connect():
        events.append("connect")
        subprocess.check_call(["dvc", "remote", "add", "-d", "store", storage])

    def fail():
        events.append("fail")
        calkit.cli.raise_error("Hub unreachable")

    def save(name: str, input: str = "", to: str = "dvc") -> str:
        with open(name, "w") as f:
            f.write(name)
        result = runner.invoke(
            calkit_app,
            ["save", name, "--to", to, "-m", f"Add {name}"],
            input=input,
        )
        assert result.exit_code == 0, result.output
        assert git.Repo(bare).head.commit.message.strip() == f"Add {name}"
        return result.output

    monkeypatch.setattr(calkit.cli.update, "update_hub", connect)
    # Code alone doesn't ask: its Git remote is somewhere to push it
    assert "no DVC remote" not in save("a.txt", to="git")
    # Data does, and declining still pushes the code, and is remembered
    output = save("data1.bin", input="n\n")
    assert "no DVC remote" in output
    assert "not asking again" in output
    assert not os.listdir(storage)
    assert "no DVC remote" not in save("data2.bin")
    os.remove(declined_path)
    # A code-only commit doesn't ask, though data is here, but a push of
    # everything does
    assert "no DVC remote" not in save("b.txt", to="git")
    result = runner.invoke(calkit_app, ["push"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Skipping DVC push" in result.output
    os.remove(declined_path)
    # Without pushing there's nothing to ask about
    with open("c.txt", "w") as f:
        f.write("c")
    result = runner.invoke(calkit_app, ["save", "-am", "Add c", "--no-push"])
    assert result.exit_code == 0, result.output
    assert "no DVC remote" not in result.output
    # Failing to connect still pushes the code
    monkeypatch.setattr(calkit.cli.update, "update_hub", fail)
    assert "connecting failed" in save("data3.bin", input="y\n")
    assert events == ["fail"]
    assert not os.path.exists(declined_path)
    # Accepting connects, then pushes the data that was already here too
    monkeypatch.setattr(calkit.cli.update, "update_hub", connect)
    save("data4.bin", input="y\n")
    assert events == ["fail", "connect"]
    assert "in sync" in subprocess.check_output(
        ["dvc", "status", "--cloud"], text=True
    )
    # Once there's a remote, nothing asks again
    assert "no DVC remote" not in save("data5.bin")
    assert events == ["fail", "connect"]
    # Without a terminal to ask in, it says how to connect instead
    subprocess.check_call(["dvc", "remote", "remove", "store"])
    monkeypatch.setattr(calkit.core, "is_tty", lambda: False)
    result = runner.invoke(calkit_app, ["push"])
    assert result.exit_code == 0, result.output
    assert "calkit update hub" in result.output
    assert events == ["fail", "connect"]


def test_outputs_stay_out_of_git_after_failed_run(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = {
        "stages": {
            "ev": {
                "kind": "shell-command",
                "environment": "_system",
                "command": "mkdir -p results/s{s} && echo {n} > "
                "results/s{s}/seed-{n}.txt",
                "iterate_over": [
                    {"arg_name": "s", "values": [1, 3]},
                    {"arg_name": "n", "values": [1, 2]},
                ],
                "outputs": ["results/s{s}/seed-{n}.txt"],
            },
            "boom": {
                "kind": "shell-command",
                "environment": "_system",
                "command": "exit 1",
                "inputs": [{"from_stage_outputs": "ev"}],
                "outputs": ["results/other.txt"],
            },
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    outputs = [f"results/s{s}/seed-{n}.txt" for s in [1, 3] for n in [1, 2]]
    # DVC drops the ignore entries of stages that succeeded when a later
    # one fails, so a failed run has to put them back
    proc = subprocess.run(["calkit", "run"], capture_output=True, text=True)
    assert proc.returncode != 0
    repo = git.Repo()
    assert all(repo.ignored(path) for path in outputs)
    # And an output left unignored anyway, e.g., by an older Calkit, is
    # still not committed to Git by save
    for path in ["results/s1/.gitignore", "results/s3/.gitignore"]:
        os.remove(path)
    assert not any(repo.ignored(path) for path in outputs)
    subprocess.check_call(["calkit", "save", "-am", "Run", "--no-push"])
    tracked = repo.git.ls_files("results").splitlines()
    assert not set(outputs) & set(tracked)
    assert all(repo.ignored(path) for path in outputs)
    assert "dvc.lock" in repo.git.ls_files().splitlines()


def test_save_new_files_in_git_stored_output_dir(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = {
        "stages": {
            "fetch": {
                "kind": "shell-command",
                "environment": "_system",
                "command": "mkdir -p data/github && echo 1 > data/github/1.json",
                "outputs": [
                    {
                        "path": "data/github",
                        "storage": "git",
                        "delete_before_run": False,
                    }
                ],
            },
            "plot": {
                "kind": "shell-command",
                "environment": "_system",
                "wdir": "sub",
                "command": "mkdir -p figs && echo 1 > figs/1.txt",
                "outputs": [
                    {
                        "path": "figs",
                        "storage": "git",
                        "delete_before_run": False,
                    }
                ],
            },
        }
    }
    os.makedirs("sub")
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "run"])
    subprocess.check_call(["calkit", "save", "-am", "Run", "--no-push"])
    repo = git.Repo()
    assert "data/github/1.json" in repo.git.ls_files("data").splitlines()
    # A later run adds files to the persistent output, which belong in Git
    # with the rest of it, not ignored as if DVC cached the output, and not
    # sent to DVC by extension either, including for a stage with a wdir
    new_files = [
        "data/github/2.json",
        "data/github/plot.png",
        "sub/figs/plot.png",
    ]
    for path in new_files:
        with open(path, "w") as f:
            f.write("2")
    subprocess.check_call(["calkit", "save", "-am", "Run", "--no-push"])
    tracked = repo.git.ls_files().splitlines()
    assert set(new_files) <= set(tracked)
    assert not any(repo.ignored(path) for path in new_files)
    assert not os.path.exists("data/.gitignore")
    # Projects an older Calkit already broke have the output ignored, once
    # per file it saw, so both run and save have to undo that
    for run_first in [True, False]:
        with open("data/.gitignore", "w") as f:
            f.write("/github\n/github\n/github\n")
        repo.git.add("data/.gitignore")
        repo.git.commit("-m", "Ignore output")
        with open("data/github/3.json", "w") as f:
            f.write("3")
        if run_first:
            subprocess.check_call(["calkit", "run"])
        subprocess.check_call(["calkit", "save", "-am", "Run", "--no-push"])
        assert "data/github/3.json" in repo.git.ls_files("data").splitlines()
        with open("data/.gitignore") as f:
            assert "github" not in f.read()
        repo.git.rm("-q", "data/github/3.json")
        repo.git.commit("-m", "Remove 3")


@skipif_windows_docker
@pytest.mark.needs("docker")
def test_xenv_env_var(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    ck_info = calkit.load_calkit_info()
    ck_info["environments"] = {
        "here": {"kind": "system"},
        "box": {"kind": "docker", "image": "alpine:3.20"},
    }
    calkit.save_calkit_info(ck_info)

    def echo(env_name, *args):
        return subprocess.check_output(
            ["calkit", "xenv", "-n", env_name, "--no-check", *args]
            + ["--", "sh", "-c", "echo [$FOO][$BAR]"],
            text=True,
        )

    # Set in the process the command runs in, and handed to a container,
    # which inherits nothing from here
    for env_name in ["here", "box"]:
        out = echo(env_name, "--env-var", "FOO=bar", "--env-var", "BAR=2")
        assert "[bar][2]" in out, out
        assert "[][]" in echo(env_name)
    # Written as KEY=VALUE, and said so when it isn't
    proc = subprocess.run(
        ["calkit", "xenv", "-n", "here", "--env-var", "FOO", "--", "sh"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "KEY=VALUE" in proc.stderr


@pytest.mark.xdist_group("texlive")
def test_xenv_composed_env(tmp_dir, texlive_user_home, monkeypatch):
    from calkit.cli.main import run_in_env
    from calkit.environments import texlive

    monkeypatch.setenv("CALKIT_USER_HOME", texlive_user_home)
    monkeypatch.delenv("FONTCONFIG_FILE", raising=False)
    subprocess.check_call(["calkit", "init"])
    with open("requirements.txt", "w") as f:
        f.write("")
    ck_info = calkit.load_calkit_info()
    ck_info["environments"] = {
        "tex": {"kind": "texlive"},
        "py": {"kind": "uv-venv", "path": "requirements.txt", "with": ["tex"]},
    }
    calkit.save_calkit_info(ck_info)
    view_dir = texlive.check("tex", ck_info["environments"]["tex"])
    bin_dir = os.path.join(view_dir, "bin", texlive.get_platform())
    show = (
        "import os, shutil; print(shutil.which('kpsewhich')); "
        "print(os.environ['MPLCONFIGDIR']); "
        "print(os.environ['PATH'].split(os.pathsep).index(os.path.dirname("
        "shutil.which('python'))))"
    )

    def run(*args: str) -> list[str]:
        return subprocess.check_output(
            ["calkit", "xenv", "-n", "py", *args, "--", "python", "-c", show],
            text=True,
        ).splitlines()[-3:]

    # The command gets the guest's programs after the host's own, and
    # Matplotlib a config directory of its own
    kpsewhich, mplconfigdir, python_index = run()
    assert os.path.dirname(kpsewhich) == bin_dir
    assert mplconfigdir.startswith(
        os.path.join(texlive_user_home, ".calkit", "composed")
    )
    assert python_index == "0"
    # This process isn't changed, which matters in a long-lived one, e.g.,
    # Jupyter's server
    path = os.environ["PATH"]
    run_in_env(cmd=["python", "-c", "pass"], env_name="py")
    assert os.environ["PATH"] == path
    assert "FONTCONFIG_FILE" not in os.environ
    # What the project and --env-var set wins
    ck_info["env_vars"] = {"MPLCONFIGDIR": "from-project"}
    calkit.save_calkit_info(ck_info)
    assert run()[1] == "from-project"
    assert run("--env-var", "MPLCONFIGDIR=from-cli")[1] == "from-cli"
    # One that can't be composed is said so
    ck_info["environments"]["py"]["with"] = ["nope"]
    calkit.save_calkit_info(ck_info)
    proc = subprocess.run(
        ["calkit", "xenv", "-n", "py", "--", "python", "-c", "pass"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "Environment 'py' has 'nope' in 'with'" in proc.stderr
    assert "Environment 'py': Environment" not in proc.stderr


def test_add_says_why_git_refused(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    with open(".gitignore", "w") as f:
        f.write("secret.txt\n")
    with open("secret.txt", "w") as f:
        f.write("shh")
    # What Git refuses is said rather than passed over, and doesn't stop
    # the rest of what was asked for
    proc = subprocess.run(
        ["calkit", "add", "secret.txt", "-t", "git"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    said = proc.stdout + proc.stderr
    assert "Failed to add secret.txt to Git" in said
    assert "ignored by one of your .gitignore files" in said
    assert not git.Repo().git.ls_files("secret.txt")


def test_push_carries_annotated_tags(tmp_dir):
    """Annotated tags should reach the remote along with their commits.

    A plain ``git push`` leaves tags behind, so a project that tags its
    results ends up with labels that exist only on the machine that made
    them.
    """
    remote = os.path.join(tmp_dir, "remote.git")
    subprocess.check_call(["git", "init", "--bare", "-q", remote])
    work = os.path.join(tmp_dir, "work")
    os.makedirs(work)
    os.chdir(work)
    subprocess.check_call(["git", "init", "-q"])
    subprocess.check_call(["git", "remote", "add", "origin", remote])
    # ``calkit init`` commits what it creates, so there is a commit to tag
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(["git", "tag", "-a", "v0.1.0", "-m", "First"])
    # An unannotated tag must stay local: --follow-tags is deliberately the
    # conservative form, so scratch tags do not get published by accident
    subprocess.check_call(["git", "tag", "scratch"])
    subprocess.check_call(
        [
            "calkit",
            "push",
            "git",
            "--git-arg",
            "-u",
            "--git-arg",
            "origin",
            "--git-arg",
            "HEAD",
        ]
    )
    tags = subprocess.check_output(
        ["git", "ls-remote", "--tags", remote], text=True
    )
    assert "v0.1.0" in tags
    assert "scratch" not in tags


def test_push_and_pull_data_in_folder_with_ignored_contents(
    tmp_dir: Path, tmp_path: Path
) -> None:
    subprocess.check_call(["calkit", "init"])
    dvc_remote = tmp_path / "dvc_remote"
    dvc_remote.mkdir()
    subprocess.check_call(
        ["dvc", "remote", "add", "-d", "origin", str(dvc_remote)]
    )
    # Everything in data/ is ignored but the pointers, so the folder itself
    # isn't, and DVC has to look inside it to find them
    with open(".gitignore", "a") as f:
        f.write("data/*\n!data/*.dvc\n")
    os.makedirs("data")
    with open("data/raw.bin", "w") as f:
        f.write("raw data")
    subprocess.check_call(["dvc", "add", "data/raw.bin"])
    subprocess.check_call(["calkit", "push", "--no-git", "--no-check-auth"])
    assert any(p.is_file() for p in dvc_remote.rglob("*"))
    # It comes back on a pull
    os.remove("data/raw.bin")
    calkit.overleaf.rmtree(".dvc/cache")
    subprocess.check_call(["calkit", "pull", "--no-git", "--no-check-auth"])
    with open("data/raw.bin") as f:
        assert f.read() == "raw data"


@skipif_windows_mock_scheduler
def test_run_switch_env(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    ck_info = {
        "environments": {
            "cluster": {
                "kind": "switch",
                "switch": [
                    # Defined in place, since only the switch uses it
                    {
                        "when": [{"env_var_equals": "CK_TEST_SITE=cluster"}],
                        "use": {
                            "kind": "slurm",
                            "default_setup": ["export WHERE=slurm"],
                        },
                    },
                    {"use": "here"},
                ],
            },
            "here": {"kind": "system", "default_setup": ["export WHERE=here"]},
        },
        "pipeline": {
            "stages": {
                "s": {
                    "kind": "shell-command",
                    "command": "echo $WHERE > out.txt",
                    "environment": "cluster",
                    "outputs": ["out.txt"],
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    env = {k: v for k, v in os.environ.items() if k != "CK_TEST_SITE"}
    # Off the cluster, the switch picks the system env and runs it here,
    # writing the log a scheduler stage declares
    subprocess.check_call(["calkit", "run"], env=env)
    with open("out.txt") as f:
        assert f.read().strip() == "here"
    assert os.path.isfile(".calkit/scheduler/logs/s.out")
    runs = sorted(os.listdir(os.path.join(".calkit", "local", "runs")))
    with open(os.path.join(".calkit", "local", "runs", runs[-1])) as f:
        run_info = json.load(f)
    assert run_info["switches"] == {"cluster": "here"}
    assert run_info["stages"]["s"]["switches"] == {"cluster": "here"}
    with open(STAGE_RUNS_FPATH) as f:
        stage_runs = json.load(f)
    assert stage_runs["s"]["environment"] == {
        "name": "cluster",
        "switch": "here",
    }
    # The command file it runs from is committed, so it's staged
    staged = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only"], text=True
    ).splitlines()
    assert ".calkit/stage-commands/s.sh" in staged
    out = subprocess.check_output(["calkit", "status"], env=env, text=True)
    assert "Environment 'cluster' picks 'here' here" in out
    # Moving to the cluster doesn't make the stage stale, since it doesn't
    # depend on which option was picked
    env["CK_TEST_SITE"] = "cluster"
    subprocess.check_call(["calkit", "run"], env=env)
    with open("out.txt") as f:
        assert f.read().strip() == "here"
    with open(STAGE_RUNS_FPATH) as f:
        assert json.load(f) == stage_runs
    # Rerunning it there goes through the scheduler
    subprocess.check_call(["calkit", "run", "-K", "-f"], env=env)
    with open("out.txt") as f:
        assert f.read().strip() == "slurm"
    with open(STAGE_RUNS_FPATH) as f:
        assert json.load(f)["s"]["environment"]["switch"] == "cluster.1"
    # xenv resolves a switch passed by name
    out = subprocess.check_output(
        ["calkit", "xenv", "-n", "cluster", "--", "echo", "picked"],
        env={k: v for k, v in env.items() if k != "CK_TEST_SITE"},
        text=True,
    )
    assert "picked" in out


def test_run_skips_stages_that_cant_run_here(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    ck_info = {
        "environments": {
            "lab": {
                "kind": "system",
                "requirements": [{"kind": "env-var", "name": "CK_TEST_TOKEN"}],
            },
        },
        "pipeline": {
            "stages": {
                "fetch": {
                    "kind": "shell-command",
                    "command": "printenv CK_TEST_TOKEN > data.txt",
                    "environment": "lab",
                    "inputs": [{"kind": "env-var", "name": "CK_TEST_TOKEN"}],
                    "outputs": [{"path": "data.txt", "storage": "git"}],
                },
                "use": {
                    "kind": "shell-command",
                    "command": "cat data.txt > result.txt",
                    "environment": "_system",
                    "inputs": ["data.txt"],
                    "outputs": [{"path": "result.txt", "storage": "git"}],
                },
                "settled": {
                    "kind": "shell-command",
                    "command": "echo done > settled.txt",
                    "environment": "lab",
                    "outputs": [{"path": "settled.txt", "storage": "git"}],
                },
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    env = dict(os.environ)
    # Where the requirement is met, everything runs
    env["CK_TEST_TOKEN"] = "first"
    subprocess.check_call(["calkit", "run"], env=env)
    with open("result.txt") as f:
        assert f.read().strip() == "first"
    # Somewhere it isn't, the stage is skipped and its output kept, and
    # what depends on that output still runs from it
    del env["CK_TEST_TOKEN"]
    with open("calkit.yaml") as f:
        ck_info = calkit.ryaml.load(f)
    ck_info["pipeline"]["stages"]["fetch"]["command"] = (
        "printenv CK_TEST_TOKEN > data.txt && echo changed"
    )
    ck_info["pipeline"]["stages"]["use"]["command"] = (
        "cat data.txt data.txt > result.txt"
    )
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    res = subprocess.run(
        ["calkit", "run"], env=env, capture_output=True, text=True
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "can't run on this machine" in res.stdout + res.stderr
    assert "skipping 1 out-of-date stage" in res.stdout
    assert "successfully" not in res.stdout
    # One that is up to date isn't worth mentioning
    assert "'settled' can't run" not in res.stdout + res.stderr
    assert "'settled' is out of date" not in res.stdout + res.stderr
    with open("data.txt") as f:
        assert f.read().strip() == "first"
    with open("result.txt") as f:
        assert f.read().split() == ["first", "first"]
    runs = sorted(os.listdir(os.path.join(".calkit", "local", "runs")))
    with open(os.path.join(".calkit", "local", "runs", runs[-1])) as f:
        run_info = json.load(f)
    assert "CK_TEST_TOKEN" in run_info["gated"]["fetch"]
    assert run_info["stages"]["fetch"]["status"] == "gated"
    # It stays stale, since running it where it can is what updates it
    out = subprocess.check_output(["calkit", "status"], env=env, text=True)
    assert "fetch" in out
    assert "can't run on this machine" in out
    # A variable calkit.yaml sets counts for status, as it does for run
    with open("calkit.yaml") as f:
        ck_yaml = f.read()
    with open("calkit.yaml", "a") as f:
        f.write("env_vars:\n  CK_TEST_TOKEN: from-yaml\n")
    out = subprocess.check_output(["calkit", "status"], env=env, text=True)
    assert "can't run on this machine" not in out
    with open("calkit.yaml", "w") as f:
        f.write(ck_yaml)
    # Asking for it by name and not getting it is a failure
    res = subprocess.run(
        ["calkit", "run", "fetch"], env=env, capture_output=True, text=True
    )
    assert res.returncode != 0
    assert "out of date and couldn't run" in res.stderr
    # As is any with --strict, e.g., in CI where every stage should run
    res = subprocess.run(
        ["calkit", "run", "--strict"], env=env, capture_output=True, text=True
    )
    assert res.returncode != 0
    assert "'fetch' is out of date and couldn't run" in res.stderr
    # A skipped stage is still caught out of date when a stage it depends
    # on runs after DVC has visited it
    with open("calkit.yaml") as f:
        ck_info = calkit.ryaml.load(f)
    ck_info["pipeline"]["stages"]["g"] = {
        "kind": "shell-command",
        "command": "cat u.txt > g.txt",
        "environment": "lab",
        "inputs": ["u.txt"],
        "outputs": [{"path": "g.txt", "storage": "git"}],
    }
    ck_info["pipeline"]["stages"]["u"] = {
        "kind": "shell-command",
        "command": "cat in.txt > u.txt",
        "environment": "_system",
        "inputs": ["in.txt"],
        "outputs": [{"path": "u.txt", "storage": "git"}],
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open("in.txt", "w") as f:
        f.write("1\n")
    subprocess.check_call(
        ["calkit", "run", "g"], env=env | {"CK_TEST_TOKEN": "first"}
    )
    with open("in.txt", "w") as f:
        f.write("2\n")
    res = subprocess.run(
        ["calkit", "run"], env=env, capture_output=True, text=True
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "'g' is out of date but can't run" in res.stdout
    with open("u.txt") as f:
        assert f.read().strip() == "2"
    with open("g.txt") as f:
        assert f.read().strip() == "1"
    runs = sorted(os.listdir(os.path.join(".calkit", "local", "runs")))
    with open(os.path.join(".calkit", "local", "runs", runs[-1])) as f:
        run_info = json.load(f)
    assert run_info["stages"]["g"]["status"] == "gated"
    # So is a stage that can't run because something is wrong, though the
    # rest still runs
    with open("calkit.yaml") as f:
        ck_info = calkit.ryaml.load(f)
    ck_info["environments"]["broken"] = {
        "kind": "system",
        "host": "calkit-test.invalid",
        "requirements": ["git"],
    }
    ck_info["pipeline"]["stages"]["odd"] = {
        "kind": "shell-command",
        "command": "echo odd > odd.txt",
        "environment": "broken",
        "outputs": [{"path": "odd.txt", "storage": "git"}],
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    env["CK_TEST_TOKEN"] = "second"
    res = subprocess.run(
        ["calkit", "run"], env=env, capture_output=True, text=True
    )
    assert res.returncode != 0
    assert "'odd' is out of date and couldn't run" in res.stderr
    assert not os.path.isfile("odd.txt")
    with open("result.txt") as f:
        assert f.read().split() == ["second", "second"]


def test_run_skip(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    period_file = ".calkit/local/current-periods/1-day-utc.txt"
    ck_info = {
        "pipeline": {
            "stages": {
                "fetch": {
                    "kind": "shell-command",
                    "command": f"cat {period_file} > data.txt",
                    "environment": "_system",
                    "inputs": [{"kind": "schedule", "period": "1 day"}],
                    "outputs": [{"path": "data.txt", "storage": "git"}],
                },
                "use": {
                    "kind": "shell-command",
                    "command": "cat data.txt > result.txt",
                    "environment": "_system",
                    "inputs": ["data.txt"],
                    "outputs": [{"path": "result.txt", "storage": "git"}],
                },
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    env = dict(os.environ) | {"CALKIT_NOW": "2026-10-20T08:00:00Z"}
    subprocess.check_call(["calkit", "run"], env=env)
    # The next day, a skipped stage keeps its output, what depends on it
    # still runs from that, and even --strict doesn't fail on it
    env["CALKIT_NOW"] = "2026-10-21T08:00:00Z"
    ck_info["pipeline"]["stages"]["use"]["command"] = (
        "cat data.txt data.txt > result.txt"
    )
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open(STAGE_RUNS_FPATH) as f:
        fetch_run = json.load(f)["fetch"]
    res = subprocess.run(
        ["calkit", "run", "--skip", "fetch", "--strict"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Skipped out-of-date stage 'fetch' as requested" in res.stdout
    assert "successfully" in res.stdout
    assert "can't run" not in res.stdout + res.stderr
    with open("data.txt") as f:
        assert f.read().strip() == "2026-10-20"
    with open("result.txt") as f:
        assert f.read().split() == ["2026-10-20", "2026-10-20"]
    with open(STAGE_RUNS_FPATH) as f:
        assert json.load(f)["fetch"] == fetch_run
    runs = sorted(os.listdir(os.path.join(".calkit", "local", "runs")))
    with open(os.path.join(".calkit", "local", "runs", runs[-1])) as f:
        run_info = json.load(f)
    assert run_info["stages"]["fetch"]["status"] == "skipped"
    assert "fetch" not in run_info.get("gated", {})
    # It stays out of date, so a run without the skip catches it up
    out = subprocess.check_output(["calkit", "status"], env=env, text=True)
    assert "fetch" in out
    subprocess.check_call(["calkit", "run"], env=env)
    with open("result.txt") as f:
        assert f.read().split() == ["2026-10-21", "2026-10-21"]
    # A stage that isn't there is an error rather than nothing skipped
    res = subprocess.run(
        ["calkit", "run", "--skip", "fetchh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "No stage to skip named: fetchh" in res.stdout + res.stderr


def test_run_offers_requirements_of_stages_that_would_run(
    tmp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    import calkit.core

    subprocess.check_call(["calkit", "init"])
    token = {"kind": "env-var", "name": "CK_TEST_TOKEN"}
    ck_info: dict = {
        "environments": {
            "lab": {"kind": "system", "requirements": [token]},
        },
        "pipeline": {
            "stages": {
                "fetch": {
                    "kind": "shell-command",
                    "command": "printenv CK_TEST_TOKEN > data.txt",
                    "environment": "lab",
                    "inputs": [{"kind": "env-var", "name": "CK_TEST_TOKEN"}],
                    "outputs": [{"path": "data.txt", "storage": "git"}],
                },
                # Shares the requirement, through its own list
                "fetch2": {
                    "kind": "shell-command",
                    "command": "printenv CK_TEST_TOKEN > data2.txt",
                    "environment": "_system",
                    "requirements": [token],
                    "outputs": [{"path": "data2.txt", "storage": "git"}],
                },
                # Up to date, but runs after one that isn't
                "report": {
                    "kind": "shell-command",
                    "command": "cat data.txt > report.txt",
                    "environment": "_system",
                    "requirements": [
                        {"kind": "env-var", "name": "CK_TEST_REPORT"}
                    ],
                    "inputs": ["data.txt"],
                    "outputs": [{"path": "report.txt", "storage": "git"}],
                },
                "settled": {
                    "kind": "shell-command",
                    "command": "echo done > settled.txt",
                    "environment": "_system",
                    "requirements": [
                        {"kind": "env-var", "name": "CK_TEST_SETTLED"}
                    ],
                    "outputs": [{"path": "settled.txt", "storage": "git"}],
                },
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    env = dict(os.environ) | {
        "CK_TEST_TOKEN": "first",
        "CK_TEST_REPORT": "r",
        "CK_TEST_SETTLED": "s",
    }
    subprocess.check_call(["calkit", "run"], env=env)
    for name in ("CK_TEST_TOKEN", "CK_TEST_REPORT", "CK_TEST_SETTLED"):
        monkeypatch.setenv(name, "unset")
        monkeypatch.delenv(name)

    def make_stale() -> None:
        with open("calkit.yaml") as f:
            info = calkit.ryaml.load(f)
        for name in ("fetch", "fetch2"):
            info["pipeline"]["stages"][name]["command"] += " && echo again"
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(info, f)

    # On a terminal, what the stages that would run need is asked for,
    # once however many share it, and not for one that's up to date
    make_stale()
    monkeypatch.setattr(calkit.core, "is_tty", lambda: True)
    runner = CliRunner()
    res = runner.invoke(calkit_app, ["run"], input="second\nrep\n")
    assert res.exit_code == 0, res.output
    assert res.output.count("Missing env var 'CK_TEST_TOKEN'") == 1
    assert "Stage 'fetch' is out of date, but this machine" in res.output
    assert "Stage 'fetch2' is out of date" not in res.output
    assert "Missing env var 'CK_TEST_REPORT'" in res.output
    assert "CK_TEST_SETTLED" not in res.output
    for path, value in [
        ("data.txt", "second"),
        ("data2.txt", "second"),
        ("report.txt", "second"),
        ("settled.txt", "done"),
    ]:
        with open(path) as f:
            assert f.read().strip() == value
    # What's entered is in the stage's inputs as it ran, so it's up to date
    out = subprocess.check_output(
        ["calkit", "status"], text=True, stdin=subprocess.DEVNULL
    )
    assert "Pipeline is up to date" in out, out
    # Declining skips them, as without a terminal, and asking for one by
    # name, or for all with --strict, still fails
    os.remove(".env")
    monkeypatch.delenv("CK_TEST_TOKEN")
    make_stale()
    res = runner.invoke(calkit_app, ["run"], input="\n")
    assert res.exit_code == 0, res.output
    assert res.output.count("Missing env var 'CK_TEST_TOKEN'") == 1
    assert "skipping 2 out-of-date stage" in res.output
    assert "'calkit check reqs --stale'" in res.output
    with open("data.txt") as f:
        assert f.read().strip() == "second"
    for args in (["run", "fetch"], ["run", "--strict"]):
        res = runner.invoke(calkit_app, args, input="\n")
        assert res.exit_code != 0
        assert "'fetch' is out of date and couldn't run" in res.output
    # Nor is anything asked for stages skipped by name, which stay skipped
    res = runner.invoke(
        calkit_app,
        ["run", "--skip", "fetch", "--skip", "fetch2"],
        input="third\n",
    )
    assert res.exit_code == 0, res.output
    assert "Missing env var" not in res.output
    with open("data.txt") as f:
        assert f.read().strip() == "second"
    # Without a terminal nothing is asked
    monkeypatch.setattr(calkit.core, "is_tty", lambda: False)
    res = runner.invoke(calkit_app, ["run"], input="third\n")
    assert res.exit_code == 0, res.output
    assert "Missing env var" not in res.output
    assert "skipping 2 out-of-date stage" in res.output
    # Status says where to get what's missing
    out = subprocess.check_output(
        ["calkit", "status"], text=True, stdin=subprocess.DEVNULL
    )
    assert (
        "can't run on this machine: env-var 'CK_TEST_TOKEN' not found; "
        "'calkit check reqs --stale' offers to install or set up what's "
        "missing"
    ) in out
    # With --single-item, a stage before the one named that's out of date
    # won't run, so doesn't put it out of date
    monkeypatch.setattr(calkit.core, "is_tty", lambda: True)
    monkeypatch.delenv("CK_TEST_REPORT", raising=False)
    res = runner.invoke(
        calkit_app, ["run", "--single-item", "report"], input="\n"
    )
    assert res.exit_code == 0, res.output
    assert "CK_TEST_REPORT" not in res.output
    # A stage waiting on one whose requirements were declined isn't asked
    # about or run, even with its own met
    monkeypatch.setenv("CK_TEST_TOKEN", "third")
    monkeypatch.setenv("CK_TEST_REPORT", "r")
    with open("calkit.yaml") as f:
        info = calkit.ryaml.load(f)
    for name, extra in [
        ("up", {}),
        ("down", {"inputs": ["up.txt"]}),
    ]:
        info["pipeline"]["stages"][name] = {
            "kind": "shell-command",
            "command": f"echo {name} > {name}.txt",
            "environment": "_system",
            "requirements": [
                {"kind": "env-var", "name": f"CK_TEST_{name.upper()}"}
            ],
            "outputs": [{"path": f"{name}.txt", "storage": "git"}],
        } | extra
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(info, f)
    monkeypatch.setenv("CK_TEST_DOWN", "d")
    monkeypatch.delenv("CK_TEST_DOWN")
    res = runner.invoke(calkit_app, ["run"], input="\nd\n")
    assert res.exit_code == 0, res.output
    assert "Missing env var 'CK_TEST_UP'" in res.output
    assert "Missing env var 'CK_TEST_DOWN'" not in res.output
    assert not os.path.exists("down.txt")
    # A Markdown stage named with --single-item is offered as its blocks
    with open("doc.md", "w") as f:
        f.write(
            "```sh calkit stage name=one environment=_system "
            "requirements=[{kind: env-var, name: CK_TEST_DOC}] "
            "outputs=[{path: one.txt, storage: git}]\n"
            "printenv CK_TEST_DOC > one.txt\n"
            "```\n"
        )
    info["pipeline"]["stages"]["doc"] = {
        "kind": "markdown",
        "target_path": "doc.md",
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(info, f)
    res = runner.invoke(
        calkit_app, ["run", "--single-item", "doc"], input="docs\n"
    )
    assert res.exit_code == 0, res.output
    assert "Missing env var 'CK_TEST_DOC'" in res.output
    with open("one.txt") as f:
        assert f.read().strip() == "docs"


def test_run_reruns_when_an_env_var_input_changes(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    ck_info = {
        "environments": {
            "here": {
                "kind": "system",
                "inputs": [{"kind": "env-var", "name": "CK_TEST_SITE"}],
            },
        },
        "pipeline": {
            "stages": {
                "s": {
                    "kind": "shell-command",
                    "command": "printenv CK_TEST_MODE > out.txt",
                    "environment": "here",
                    "inputs": [{"kind": "env-var", "name": "CK_TEST_MODE"}],
                    "outputs": [{"path": "out.txt", "storage": "git"}],
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    env = dict(os.environ) | {"CK_TEST_MODE": "a", "CK_TEST_SITE": "x"}
    subprocess.check_call(["calkit", "run"], env=env)
    with open("out.txt") as f:
        assert f.read().strip() == "a"
    # The values are hashed rather than written down
    with open(os.path.join(".calkit", "env-vars", "s.json")) as f:
        hashes = json.load(f)
    assert set(hashes) == {"CK_TEST_MODE", "CK_TEST_SITE"}
    assert "a" not in hashes.values()
    out = subprocess.check_output(["calkit", "status"], env=env, text=True)
    assert "Pipeline is up to date" in out
    # Changing the stage's value, or its environment's, reruns it
    env["CK_TEST_MODE"] = "b"
    out = subprocess.check_output(["calkit", "status"], env=env, text=True)
    assert "Stale stages" in out
    subprocess.check_call(["calkit", "run"], env=env)
    with open("out.txt") as f:
        assert f.read().strip() == "b"
    # A process without the value, e.g., an editor's, doesn't make it stale,
    # but a run without it does
    unset = {k: v for k, v in env.items() if k != "CK_TEST_MODE"}
    out = subprocess.check_output(["calkit", "status"], env=unset, text=True)
    assert "Pipeline is up to date" in out
    # The stage itself fails without it
    subprocess.run(["calkit", "run"], env=unset, capture_output=True)
    with open(os.path.join(".calkit", "env-vars", "s.json")) as f:
        assert json.load(f)["CK_TEST_MODE"] is None
    subprocess.check_call(["calkit", "run"], env=env)
    env["CK_TEST_SITE"] = "y"
    out = subprocess.check_output(["calkit", "status"], env=env, text=True)
    assert "Stale stages" in out


def test_run_reruns_once_per_schedule_period(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    period_file = ".calkit/local/current-periods/1-day-utc.txt"
    ck_info = {
        "pipeline": {
            "stages": {
                "daily": {
                    "kind": "shell-command",
                    "command": f"cat {period_file} >> out.txt",
                    "environment": "_system",
                    "inputs": [{"kind": "schedule", "period": "1 day"}],
                    "outputs": [
                        {
                            "path": "out.txt",
                            "storage": "git",
                            "delete_before_run": False,
                        }
                    ],
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    env = dict(os.environ) | {"CALKIT_NOW": "2026-10-20T08:00:00Z"}
    subprocess.check_call(["calkit", "run"], env=env)
    with open("out.txt") as f:
        assert f.read().split() == ["2026-10-20"]
    with open("dvc.yaml") as f:
        assert period_file in yaml.safe_load(f)["stages"]["daily"]["deps"]
    # Later the same day it's up to date, so a run skips it
    env["CALKIT_NOW"] = "2026-10-20T23:00:00Z"
    out = subprocess.check_output(["calkit", "status"], env=env, text=True)
    assert "Pipeline is up to date" in out
    subprocess.check_call(["calkit", "run"], env=env)
    with open("out.txt") as f:
        assert f.read().split() == ["2026-10-20"]
    # The next day it runs again, once
    env["CALKIT_NOW"] = "2026-10-21T01:00:00Z"
    out = subprocess.check_output(["calkit", "status"], env=env, text=True)
    assert "Stale stages" in out
    subprocess.check_call(["calkit", "run"], env=env)
    subprocess.check_call(["calkit", "run"], env=env)
    with open("out.txt") as f:
        assert f.read().split() == ["2026-10-20", "2026-10-21"]


def test_run_date_range_periods(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    state = ".calkit/date-ranges/fetch/{q}"
    quarters = {"kind": "date-range", "start": "2026Q3", "step": "1 quarter"}
    ck_info = {
        "pipeline": {
            "stages": {
                # Fingerprints the source, which reruns only the quarters
                # whose fingerprint changed
                "probe": {
                    "kind": "shell-command",
                    "command": f"cp src/{{q}}.txt {state}/listing.txt",
                    "environment": "_system",
                    "iterate_over": [{"arg_name": "q", "values": [quarters]}],
                    "inputs": ["src"],
                    "outputs": [
                        {"path": f"{state}/listing.txt", "storage": "git"}
                    ],
                },
                "fetch": {
                    "kind": "shell-command",
                    "command": f"cp {state}/period.json out-{{q}}.json && "
                    "echo {q} >> runs.txt",
                    "environment": "_system",
                    "iterate_over": [
                        {
                            "arg_name": "q",
                            "values": [quarters | {"state_storage": "git"}],
                        }
                    ],
                    # runs.txt only records which items ran, so isn't an output
                    "outputs": [{"path": "out-{q}.json", "storage": "git"}],
                },
                # Has no items until its range has a full day
                "later": {
                    "kind": "shell-command",
                    "command": "echo later-{q} | tee -a runs.txt > later-{q}.txt",
                    "environment": "_system",
                    "iterate_over": [
                        {
                            "arg_name": "q",
                            "values": [
                                quarters
                                | {"start": "2026-11-25", "step": "1 month"}
                            ],
                        }
                    ],
                    "outputs": [{"path": "later-{q}.txt", "storage": "git"}],
                },
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    os.makedirs("src")
    for q in ["2026Q3", "2026Q4", "2027Q1"]:
        with open(f"src/{q}.txt", "w") as f:
            f.write("a\n")
    env = dict(os.environ) | {"CALKIT_NOW": "2026-11-10T08:00:00Z"}

    def run(now: str) -> list[str]:
        env["CALKIT_NOW"] = now
        subprocess.check_call(["calkit", "run"], env=env)
        if not os.path.exists("runs.txt"):
            return []
        with open("runs.txt") as f:
            runs = f.read().split()
        os.remove("runs.txt")
        return runs

    assert run("2026-11-10T08:00:00Z") == ["2026Q3", "2026Q4"]
    with open("out-2026Q4.json") as f:
        assert json.load(f)["through"] == "2026-11-09"
    with open("dvc.yaml") as f:
        deps = yaml.safe_load(f)["stages"]["fetch"]["deps"]
    assert deps == [".calkit/date-ranges/fetch/${item.q}"]
    # A preview compile writes no state, since it can be committed
    shutil.rmtree(".calkit/date-ranges")
    calkit.pipeline.to_dvc(write=True)
    assert not os.path.exists(".calkit/date-ranges")
    subprocess.check_call(["calkit", "status"], env=env)
    assert os.path.isfile(".calkit/date-ranges/fetch/2026Q4/period.json")
    # Only the open quarter goes out of date the next day
    assert run("2026-11-11T08:00:00Z") == ["2026Q4"]
    # A closed quarter reruns when its fingerprint changes
    with open("src/2026Q3.txt", "w") as f:
        f.write("b\n")
    assert run("2026-11-11T09:00:00Z") == ["2026Q3"]
    assert sorted(run("2026-11-26T08:00:00Z")) == ["2026Q4", "later-2026-11"]
    # A quarter is added once it has a full day, the day the last closes
    assert sorted(run("2027-01-01T08:00:00Z")) == ["2026Q4", "later-2026-12"]
    assert sorted(run("2027-01-02T08:00:00Z")) == ["2027Q1", "later-2027-01"]
    with open("out-2026Q4.json") as f:
        assert json.load(f)["through"] == "2026-12-31"


def test_merge(tmp_dir):
    def write(path: str, text: str) -> None:
        with open(path, "w") as f:
            f.write(text + "\n")

    def commit(message: str) -> None:
        subprocess.check_call(["calkit", "run"])
        subprocess.check_call(["git", "add", "-A"])
        subprocess.check_call(["git", "commit", "-qm", message])

    def merge(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["calkit", "merge", *args],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )

    subprocess.check_call(["calkit", "init"])
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = {
        "stages": {
            "a": {
                "kind": "shell-command",
                "command": "cat a1.in a2.in > a.txt",
                "environment": "_system",
                "inputs": ["a1.in", "a2.in"],
                "outputs": [{"path": "a.txt", "storage": "git"}],
            }
        }
    }
    calkit.save_calkit_info(ck_info)
    write("a1.in", "1")
    write("a2.in", "2")
    commit("Base")
    subprocess.check_call(["git", "checkout", "-qb", "other"])
    write("a2.in", "2 theirs")
    commit("Theirs")
    subprocess.check_call(["git", "checkout", "-q", "-"])
    write("a1.in", "1 ours")
    commit("Ours")
    head = git.Repo().head.commit.hexsha
    # A squash merge is resolved the same way, then committed once
    assert merge("other", "--squash").returncode != 0
    assert merge("--abort").returncode == 0
    assert not os.path.exists(os.path.join(".git", "SQUASH_MSG"))
    res = merge("other", "--squash", "--prefer", "theirs", "-m", "Squash")
    assert res.returncode == 0, res.stdout + res.stderr
    squashed = git.Repo().head.commit
    assert len(squashed.parents) == 1
    assert str(squashed.message).strip() == "Squash"
    with open("a.txt") as f:
        assert f.read() == "1\n2 theirs\n"
    subprocess.check_call(["git", "reset", "-q", "--hard", head])
    # The inputs merge, but the stage ran on both sides, so it needs a choice
    assert merge().returncode != 0
    res = merge("other")
    assert res.returncode != 0
    assert "Stage 'a' changed on both sides" in res.stdout + res.stderr
    # Which can be made after aborting and starting over
    assert merge("--abort").returncode == 0
    assert git.Repo().head.commit.hexsha == head
    assert not os.path.exists(os.path.join(".git", "MERGE_HEAD"))
    assert merge("other").returncode != 0
    res = merge("--continue", "--theirs", "a")
    assert res.returncode == 0, res.stdout + res.stderr
    commit_ = git.Repo().head.commit
    assert len(commit_.parents) == 2
    with open("a.txt") as f:
        assert f.read() == "1\n2 theirs\n"
    subprocess.check_call(["calkit", "check", "stage-runs"])
    # It ran with neither side's inputs, so it reruns
    status = calkit.pipeline.get_status(
        check_environments=False, clean_notebooks=False
    )
    assert [n.split("@")[0] for n in status.stale_stage_names] == ["a"]
    # A file someone wrote that changed on both sides is theirs to combine,
    # and is staged once its marks are gone
    subprocess.check_call(["git", "checkout", "-qb", "notes"])
    write("notes.txt", "notes theirs")
    commit("Notes theirs")
    subprocess.check_call(["git", "checkout", "-q", "-"])
    write("notes.txt", "notes ours")
    commit("Notes ours")
    res = merge("notes")
    assert res.returncode != 0
    assert "Couldn't combine the changes to notes.txt" in res.stderr
    res = merge("--continue")
    assert res.returncode != 0
    assert "notes.txt" in res.stderr
    write("notes.txt", "notes both")
    res = merge("--continue")
    assert res.returncode == 0, res.stdout + res.stderr
    assert len(git.Repo().head.commit.parents) == 2
    assert not git.Repo().is_dirty()
    # A binary file, and one deleted on a side, never had marks, so they
    # aren't taken as resolved, and are named with how to resolve them
    subprocess.check_call(["git", "checkout", "-qb", "binary"])
    with open("fig.png", "wb") as f:
        f.write(b"\x89PNG\0theirs")
    os.remove("notes.txt")
    commit("Theirs again")
    subprocess.check_call(["git", "checkout", "-q", "-"])
    with open("fig.png", "wb") as f:
        f.write(b"\x89PNG\0ours")
    write("notes.txt", "notes changed")
    commit("Ours again")
    res = merge("binary")
    assert res.returncode != 0
    assert "fig.png changed on both sides" in res.stderr
    assert "notes.txt was deleted on one side" in res.stderr
    res = merge("--continue")
    assert res.returncode != 0
    assert "fig.png changed on both sides" in res.stderr
    subprocess.check_call(["git", "checkout", "--theirs", "--", "fig.png"])
    subprocess.check_call(["git", "add", "fig.png", "notes.txt"])
    res = merge("--continue")
    assert res.returncode == 0, res.stdout + res.stderr
    with open("fig.png", "rb") as f:
        assert f.read() == b"\x89PNG\0theirs"


def test_save_merges_remote_changes(tmp_dir, tmp_path_factory):
    def write(path: str, text: str) -> None:
        with open(path, "w") as f:
            f.write(text + "\n")

    def calkit_cmd(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["calkit", *args],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )

    def push_from_other(path: str, text: str, run: bool = False) -> None:
        cwd = os.getcwd()
        os.chdir(other)
        try:
            subprocess.check_call(["git", "pull", "-q", "--no-rebase"])
            write(path, text)
            if run:
                subprocess.check_call(["calkit", "run"])
            subprocess.check_call(["git", "add", "-A"])
            subprocess.check_call(["git", "commit", "-qm", f"Edit {path}"])
            subprocess.check_call(["git", "push", "-q"])
        finally:
            os.chdir(cwd)

    subprocess.check_call(["calkit", "init"])
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = {
        "stages": {
            "a": {
                "kind": "shell-command",
                "command": "cat a.in > a.txt",
                "environment": "_system",
                "inputs": ["a.in"],
                "outputs": [{"path": "a.txt", "storage": "git"}],
            }
        }
    }
    calkit.save_calkit_info(ck_info)
    write("a.in", "1")
    write("paper.tex", "Intro")
    subprocess.check_call(["calkit", "run"])
    subprocess.check_call(["git", "add", "-A"])
    subprocess.check_call(["git", "commit", "-qm", "Base"])
    bare = str(tmp_path_factory.mktemp("remote") / "repo.git")
    subprocess.check_call(["git", "init", "-q", "--bare", bare])
    subprocess.check_call(["git", "remote", "add", "origin", bare])
    branch = git.Repo().active_branch.name
    subprocess.check_call(["git", "push", "-q", "-u", "origin", branch])
    other = str(tmp_path_factory.mktemp("other") / "repo")
    subprocess.check_call(["git", "clone", "-q", bare, other])
    # A push someone made first is merged in, then this one goes too
    push_from_other("notes.txt", "From elsewhere")
    write("paper.tex", "Intro here")
    res = calkit_cmd("save", "-am", "Edit paper")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Merging changes from origin" in res.stdout
    remote_head = git.Repo(bare).commit(branch)
    assert remote_head.hexsha == git.Repo().head.commit.hexsha
    assert len(remote_head.parents) == 2
    assert os.path.isfile("notes.txt")
    # Running and saving brings it in first, with work in progress saved,
    # so the run includes it
    push_from_other("a.in", "2", run=True)
    write("paper.tex", "Intro here and there")
    res = calkit_cmd("run", "--save", "-m", "Run")
    assert res.returncode == 0, res.stdout + res.stderr
    with open("a.txt") as f:
        assert f.read() == "2\n"
    messages = [
        str(c.message).strip() for c in git.Repo().iter_commits(max_count=4)
    ]
    assert "Save work before merging changes from origin" in messages
    assert git.Repo(bare).commit(branch) == git.Repo().head.commit
    assert calkit_cmd("check", "stage-runs").returncode == 0
    # A stage added elsewhere is merged before the pipeline's read, so it
    # runs too
    stage_b = {
        "kind": "shell-command",
        "command": "cat a.in > b.txt",
        "environment": "_system",
        "inputs": ["a.in"],
        "outputs": [{"path": "b.txt", "storage": "git"}],
    }
    cwd = os.getcwd()
    os.chdir(other)
    try:
        subprocess.check_call(["git", "pull", "-q", "--no-rebase"])
        other_info = calkit.load_calkit_info()
        other_info["pipeline"]["stages"]["b"] = stage_b
        calkit.save_calkit_info(other_info)
        subprocess.check_call(["git", "commit", "-qam", "Add stage b"])
        subprocess.check_call(["git", "push", "-q"])
    finally:
        os.chdir(cwd)
    res = calkit_cmd("run", "--save", "-m", "Run with b")
    assert res.returncode == 0, res.stdout + res.stderr
    with open("b.txt") as f:
        assert f.read() == "2\n"
    assert git.Repo(bare).commit(branch) == git.Repo().head.commit
    # The same line edited on both sides stops, naming the file
    push_from_other("paper.tex", "Intro from elsewhere")
    write("paper.tex", "Intro from here")
    res = calkit_cmd("save", "-am", "Edit paper again")
    assert res.returncode != 0
    assert "Couldn't combine the changes to paper.tex" in res.stderr
    write("paper.tex", "Intro from both")
    res = calkit_cmd("merge", "--continue")
    assert res.returncode == 0, res.stdout + res.stderr
    assert calkit_cmd("push").returncode == 0
    assert git.Repo(bare).commit(branch) == git.Repo().head.commit


def test_manual_step(tmp_dir, monkeypatch, capsys):
    from calkit.cli.main.core import manual_step

    # Status says what a manual stage needs when it's out of date
    subprocess.check_call(["calkit", "init"])
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "pipeline": {
                    "stages": {
                        "export": {
                            "kind": "manual-step",
                            "message": "Export fig.png",
                            "outputs": ["fig.png"],
                        }
                    }
                }
            },
            f,
        )
    out = subprocess.run(
        ["calkit", "status"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).stdout
    assert "is a manual step: Export fig.png" in out
    # With nobody to do it, it says so rather than waiting
    out = subprocess.run(
        ["calkit", "manual-step", "-m", "Export fig.png"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    assert out.returncode != 0
    assert "Needs a manual step" in out.stdout + out.stderr
    assert "Export fig.png" in out.stdout + out.stderr
    # With someone there, the step isn't done until every output exists
    # and has changed, or they say keep it as is
    with open("fig.png", "w") as f:
        f.write("v1")
    monkeypatch.setattr(sys, "stdin", Mock(isatty=lambda: True))
    answers = []

    def answer() -> str:
        answers.append(capsys.readouterr().out)
        if len(answers) == 2:
            with open("new.png", "w") as f:
                f.write("v1")
        elif len(answers) == 3:
            return "n"
        elif len(answers) == 4:
            with open("fig.png", "w") as f:
                f.write("v2")
        return ""

    monkeypatch.setattr("builtins.input", answer)
    manual_step(
        message="Export fig.png and new.png",
        outputs=["fig.png", "new.png"],
    )
    # Every prompt is a whole line, so it shows under 'calkit run'
    assert answers[0].endswith(
        "Export fig.png and new.png. Press Enter when done.\n"
    )
    assert answers[1].startswith("Not there yet: new.png\n")
    assert answers[2].endswith("Unchanged: fig.png. Keep as is? [y/N]\n")
    assert len(answers) == 4
    assert capsys.readouterr().out.rstrip().endswith("Done")
    # Input ending says nobody's there too, as an empty stdin on Windows
    # passes for a terminal

    def no_input() -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", no_input)
    with pytest.raises(typer.Exit):
        manual_step(message="Export fig.png", outputs=["fig.png"])
    assert "nobody here to do it" in capsys.readouterr().err
    # A long message is wrapped to fit a terminal
    message = "In Photoshop, export paper/deficit_new.png from " + "x/" * 30
    monkeypatch.setattr("builtins.input", lambda: "")
    manual_step(message=message + ".")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) > 2
    assert all(len(line) <= 80 for line in lines)
    assert " ".join(lines[:-1]).endswith("x/. Press Enter when done.")
    # A file is opened with the app named, never the default for its type,
    # and a missing app still leaves the step to do
    with pytest.raises(typer.Exit):
        manual_step(message="Export fig.png", open_path="fig.png")
    assert "Name the app" in capsys.readouterr().err
    with pytest.raises(typer.Exit):
        manual_step(message="Export x.png", app="GIMP", open_path="x.xcf")
    assert "x.xcf doesn't exist" in capsys.readouterr().err
    launched = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kw: launched.append(args) or Mock(returncode=0),
    )
    monkeypatch.setattr(
        subprocess, "Popen", lambda args, **kw: launched.append(args)
    )
    for platform_name, which, expected in [
        ("darwin", None, ["open", "-a", "Inkscape", "fig.png"]),
        ("linux", "/usr/bin/inkscape", ["/usr/bin/inkscape", "fig.png"]),
        ("win32", None, None),
    ]:
        monkeypatch.setattr(sys, "platform", platform_name)
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: which if name == "inkscape" else None,
        )
        launched.clear()
        manual_step(
            message="Export fig.png", app="Inkscape", open_path="fig.png"
        )
        assert launched == ([] if expected is None else [expected])
        out = capsys.readouterr().out
        assert ("Can't find Inkscape" in out) == (expected is None)


@pytest.mark.skipif(sys.platform == "win32", reason="Fake app is a script")
def test_run_records_app_version(tmp_dir):
    # An app a stage runs from the system has its version recorded, since
    # no environment pins it
    bin_dir = os.path.abspath("bin")
    os.makedirs(bin_dir)
    fake = os.path.join(bin_dir, "inkscape")
    with open(fake, "w") as f:
        f.write(
            f"#!{sys.executable}\n"
            "import pathlib, sys\n"
            "if sys.argv[1] == '--version':\n"
            "    print('Inkscape 1.3.2 (091e20e, 2023-11-25)')\n"
            "    sys.exit()\n"
            "out = [a for a in sys.argv if a.startswith('--export-filename=')]\n"
            "pathlib.Path(out[0].split('=', 1)[1]).write_text('png')\n"
        )
    os.chmod(fake, 0o755)
    env = {**os.environ, "PATH": bin_dir + os.pathsep + os.environ["PATH"]}
    subprocess.check_call(["calkit", "init"])
    with open("setup.svg", "w") as f:
        f.write("<svg/>")
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "pipeline": {
                    "stages": {
                        "export-setup": {
                            "kind": "inkscape-export",
                            "source_path": "setup.svg",
                            "outputs": ["setup.png"],
                        }
                    }
                }
            },
            f,
        )
    subprocess.check_call(["calkit", "run"], env=env)
    with open(STAGE_RUNS_FPATH) as f:
        system = json.load(f)["export-setup"]["system"]
    assert system["inkscape_version"] == "1.3.2"
    assert system["os"] == platform.system()


def test_clone_data_not_available(tmp_dir, monkeypatch):
    from typer.testing import CliRunner

    real_check_call = subprocess.check_call

    def run(*cmd):
        real_check_call(cmd, stdout=subprocess.DEVNULL)

    def clone(name, remote_url=None):
        # Clone from a copy that has the remote, if any, in its DVC config
        source = os.path.join(top, f"source-{name}")
        run("git", "clone", "-q", origin, source)
        if remote_url is not None:
            run("dvc", "--cd", source, "remote", "add", "-d", "r", remote_url)
            run("git", "-C", source, "add", ".dvc/config")
            run(
                "git",
                "-C",
                source,
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test",
                "commit",
                "-qm",
                "Add remote",
            )

        def check_call(cmd, *args, **kwargs):
            # Clone only takes URLs, so have Git clone the local copy
            if cmd[:2] == ["git", "clone"]:
                cmd = ["git", "clone", "-q", source, cmd[-1]]
            return real_check_call(cmd, *args, **kwargs)

        with patch("subprocess.check_call", check_call):
            result = CliRunner().invoke(
                calkit.cli.main.app,
                ["clone", "https://example.com/me/proj.git", f"clone-{name}"],
            )
        os.chdir(top)
        return result, Path(top, f"clone-{name}")

    monkeypatch.setattr(calkit.github, "can_use_ssh", lambda **kwargs: False)
    monkeypatch.setattr(calkit, "record_project_path", lambda: None)
    top = os.getcwd()
    origin = os.path.join(top, "origin")
    os.makedirs(origin)
    os.chdir(origin)
    run("git", "init", "-q")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "Test")
    run("dvc", "init", "-q")
    Path("kept.txt").write_text("kept")
    Path("lost.txt").write_text("lost")
    run("dvc", "add", "-q", "kept.txt", "lost.txt")
    with open("dvc.yaml", "w") as f:
        yaml.safe_dump(
            {
                "stages": {
                    "never-run": {
                        "cmd": "echo hi > never-run.txt",
                        "outs": ["never-run.txt"],
                    }
                }
            },
            f,
        )
    run("git", "add", "-A")
    run("git", "commit", "-qm", "Add data")
    all_there = os.path.join(top, "all-there")
    partial = os.path.join(top, "partial")
    run("dvc", "remote", "add", "--local", "all-there", all_there)
    run("dvc", "remote", "add", "--local", "partial", partial)
    run("dvc", "push", "-q", "-r", "all-there", "kept.txt", "lost.txt")
    run("dvc", "push", "-q", "-r", "partial", "kept.txt")
    os.chdir(top)
    # With no remote, the data is named and the clone still finishes
    result, path = clone("no-remote")
    assert result.exit_code == 0, result.output
    assert "the project has no DVC remote" in result.output
    warning = result.output.split("weren't pulled")[1]
    assert "kept.txt" in warning and "lost.txt" in warning
    assert "never-run.txt" not in warning
    assert (path / "kept.txt.dvc").is_file()
    # With everything in the remote, a stage that hasn't run isn't missing
    result, path = clone("all-there", all_there)
    assert result.exit_code == 0, result.output
    assert "weren't pulled" not in result.output
    assert (path / "kept.txt").read_text() == "kept"
    assert (path / "lost.txt").read_text() == "lost"
    # What the remote does have is pulled, and only the rest is named
    result, path = clone("partial", partial)
    assert result.exit_code == 0, result.output
    assert "they aren't in the project's DVC remote" in result.output
    warning = result.output.split("weren't pulled")[1]
    assert "lost.txt" in warning and "kept.txt" not in warning
    assert (path / "kept.txt").read_text() == "kept"
    assert not (path / "lost.txt").exists()
    # A remote that can't be reached is still an error
    result, _ = clone("unreachable", "ssh://nobody@127.0.0.1:1/nothing")
    assert result.exit_code != 0
    assert "Failed to pull" in result.output


def test_clone(monkeypatch):
    from typer.testing import CliRunner

    cloned = []
    hubs = []

    def check_call(cmd, *args, **kwargs):
        # Stop at the clone, which is all that depends on the protocol
        if cmd[:2] == ["git", "clone"]:
            cloned.append(cmd[2])
            raise subprocess.CalledProcessError(1, cmd)
        raise AssertionError(cmd)

    def get(path):
        hubs.append(os.environ.get("CALKIT_HUB"))
        return {"git_repo_url": "https://github.com/me/proj"}

    def clone(*args, ssh_set_up=True):
        cloned.clear()
        hubs.clear()
        monkeypatch.delenv("CALKIT_HUB", raising=False)
        monkeypatch.setattr(
            calkit.github, "can_use_ssh", lambda interactive=False: ssh_set_up
        )
        result = CliRunner().invoke(calkit.cli.main.app, ["clone", *args])
        assert result.exit_code != 0
        return result

    def clone_url(*args, **kwargs):
        clone(*args, **kwargs)
        return cloned[0]

    # Clone sets CALKIT_HUB, so have it restored after the test
    monkeypatch.setenv("CALKIT_HUB", "")
    monkeypatch.setattr("subprocess.check_call", check_call)
    monkeypatch.setattr(calkit.hub, "get", get)
    # SSH where it's set up for GitHub, by a project's name or its URL
    assert clone_url("me/proj") == "git@github.com:me/proj.git"
    assert (
        clone_url("https://github.com/me/proj.git")
        == "git@github.com:me/proj.git"
    )
    assert clone_url("github.com/me/proj") == "git@github.com:me/proj"
    # GitHub's ssh:// form is the same URL, and another host's is kept
    assert (
        clone_url("ssh://git@github.com/me/proj.git")
        == "git@github.com:me/proj.git"
    )
    assert (
        clone_url("ssh://git@github.com/me/proj.git", "--https")
        == "https://github.com/me/proj.git"
    )
    assert (
        clone_url("ssh://git@gitlab.com/me/proj.git")
        == "ssh://git@gitlab.com/me/proj.git"
    )
    # Otherwise HTTPS, which is also what's asked for wins
    assert (
        clone_url("me/proj", ssh_set_up=False)
        == "https://github.com/me/proj.git"
    )
    assert clone_url("me/proj", "--https") == "https://github.com/me/proj.git"
    assert (
        clone_url("git@github.com:me/proj.git", "--https")
        == "https://github.com/me/proj.git"
    )
    # An SSH URL is kept without --https, even where SSH isn't set up
    assert (
        clone_url("git@github.com:me/proj.git", ssh_set_up=False)
        == "git@github.com:me/proj.git"
    )
    assert (
        clone_url("me/proj", "--ssh", ssh_set_up=False)
        == "git@github.com:me/proj.git"
    )
    # Interactively, SSH where it isn't set up offers to set it up, which
    # can end early, e.g., once GitHub's host key is trusted, then checks
    # again, or falls back to HTTPS, unless SSH was asked for
    monkeypatch.setattr(calkit.core, "is_tty", lambda: True)
    for args, answer, setup_works, url in [
        ([], "y", True, "git@github.com:me/proj.git"),
        ([], "y", False, "https://github.com/me/proj.git"),
        ([], "n", False, "https://github.com/me/proj.git"),
        (["--ssh"], "n", False, "git@github.com:me/proj.git"),
    ]:
        monkeypatch.setattr(
            calkit.github,
            "can_use_ssh",
            lambda interactive=False: interactive and setup_works,
        )
        with patch(
            "calkit.cli.config.config_github_ssh", side_effect=typer.Exit()
        ) as m_setup:
            result = CliRunner().invoke(
                calkit.cli.main.app,
                ["clone", "git@github.com:me/proj.git", *args],
                input=answer + "\n",
            )
        assert "SSH not set up" in result.output
        assert cloned[-1] == url, (args, answer, setup_works)
        assert m_setup.called is (answer == "y")
    monkeypatch.setattr(calkit.core, "is_tty", lambda: False)
    # Without Git, it's offered first
    for installed in [True, False]:
        with (
            patch("calkit.install.can_run_git", return_value=False),
            patch(
                "calkit.install.prompt_and_install", return_value=installed
            ) as m_prompt,
        ):
            clone("me/proj")
        assert m_prompt.call_args.args[0] == "git"
        assert bool(cloned) is installed
    # Another host's URL is left as given
    assert (
        clone_url("https://gitlab.com/me/proj.git")
        == "https://gitlab.com/me/proj.git"
    )
    # A project is looked up on the default hub, the one it names, or the
    # one given, and localhost is the development hub
    for args, hub in [
        (["me/proj"], None),
        (["calkit.example.edu/me/proj"], "https://calkit.example.edu"),
        (
            ["me/proj", "--hub", "calkit.example.edu"],
            "https://calkit.example.edu",
        ),
        (["localhost/me/proj"], "http://localhost:5173"),
        (["localhost:5173/me/proj"], "http://localhost:5173"),
    ]:
        clone(*args)
        assert hubs == [hub], args
    # Two different hubs, or a name that isn't one, is an error
    result = clone("a.edu/me/proj", "--hub", "b.edu")
    assert "doesn't match" in result.output and not hubs
    result = clone("a/b/c/d")
    assert "HUB/OWNER/NAME" in result.output and not hubs


def test_run_fails_naming_every_markdown_whose_values_cant_be_written(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    with open("r.json", "w") as f:
        json.dump({"v": 7}, f)
    doc = (
        "```sh calkit stage name={name} environment=_system "
        "outputs=[{{path: {name}.txt, storage: git}}]\n"
        "echo {name} > {name}.txt\n"
        "```\n"
        "\n"
        "<!-- calkit values path=r.json -->\n"
        "\n"
        "The value is <!-- calkit value key=v -->0<!-- /calkit value -->.\n"
    )
    # Sorted first, so this is the one that used to abort the whole pass
    with open("a-bad.md", "w") as f:
        f.write(doc.format(name="bad"))
    with open("b-good.md", "w") as f:
        f.write(doc.format(name="good") + "\n<!-- /calkit values -->\n")
    ck_info = {
        "pipeline": {
            "stages": {
                "bad-doc": {"kind": "markdown", "target_path": "a-bad.md"},
                "good-doc": {"kind": "markdown", "target_path": "b-good.md"},
            }
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    res = subprocess.run(
        ["calkit", "run"], capture_output=True, text=True, check=False
    )
    out = res.stdout + res.stderr
    assert res.returncode != 0, out
    assert "a-bad.md:5" in out, out
    assert "is not ended" in out, out
    # The stages themselves ran, and the document that parses was still
    # brought into line with the results file
    with open("good.txt") as f:
        assert f.read().strip() == "good"
    with open("b-good.md") as f:
        assert "-->7<!-- /calkit value -->" in f.read()


def test_run_untracks_git_tracked_outputs(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    # A figure imported, e.g., from Overleaf, before a stage made it
    with open("fig.txt", "w") as f:
        f.write("imported\n")
    subprocess.check_call(["git", "add", "fig.txt"])
    subprocess.check_call(["git", "commit", "-qm", "Import figure"])
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = {
        "stages": {
            "make": {
                "kind": "shell-command",
                "environment": "_system",
                "command": "echo made > fig.txt",
                "outputs": ["fig.txt"],
            }
        }
    }
    calkit.save_calkit_info(ck_info)
    result = subprocess.run(["calkit", "run"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Stopped tracking fig.txt with Git" in result.stdout + result.stderr
    assert not subprocess.check_output(
        ["git", "ls-files", "--", "fig.txt"], text=True
    ).strip()
    with open("fig.txt") as f:
        assert f.read() == "made\n"


@pytest.mark.xdist_group("conda")
@pytest.mark.skipif(
    sys.platform == "win32", reason="Conda environments need Windows debugging"
)
def test_xenv_conda_env_first_on_path(tmp_dir, monkeypatch):
    conda_name = "calkit-test-" + calkit.to_kebab_case(
        os.path.basename(os.getcwd())
    )
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        ["calkit", "new", "conda-env", "-n", "py", "--conda-name", conda_name]
        + ["python=3.12"]
    )
    try:
        # A program installed elsewhere and earlier on PATH, e.g., by Homebrew
        # or Pixi, doesn't win over the environment's own, even though
        # activating it puts it where Conda's base is on PATH, if there
        decoy = Path("decoy")
        decoy.mkdir()
        (decoy / "python").write_text("#!/bin/sh\necho decoy\n")
        (decoy / "python").chmod(0o755)
        monkeypatch.setenv(
            "PATH", str(decoy.absolute()) + os.pathsep + os.environ["PATH"]
        )
        out = subprocess.check_output(
            ["calkit", "xenv", "-n", "py", "--", "python", "-c"]
            + ["import sys; print(sys.prefix)"],
            text=True,
        )
        assert out.strip().splitlines()[-1].endswith(conda_name)
    finally:
        subprocess.call(
            [calkit.conda.find_conda_exe() or "conda", "env", "remove"]
            + ["-y", "-n", conda_name]
        )


def test_run_jupyter(tmp_dir):
    # Another Jupyter first on PATH, without Calkit's extensions, isn't run
    os.makedirs("other")
    fake = os.path.join("other", "jupyter-lab")
    with open(fake, "w") as f:
        f.write("#!/bin/sh\necho other\n")
    os.chmod(fake, 0o755)
    env = os.environ | {
        "PATH": os.path.abspath("other") + os.pathsep + os.environ["PATH"]
    }
    out = subprocess.run(
        ["calkit", "jupyter", "lab", "path"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert out.returncode == 0, out.stderr
    assert "other" not in out.stdout
    assert "Application directory" in out.stdout


def test_run_skips_for_failed_env(tmp_dir):
    # A stage whose environment couldn't be built is skipped rather than
    # failing with its own error, e.g., that a tool isn't in it, which
    # would hide the real one. The stages that need its outputs are skipped
    # too, the rest run, and then the run fails.
    subprocess.check_call(["calkit", "init"])
    with open("requirements.txt", "w") as f:
        f.write("./does-not-exist\n")
    ck_info = calkit.load_calkit_info()
    ck_info["environments"] = {
        "py": {
            "kind": "uv-venv",
            "path": "requirements.txt",
            "prefix": ".venv",
        }
    }
    ck_info["pipeline"] = {
        "stages": {
            "thing": {
                "kind": "shell-command",
                "environment": "py",
                "command": "echo hi > out.txt",
                "outputs": ["out.txt"],
            },
            "after": {
                "kind": "shell-command",
                "environment": "_system",
                "command": "cat out.txt > after.txt",
                "inputs": ["out.txt"],
                "outputs": ["after.txt"],
            },
            "other": {
                "kind": "shell-command",
                "environment": "_system",
                "command": "echo other > other.txt",
                "outputs": ["other.txt"],
            },
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    res = subprocess.run(["calkit", "run"], capture_output=True, text=True)
    out = res.stdout + res.stderr
    assert res.returncode != 0, out
    assert "Stage 'thing' is out of date and couldn't run" in out
    assert (
        "Failed to check environment 'py', so skipping out-of-date stage "
        "'thing'" in out
    )
    assert "calkit check env -n py" in out
    assert not os.path.exists("out.txt")
    assert not os.path.exists("after.txt")
    assert os.path.exists("other.txt")


def test_run_with_stderr_discarded(tmp_dir):
    # On Windows, NUL looks like a terminal to isatty, but Python writes to
    # it with the ANSI code page, so a spinner drawn there failed the run
    subprocess.check_call(["calkit", "init"], stdout=subprocess.DEVNULL)
    ck_info = calkit.load_calkit_info()
    ck_info["pipeline"] = {
        "stages": {
            "make": {
                "kind": "shell-command",
                "environment": "_system",
                "command": "echo made > out.txt",
                "outputs": ["out.txt"],
            }
        }
    }
    calkit.save_calkit_info(ck_info)
    for cmd in [["calkit", "run"], ["calkit", "status"]]:
        p = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        if p.returncode != 0:
            # Run again with stderr kept, to show why
            shown = subprocess.run(cmd, capture_output=True, text=True)
            raise AssertionError(p.stdout + shown.stdout + shown.stderr)
    assert os.path.isfile("out.txt")
