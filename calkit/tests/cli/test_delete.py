"""Tests for ``cli.delete``."""

import subprocess

import pytest

import calkit


def test_rm_question(tmp_dir):
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(["calkit", "new", "question", "First question?"])
    subprocess.check_call(["calkit", "new", "question", "Second question?"])
    assert calkit.load_calkit_info()["questions"] == [
        "First question?",
        "Second question?",
    ]
    # Remove the first (1-indexed)
    subprocess.check_call(["calkit", "rm", "question", "1"])
    assert calkit.load_calkit_info()["questions"] == ["Second question?"]
    # Out-of-range index fails
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_call(["calkit", "rm", "question", "5"])
