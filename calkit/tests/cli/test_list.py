"""Tests for ``cli.list``."""

import subprocess


def test_list_environments(tmp_dir):
    subprocess.check_call("calkit list environments", shell=True)
    # TODO: Create some environments
