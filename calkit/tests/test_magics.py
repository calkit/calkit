"""Tests for ``calkit.magics``."""

import subprocess

def test_stage(tmp_dir):
    # Test the stage magic
    # Run git and dvc init in the temp dir
    subprocess.check_call(["git", "init"])
    subprocess.check_call(["dvc", "init"])
    # TODO: Copy in a test notebook and run it
    pass
