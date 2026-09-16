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
        "get_calkit_token": lambda: "token" if installed else "",
        "get_projects": list,
        "run_in_git_bash": missing,
        "run_in_powershell": missing,
    }


def test_main_window_builds_and_refreshes_offscreen(app):
    # A bare machine: every install step shows its install button
    with mock.patch.multiple("main", **_stubs(installed=False)):
        window = main.MainWindow()
        steps = window.setup_step_widgets
        install_steps = [
            s for s in steps.values() if isinstance(s, main.DependencyInstall)
        ]
        assert {"git", "docker", "uv", "calkit", "vscode"} <= set(steps)
        assert install_steps
        assert all(s.install_button is not None for s in install_steps)
        # Steps that depend on another are disabled until it's installed
        assert not steps["calkit"].isEnabled()
        assert not steps["vscode-extensions"].isEnabled()
    # A set-up machine: refreshing clears the buttons and enables the rest
    with mock.patch.multiple("main", **_stubs(installed=True)):
        window.refresh_setup_status()
        assert all(s.install_button is None for s in install_steps)
        assert steps["calkit"].isEnabled()
        assert steps["vscode-extensions"].isEnabled()
    # An installed but outdated Calkit asks for an update, not an install
    with mock.patch.multiple(
        "main",
        **{**_stubs(installed=True), "get_calkit_version": lambda: (0, 0, 1)},
    ):
        window.refresh_setup_status()
        assert steps["calkit"].install_button is not None
        assert "Update Calkit" in steps["calkit"].label.text()
        assert "--upgrade" in steps["calkit"].install_command
    # Platform-specific steps only appear where they apply
    with mock.patch.multiple("main", **_stubs(installed=False)):
        with mock.patch("main.get_platform", return_value="mac"):
            assert "homebrew" in main.make_setup_step_widgets()
        with mock.patch("main.get_platform", return_value="windows"):
            assert "wsl" in main.make_setup_step_widgets()
        with mock.patch("main.get_platform", return_value="linux"):
            linux_steps = main.make_setup_step_widgets()
            assert "homebrew" not in linux_steps and "wsl" not in linux_steps
