"""Smoke tests for the assistant's window, run offscreen."""

from __future__ import annotations

import os
import sys
from unittest import mock

import pytest

# Must be set before Qt is imported, so the window renders without a display
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import main


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _stubs(installed: bool) -> dict:
    # Everything that would shell out or hit the network, answered as if
    # the machine were fully set up or completely bare
    def missing(*args, **kwargs):
        raise FileNotFoundError

    return {
        "check_dep_exists": lambda name: installed,
        "wsl_installed": lambda: installed,
        "vs_code_installed": lambda: installed,
        "get_installed_vs_code_extensions": lambda: (
            list(main.VSCodeExtensionsInstall.recommended) if installed else []
        ),
        "find_conda_prefix": lambda: "/opt/conda" if installed else "",
        "get_calkit_version": lambda: (99, 0, 0) if installed else None,
        "get_latest_calkit_version": lambda: (99, 0, 0),
        "get_calkit_token": lambda: "token" if installed else "",
        "get_projects": list,
        "run_in_git_bash": missing,
        "run_in_powershell": missing,
    }


def _check_setup(window, refresh: bool = True) -> None:
    from PySide6.QtWidgets import QApplication

    # The checks run on threads and report back through queued signals
    if refresh:
        window.refresh_setup_status()
    window.setup_check_thread.wait()
    window.projects_widget.load_thread.wait()
    QApplication.processEvents()


def test_main_window_builds_and_refreshes_offscreen(app):
    # A bare machine: every install step shows its install button
    with mock.patch.multiple("main", **_stubs(installed=False)):
        window = main.MainWindow()
        steps = window.setup_step_widgets
        # The window is built before anything is checked, which happens
        # in the background behind a progress bar
        assert "⏳" in steps["git"].label.text()
        assert not window.setup_progress.isHidden()
        assert not window.refresh_setup_button.isEnabled()
        _check_setup(window, refresh=False)
        assert window.setup_progress.isHidden()
        assert window.refresh_setup_button.isEnabled()
        assert window.setup_progress.value() == len(steps)
        install_steps = [
            s for s in steps.values() if isinstance(s, main.DependencyInstall)
        ]
        assert {"git", "docker", "uv", "calkit", "vscode"} <= set(steps)
        # Logging in defers to the CLI's device flow rather than a pasted
        # token
        assert steps["hub-login"].login_command == ["calkit", "hub", "login"]
        assert "❌" in steps["hub-login"].label.text()
        assert install_steps
        assert all(s.install_button is not None for s in install_steps)
        # Steps that depend on another are disabled until it's installed
        assert not steps["calkit"].isEnabled()
        assert not steps["vscode-extensions"].isEnabled()
    # A set-up machine: refreshing clears the buttons and enables the rest
    with mock.patch.multiple("main", **_stubs(installed=True)):
        _check_setup(window)
        assert all(s.install_button is None for s in install_steps)
        assert steps["calkit"].isEnabled()
        assert steps["vscode-extensions"].isEnabled()
    # An installed but outdated Calkit asks for an update, not an install
    with mock.patch.multiple(
        "main",
        **{**_stubs(installed=True), "get_calkit_version": lambda: (0, 0, 1)},
    ):
        _check_setup(window)
        assert steps["calkit"].install_button is not None
        assert "Update Calkit" in steps["calkit"].label.text()
        assert steps["calkit"].install_command == ["calkit", "upgrade"]
    # A usable Calkit behind the latest release suggests updating, without
    # blocking the steps that depend on it
    with mock.patch.multiple(
        "main",
        **{**_stubs(installed=True), "get_calkit_version": lambda: (98, 0)},
    ):
        _check_setup(window)
        assert steps["calkit"].install_button is not None
        assert steps["calkit"].install_button.toolTip() == "Update"
        assert "✅ (v99.0.0 available)" in steps["calkit"].label.text()
        assert steps["hub-login"].isEnabled()
        assert steps["calkit"].install_command == ["calkit", "upgrade"]
    with mock.patch.multiple("main", **_stubs(installed=True)):
        _check_setup(window)
        assert steps["calkit"].install_button is None
    with mock.patch.multiple("main", **_stubs(installed=False)):
        assert steps["calkit"].install_command[:3] == ["uv", "tool", "install"]
    # Platform-specific steps only appear where they apply
    with mock.patch.multiple("main", **_stubs(installed=False)):
        with mock.patch("main.get_platform", return_value="mac"):
            assert "homebrew" in main.make_setup_step_widgets()
        with mock.patch("main.get_platform", return_value="windows"):
            assert "wsl" in main.make_setup_step_widgets()
        with mock.patch("main.get_platform", return_value="linux"):
            linux_steps = main.make_setup_step_widgets()
            assert "homebrew" not in linux_steps and "wsl" not in linux_steps
            # Git has no installer on Linux, so clicking explains rather
            # than crashing
            with mock.patch("main.QMessageBox.information") as m_info:
                assert linux_steps["git"].install() is False
            assert "package manager" in m_info.call_args.args[2]
    # A machine without WSL at all reports it as missing
    with mock.patch(
        "main.subprocess.check_output", side_effect=FileNotFoundError
    ):
        assert main.wsl_installed() is False
    # WSL without a distribution fails to list, but any distribution counts,
    # whatever its name, read from wsl.exe's UTF-16 output
    with mock.patch(
        "main.subprocess.check_output",
        side_effect=main.subprocess.CalledProcessError(1, "wsl"),
    ):
        assert main.wsl_installed() is False
    with mock.patch(
        "main.subprocess.check_output",
        return_value="Ubuntu-24.04\r\n".encode("utf-16"),
    ):
        assert main.wsl_installed() is True
    # The WSL install elevates as a whole, including the winget install
    with mock.patch.multiple("main", **_stubs(installed=False)):
        cmd = main.WSLInstall().install_command
    assert cmd[0] == "powershell" and "runAs" in cmd
    assert cmd[-1].startswith('"/k winget install')
