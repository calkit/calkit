"""Tests for ``cli.update``."""

import subprocess


def test_update_environment(tmp_dir):
    # Test we can update an environment
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        ["calkit", "new", "julia-env", "-n", "main", "--julia", "1.11"]
    )
    subprocess.check_call(
        [
            "calkit",
            "update",
            "env",
            "-n",
            "main",
            "--add",
            "IJulia",
        ]
    )
