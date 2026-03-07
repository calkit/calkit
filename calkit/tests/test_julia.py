"""Tests for ``calkit.julia``"""

import shutil

from calkit.julia import check_version_in_command


def test_check_version_in_command():
    cmd = ["julia", "+1.11", "--project", "whatever"]
    cmd1 = check_version_in_command(cmd)
    juliaup_available = shutil.which("juliaup") is not None
    if juliaup_available:
        assert "+1.11" in cmd1
    # Simulate juliaup not being available
