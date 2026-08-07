"""Tests for the ``core`` module."""

import subprocess

from app.core import read_last_line_from_csv


def test_read_last_line_from_csv(tmp_dir):
    subprocess.check_call(
        ["git", "config", "--global", "user.name", "CI Test"]
    )
    subprocess.check_call(
        ["git", "config", "--global", "user.email", "ci-test@example.com"]
    )
    subprocess.check_call(["calkit", "init"])
    subprocess.check_call(
        ["calkit", "new", "status", "completed", "-m", "This is the status."]
    )
    last_line = read_last_line_from_csv(".calkit/status.csv")
    assert last_line[1] == "completed"
    assert last_line[-1] == "This is the status."
