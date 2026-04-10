"""Tests for ``calkit.cli.check``."""

import os
import shutil
import subprocess

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
def test_check_julia_env_caches_second_run(tmp_dir):
    """Second run of ``calkit check julia-env`` should skip Pkg.instantiate."""
    with open("Project.toml", "w") as f:
        f.write('[deps]\n\n[compat]\njulia = "1"\n')
    # First run — should actually call Pkg.instantiate
    result1 = subprocess.run(
        ["calkit", "check", "julia-env", "Project.toml", "--verbose"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "skipping Pkg.instantiate" not in result1.stdout
    # Second run — nothing has changed, so instantiate should be skipped
    result2 = subprocess.run(
        ["calkit", "check", "julia-env", "Project.toml", "--verbose"],
        capture_output=True,
        text=True,
        check=True,
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
    )
    assert "skipping Pkg.instantiate" not in result3.stdout
