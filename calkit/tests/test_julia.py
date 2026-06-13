"""Tests for ``calkit.julia``"""

import os
from unittest import mock

import pytest

from calkit.julia import (
    _is_julia_command,
    check_version_in_command,
    ensure_startup_file_disabled_in_command,
    escape_string,
    get_julia_exe,
    load_path,
)


def test_escape_string_windows_path():
    # A Windows path embedded in a Julia string literal must have its
    # backslashes escaped, otherwise "C:\\Users" is read as an invalid \\U
    # unicode escape (ParseError).
    assert escape_string("C:\\Users\\peteb") == "C:\\\\Users\\\\peteb"
    # Double quotes and dollar signs are the other special characters.
    assert escape_string('a"b') == 'a\\"b'
    assert escape_string("a$b") == "a\\$b"
    # Plain values (e.g. the load path) are unchanged.
    assert escape_string("@;@stdlib") == "@;@stdlib"


def test_load_path_uses_platform_separator():
    # Julia splits JULIA_LOAD_PATH on the platform path separator, so the
    # value must use ';' on Windows and ':' elsewhere (== os.pathsep).
    assert load_path() == f"@{os.pathsep}@stdlib"
    assert "@" in load_path()
    assert "@stdlib" in load_path()


def test_get_julia_exe(monkeypatch, tmp_path):
    # Prefer julia on the PATH when present
    def which_julia(name):
        return "/usr/bin/julia" if name == "julia" else None

    monkeypatch.setattr("calkit.julia.shutil.which", which_julia)
    assert get_julia_exe() == "/usr/bin/julia"
    # When julia is absent but juliaup is installed, fall back to juliaup's
    # julialauncher (the binary the julia shim normally points to)
    juliaup_bin = tmp_path / "bin"
    juliaup_bin.mkdir()
    juliaup_path = juliaup_bin / "juliaup"
    juliaup_path.write_text("")
    launcher_path = juliaup_bin / "julialauncher"
    launcher_path.write_text("")

    def which_juliaup(name):
        return str(juliaup_path) if name == "juliaup" else None

    monkeypatch.setattr("calkit.julia.shutil.which", which_juliaup)
    assert get_julia_exe() == str(launcher_path)
    # The resolved launcher path is still accepted as a Julia command
    cmd = ensure_startup_file_disabled_in_command(
        [get_julia_exe(), "--version"]
    )
    assert cmd[0] == str(launcher_path)
    assert "--startup-file=no" in cmd
    # Neither julia nor juliaup available: fall back to a bare "julia" so the
    # caller surfaces a clear not-found error
    monkeypatch.setattr("calkit.julia.shutil.which", lambda name: None)
    assert get_julia_exe() == "julia"


def test_is_julia_command_case_insensitive():
    # Windows resolves the execution-alias shim to an uppercase extension
    # (e.g. ``julia.EXE``); the check must still recognize it.
    assert _is_julia_command("C:/x/julia.EXE")
    assert _is_julia_command("C:/x/Julia.Exe")
    assert _is_julia_command("C:/x/julialauncher.EXE")
    assert _is_julia_command("/usr/bin/julia")
    assert _is_julia_command("julialauncher")
    assert not _is_julia_command("python")
    assert not _is_julia_command("C:/x/python.exe")


def test_disable_startup_file_accepts_uppercase_exe():
    # Regression: julia.EXE (Windows execution alias) was rejected as not a
    # Julia command, failing the env check and masking real pipeline status.
    cmd = ensure_startup_file_disabled_in_command(
        ["C:/x/julia.EXE", "--version"]
    )
    assert cmd[0] == "C:/x/julia.EXE"
    assert "--startup-file=no" in cmd


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


def test_disable_startup_file_removes_conflicting_startup_file_yes():
    """Test that existing --startup-file=yes is removed and replaced."""
    cmd = ["julia", "--startup-file=yes", "--project", "whatever"]
    updated = ensure_startup_file_disabled_in_command(cmd)
    assert "--startup-file=yes" not in updated
    assert "--startup-file=no" in updated
    assert updated == [
        "julia",
        "--startup-file=no",
        "--project",
        "whatever",
    ]


def test_disable_startup_file_removes_conflicting_startup_file_with_version():
    """Test removal works when version specifier and conflicting flag present."""
    cmd = ["julia", "+1.11", "--startup-file=yes", "--project", "whatever"]
    updated = ensure_startup_file_disabled_in_command(cmd)
    assert "--startup-file=yes" not in updated
    assert updated == [
        "julia",
        "+1.11",
        "--startup-file=no",
        "--project",
        "whatever",
    ]
