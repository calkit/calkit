"""Tests for ``cli.new``."""

import os
import subprocess


def test_new_foreach_stage(tmp_dir):
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["dvc", "init"])
    subprocess.check_call(
        [
            "calkit",
            "new",
            "foreach-stage",
            "-n",
            "stage1",
            "--cmd",
            "echo {var} > {var}.txt",
            "--out",
            "{var}.txt",
            "one",
            "two",
            "three",
        ]
    )
    subprocess.check_call(["calkit", "run"])
    assert os.path.isfile("one.txt")
    # Add another stage that depends on one of these outputs
    subprocess.check_call(
        [
            "calkit",
            "new",
            "foreach-stage",
            "-n",
            "stage2",
            "--cmd",
            "cat {var}.txt > {var}-2.txt",
            "--out",
            "{var}-2.txt",
            "--dep",
            "{var}.txt",
            "one",
            "two",
            "three",
        ]
    )
    subprocess.check_call(["calkit", "run"])
    assert os.path.isfile("two-2.txt")
