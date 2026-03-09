"""Tests for ``calkit.julia``"""

from unittest import mock

from calkit.julia import check_version_in_command


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
