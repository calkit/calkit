"""Tests for ``calkit.julia``"""

from unittest import mock

import pytest

from calkit.julia import (
    check_version_in_command,
    ensure_startup_file_disabled_in_command,
)


def test_check_version_in_command():
    cmd = ["julia", "+1.11", "--project", "whatever"]
    # Case 1: juliaup is available
    # The +version specifier should be preserved
    with mock.patch(
        "calkit.julia.shutil.which", return_value="/usr/bin/juliaup"
    ):
        cmd_with_juliaup = check_version_in_command(cmd.copy())
        assert "+1.11" in cmd_with_juliaup
    # Case 2: juliaup is not available
    # check_version_in_command will fall back to invoking `julia --version`
    # Mock this so the test does not depend
    # on a real Julia installation and assert that the +version is stripped
    mock_completed = mock.Mock()
    mock_completed.returncode = 0
    mock_completed.stdout = "julia version 1.11.0\n"
    with (
        mock.patch("calkit.julia.shutil.which", return_value=None),
        mock.patch("calkit.julia.subprocess.run", return_value=mock_completed),
    ):
        cmd_without_juliaup = check_version_in_command(cmd.copy())
        assert "+1.11" not in cmd_without_juliaup
        # Ensure the base julia command is still present.
        assert "julia" in cmd_without_juliaup


def test_disable_startup_file_with_version_flag():
    cmd = ["julia", "+1.11", "--project", "whatever"]
    updated = ensure_startup_file_disabled_in_command(cmd)
    assert updated == [
        "julia",
        "+1.11",
        "--startup-file=no",
        "--project",
        "whatever",
    ]


def test_disable_startup_file_without_version_flag():
    cmd = ["julia", "--project", "whatever"]
    updated = ensure_startup_file_disabled_in_command(cmd)
    assert updated == [
        "julia",
        "--startup-file=no",
        "--project",
        "whatever",
    ]


def test_disable_startup_file_idempotent():
    cmd = ["julia", "--startup-file=no", "--project", "whatever"]
    assert ensure_startup_file_disabled_in_command(cmd) == cmd


def test_disable_startup_file_non_julia_raises():
    with pytest.raises(ValueError, match="Julia command"):
        ensure_startup_file_disabled_in_command(["python", "-V"])
