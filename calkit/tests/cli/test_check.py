"""Tests for ``calkit.cli.check``."""

import shutil
import subprocess


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
