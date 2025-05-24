"""Tests for ``calkit.check``."""

import os
import subprocess
import sys

from calkit.check import check_reproducibility


def test_check_reproducibility(tmp_path):
    os.chdir(tmp_path)
    res = check_reproducibility()
    assert not res.is_git_repo
    subprocess.run(["git", "init"])
    res = check_reproducibility()
    assert res.is_git_repo
    assert not res.is_dvc_repo
    assert not res.has_readme
    assert "no README.md" in res.recommendation
    subprocess.run([sys.executable, "-m", "dvc", "init"])
    res = check_reproducibility()
    assert res.is_dvc_repo
    assert res.n_dvc_remotes == 0
    assert not res.has_calkit_info
    assert not res.has_dev_container
    assert not res.has_pipeline
    print(res.to_pretty())
    with open("README.md", "w") as f:
        f.write("Simply execute `calkit run` to reproduce.")
    res = check_reproducibility()
    assert res.has_readme
    assert res.instructions_in_readme


def test_check_call():
    out = (
        subprocess.check_output(
            ["calkit", "check", "call", "echo sup", "--if-error", "echo yo"]
        )
        .decode()
        .strip()
        .split("\n")
    )
    out = [v.strip() for v in out]
    assert "sup" in out
    assert "yo" not in out
    out = (
        subprocess.check_output(
            ["calkit", "check", "call", "sup", "--if-error", "echo yo"]
        )
        .decode()
        .strip()
        .split("\n")
    )
    out = [v.strip() for v in out]
    assert "yo" in out
