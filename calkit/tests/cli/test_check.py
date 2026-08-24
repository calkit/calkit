"""Tests for ``calkit.cli.check``."""

import os
import shutil
import socket
import subprocess
import sys

import pytest

import calkit


def test_check_venv(tmp_dir):
    with open("reqs.txt", "w") as f:
        f.write("requests")
    subprocess.check_call(
        ["calkit", "check", "venv", "reqs.txt", "-o", "lock.txt"]
    )
    # Now check that we can install from the lock file
    shutil.rmtree(".venv")
    subprocess.check_call(
        ["calkit", "check", "venv", "reqs.txt", "-o", "lock.txt"]
    )
    with open("lock.txt") as f:
        lock_txt = f.read()
    # Now check that if we add a requirement, the env is rebuilt
    assert "polars" not in lock_txt
    with open("reqs.txt", "w") as f:
        f.write("requests\npolars")
    subprocess.check_call(
        ["calkit", "check", "venv", "reqs.txt", "-o", "lock.txt"]
    )
    with open("lock.txt") as f:
        lock_txt = f.read()
    assert "polars" in lock_txt
    # Now confirm that if we check the env again, nothing happens
    subprocess.check_call(
        ["calkit", "check", "venv", "reqs.txt", "-o", "lock.txt"]
    )
    with open("lock.txt") as f:
        lock_txt_2 = f.read()
    assert lock_txt == lock_txt_2
    # Now check that if we pin a version in reqs.txt, we rebuild
    with open("reqs.txt", "w") as f:
        f.write("requests\npolars==1.0.0")
    subprocess.check_call(
        ["calkit", "check", "venv", "reqs.txt", "-o", "lock.txt"]
    )
    with open("lock.txt") as f:
        lock_txt_3 = f.read()
    assert "polars==1.0.0" in lock_txt_3
    # Test that if we specify a different Python or otherwise fail with an
    # existing prefix, we can still build the environment since it will be
    # deleted and recreated
    subprocess.check_call(
        [
            "calkit",
            "check",
            "venv",
            "reqs.txt",
            "-o",
            "lock.txt",
            "--python",
            "3.11",
        ]
    )


def test_check_venv_moved(tmp_dir):
    with open("reqs.txt", "w") as f:
        f.write("requests")
    subprocess.check_call(
        ["calkit", "check", "venv", "reqs.txt", "-o", "lock.txt"]
    )
    # Simulate the project having been renamed, which leaves the old absolute
    # path baked into the activate script
    if sys.platform == "win32":
        activate_fpath = os.path.join(".venv", "Scripts", "activate.bat")
    else:
        activate_fpath = os.path.join(".venv", "bin", "activate")
    with open(activate_fpath) as f:
        activate_txt = f.read()
    prefix = os.path.abspath(".venv")
    assert prefix in activate_txt
    with open(activate_fpath, "w") as f:
        f.write(activate_txt.replace(prefix, os.path.abspath("old-name")))
    subprocess.check_call(
        ["calkit", "check", "venv", "reqs.txt", "-o", "lock.txt"]
    )
    with open(activate_fpath) as f:
        assert os.path.normcase(prefix) in os.path.normcase(f.read())
    # Activating should now resolve to the env's own Python, which is what
    # breaks when the path is stale
    if sys.platform == "win32":
        cmd = f'call "{activate_fpath}" && python -c "import requests"'
    else:
        cmd = f". \"{activate_fpath}\" && python -c 'import requests'"
    subprocess.check_call(cmd, shell=True)


def test_check_env_vars(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    ck_info = {
        "dependencies": [
            {"name": "MY_ENV_VAR", "kind": "env-var"},
            {"name": "MY_APP", "kind": "app"},
            "something-else",
            {"MY_OTHER_ENV_VAR": {"kind": "env-var"}},
        ]
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(
        ["calkit", "check", "env-vars"],
        env=os.environ.copy()
        | {"MY_ENV_VAR": "value1", "MY_OTHER_ENV_VAR": "value2"},
    )
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(
            ["calkit", "check", "env-vars"],
            env=os.environ.copy() | {"MY_ENV_VAR": "value1"},
        )


@pytest.mark.skipif(
    shutil.which("julia") is None, reason="Julia not installed"
)
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Julia env init fails on Windows GHA runners (Pkg stdlib missing)",
)
def test_check_julia_env_caches_second_run(tmp_dir):
    """Second run of ``calkit check julia-env`` should skip Pkg.instantiate."""
    with open("Project.toml", "w") as f:
        f.write('[deps]\n\n[compat]\njulia = "1"\n')
    # The cache includes a signature of the Julia depot, so another test
    # installing packages into the shared depot while this one runs would
    # invalidate it. Write to our own depot, keeping the shared one on the
    # path so packages and registries in it can still be read.
    depot = os.path.join(os.getcwd(), "julia-depot")
    os.makedirs(depot, exist_ok=True)
    env = os.environ.copy() | {
        "JULIA_DEPOT_PATH": os.pathsep.join(
            [depot, os.path.join(os.path.expanduser("~"), ".julia")]
        )
    }
    # First run — should actually call Pkg.instantiate
    result1 = subprocess.run(
        ["calkit", "check", "julia-env", "Project.toml", "--verbose"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert "skipping Pkg.instantiate" not in result1.stdout
    # Second run — nothing has changed, so instantiate should be skipped
    result2 = subprocess.run(
        ["calkit", "check", "julia-env", "Project.toml", "--verbose"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert "skipping Pkg.instantiate" in result2.stdout
    # Modify Project.toml — cache should be invalidated
    with open("Project.toml", "a") as f:
        f.write("# touched\n")
    result3 = subprocess.run(
        ["calkit", "check", "julia-env", "Project.toml", "--verbose"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert "skipping Pkg.instantiate" not in result3.stdout


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: Docker daemon not available on windows-latest GHA runners",
)
def test_check_docker_env(tmp_dir):
    # First create a Dockerfile with a known base image
    with open("Dockerfile", "w") as f:
        f.write("FROM python:3.9-slim\n")
    # Now check the environment
    subprocess.check_call(
        [
            "calkit",
            "check",
            "docker-env",
            "python-3.9-slim",
            "-i",
            "Dockerfile",
            "-o",
            "Dockerfile-lock.json",
        ]
    )
    # Now modify the image to fail to build and ensure the lock file is deleted
    with open("Dockerfile", "w") as f:
        f.write("FROM non-existent-image:latest\n")
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(
            [
                "calkit",
                "check",
                "docker-env",
                "python-3.9-slim",
                "-i",
                "Dockerfile",
                "-o",
                "Dockerfile-lock.json",
            ]
        )
    assert not os.path.exists("Dockerfile-lock.json")


def test_check_env_rejects_an_invalid_lock_property(tmp_dir):
    # A misspelled property is the user's mistake to fix, so it has to say
    # what was wrong and fail. It used to escape the local branch as a
    # traceback, and 'check envs' then reported the exit code in place of
    # the reason -- leaving a warning that said '1'.
    subprocess.check_call(["calkit", "init"])
    ck_info = calkit.load_calkit_info()
    ck_info["environments"] = {
        "laptop": {
            "kind": "system",
            "host": socket.gethostname(),
            "lock": ["python", "os"],
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    for argv in (
        ["calkit", "check", "env", "-n", "laptop"],
        ["calkit", "check", "envs"],
    ):
        proc = subprocess.run(argv, capture_output=True, text=True)
        assert proc.returncode != 0, argv
        combined = proc.stdout + proc.stderr
        assert "Unknown system property to lock: 'python'" in combined, argv
        # The valid options are listed, since knowing the name is wrong
        # doesn't tell anyone what the right one is
        assert "python-version" in combined, argv
        assert "Traceback" not in combined, argv
    # Nothing is recorded for an environment that couldn't be locked, so a
    # stage can't depend on a half-written pin
    assert not os.path.exists(os.path.join(".calkit", "env-locks", "laptop"))


def test_check_env_checks_system_requirements(tmp_dir):
    # A system env's requirements gate the machine it names, and are
    # checked before its lock is written, so a machine that doesn't meet
    # them never has its properties recorded as what results depend on
    subprocess.check_call(["calkit", "init"])
    ck_info = calkit.load_calkit_info()
    ck_info["environments"] = {
        "laptop": {
            "kind": "system",
            "host": socket.gethostname(),
            "requirements": [{"kind": "cpu-count", "min": 10000}],
            "lock": ["os"],
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    proc = subprocess.run(
        ["calkit", "check", "env", "-n", "laptop"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "cpu-count" in combined
    assert "Environment 'laptop'" in combined
    assert "Traceback" not in combined
    lock_fpath = os.path.join(".calkit", "env-locks", "laptop", "info.json")
    assert not os.path.exists(lock_fpath)
    # Met requirements let the check proceed to writing the lock
    ck_info["environments"]["laptop"]["requirements"] = [
        {"kind": "cpu-count", "min": 1}
    ]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["calkit", "check", "env", "-n", "laptop"])
    assert os.path.exists(lock_fpath)


def test_check_envs_preloads_env_vars(tmp_dir, monkeypatch):
    # Verify that `calkit check envs` loads .env and calkit.yaml env_vars
    # before checking environments, so env-var-gated checks see them.
    # The environment uses $CALKIT_VAR as its path so the check fails if
    # the env var isn't preloaded before check_environment is called.
    subprocess.check_call(["calkit", "init"])
    with open(".env", "w") as f:
        f.write("DOT_ENV_VAR=from_dotenv\n")
    ck_info = calkit.load_calkit_info()
    # CALKIT_VAR holds the requirements file path; it is set via env_vars so
    # check envs must preload it before the venv check can resolve $CALKIT_VAR
    ck_info["env_vars"] = {"CALKIT_VAR": "requirements.txt"}
    ck_info["environments"] = {
        "test-env": {
            "kind": "uv-venv",
            "path": "$CALKIT_VAR",
            "prefix": ".venv",
            "python": "3.13",
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open("requirements.txt", "w") as f:
        f.write("requests\n")
    # Ensure vars are NOT already in the environment so only preloading sets them
    monkeypatch.delenv("DOT_ENV_VAR", raising=False)
    monkeypatch.delenv("CALKIT_VAR", raising=False)
    # Should succeed: check envs preloads CALKIT_VAR → path resolves to
    # requirements.txt; without preloading $CALKIT_VAR would not resolve
    subprocess.check_call(["calkit", "check", "envs"])
