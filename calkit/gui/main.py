"""A GUI to help users manage their system.

This app helps install and track system-wide dependencies and open projects
in their editor of choice.
"""

import subprocess
import sys
import webbrowser
from abc import ABC, ABCMeta, abstractmethod
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import calkit


def git_installed() -> bool:
    return calkit.check_dep_exists("git")


def git_user_name() -> str:
    return (
        subprocess.check_output(["git", "config", "user.name"])
        .decode()
        .strip()
    )


def git_email() -> str:
    return (
        subprocess.check_output(["git", "config", "user.email"])
        .decode()
        .strip()
    )


def get_platform() -> Literal["linux", "mac", "windows"]:
    """Get the platform name."""
    if sys.platform.startswith("linux"):
        return "linux"
    elif sys.platform.startswith("darwin"):
        return "mac"
    elif sys.platform.startswith("win"):
        return "windows"
    else:
        raise ValueError("Unsupported platform")


def make_setup_step_layout(widget: QWidget) -> QHBoxLayout:
    layout = QHBoxLayout(widget)
    layout.setAlignment(Qt.AlignTop)
    layout.setSpacing(0)
    layout.setContentsMargins(0, 0, 0, 0)
    return layout


class CalkitToken(QWidget):
    """A widget to set the Calkit token."""

    def __init__(self):
        super().__init__()
        self.config = calkit.config.read()
        self.txt_not_set = "Set Calkit Cloud API token:  ❌ "
        self.txt_set = "Set Calkit Cloud API token:  ✅ "
        self.label = QLabel(
            self.txt_set if self.config.token is not None else self.txt_not_set
        )
        self.fix_button = QPushButton(
            "Set" if self.config.token is None else "Update"
        )
        self.fix_button.setStyleSheet("font-size: 10px;")
        self.layout = make_setup_step_layout(self)
        self.fix_button.clicked.connect(self.open_dialog)
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.fix_button)

    def open_dialog(self):
        webbrowser.open("https://calkit.io/settings?tab=tokens")
        text, ok = QInputDialog.getText(
            self,
            "Set Calkit Cloud API token",
            "Enter API token created at calkit.io/settings:",
            echo=QLineEdit.Password,
        )
        if ok and text:
            self.config.token = text
            self.config.write()
            self.label.setText(self.txt_set)
            self.fix_button.setText("Update")


class QWidgetABCMeta(ABCMeta, type(QWidget)):
    pass


class DependencyInstall(QWidget, metaclass=QWidgetABCMeta):
    """An abstract base class to represent an installed dependency."""

    def __init__(self):
        super().__init__()
        self.layout = make_setup_step_layout(self)
        self.txt_installed = f"Install {self.dependency_name}:  ✅ "
        self.txt_not_installed = f"Install {self.dependency_name}:  ❌ "
        installed = self.installed
        self.label = QLabel(
            self.txt_installed if installed else self.txt_not_installed
        )
        self.layout.addWidget(self.label)
        if not installed:
            self.install_button = QPushButton("Install")
            self.install_button.setStyleSheet("font-size: 10px;")
            self.install_button.clicked.connect(self._install)
            self.layout.addWidget(self.install_button)

    @property
    @abstractmethod
    def dependency_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def installed(self) -> bool:
        """Return a bool indicating if the dependency is installed."""
        raise NotImplementedError

    @abstractmethod
    def install(self) -> bool:
        """Install the app, returning a bool indicating success."""
        raise NotImplementedError

    def _install(self) -> None:
        """Run the full install process."""
        # Disable install button
        self.install_button.setEnabled(False)
        # Show loading message
        self.install_button.setText("Installing...")
        success = self.install()
        # Check if this was successful
        if success:
            self.layout.removeWidget(self.install_button)
            self.install_button.deleteLater()
            self.install_button = None
            # Update label to show installed
            self.label.setText(self.txt_installed)
        else:
            print("Failed")
            # TODO: Show error message to user


class HomebrewInstall(DependencyInstall):
    """A widget to check for and install Homebrew."""

    @property
    def dependency_name(self) -> str:
        return "Homebrew"

    @property
    def installed(self) -> bool:
        return calkit.check_dep_exists("brew")

    def install(self) -> bool:
        subprocess.run(
            [
                "/bin/bash",
                "-c",
                (
                    "$(curl -fsSL https://raw.githubusercontent.com/"
                    "Homebrew/install/HEAD/install.sh)"
                ),
            ]
        )
        return subprocess.returncode == 0


class ChocolateyInstall(DependencyInstall):
    """A widget to check for and install Chocolatey."""

    @property
    def dependency_name(self) -> str:
        return "Chocolatey"

    @property
    def installed(self) -> bool:
        return calkit.check_dep_exists("choco")

    def install(self) -> bool:
        cmd = (
            "Set-ExecutionPolicy Bypass -Scope Process -Force; "
            "[System.Net.ServicePointManager]::SecurityProtocol = "
            "[System.Net.ServicePointManager]::SecurityProtocol -bor 3072; "
            "iex ((New-Object System.Net.WebClient).DownloadString("
            "'https://community.chocolatey.org/install.ps1'))"
        )
        process = subprocess.run(
            [
                "powershell",
                "-Command",
                "Start-Process",
                "powershell",
                "-Verb",
                "runAs",
                "-ArgumentList",
                f"'{cmd}'",
            ],
            capture_output=True,
            text=True,
        )
        return process.returncode == 0


class WSLInstall(DependencyInstall):
    """A widget to check for and install WSL on Windows."""

    @property
    def dependency_name(self) -> str:
        return "WSL"

    @property
    def installed(self) -> bool:
        output = subprocess.check_output(["wsl", "--status"]).decode()
        return (
            "Default Version: 2" in output
            and "Default Distribution: Ubuntu" in output
            and "not supported" not in output
        )

    def install(self) -> bool:
        # Run command as administrator in PowerShell
        cmd = "wsl --install -d Ubuntu"
        process = subprocess.run(
            [
                "powershell",
                "-Command",
                "Start-Process",
                "powershell",
                "-Verb",
                "runAs",
                "-ArgumentList",
                f"'{cmd}'",
            ],
            capture_output=True,
            text=True,
        )
        return process.returncode == 0


class CondaInstall(DependencyInstall):
    @property
    def dependency_name(self) -> str:
        return "Conda"

    @property
    def installed(self) -> bool:
        return calkit.check_dep_exists("conda")

    def install(self) -> bool:
        """Install Conda."""
        # First check our platform and download the installer
        # Run the installer
        raise NotImplementedError


class DockerInstall(DependencyInstall):
    @property
    def dependency_name(self) -> str:
        return "Docker"

    @property
    def installed(self) -> bool:
        return calkit.check_dep_exists("docker")

    def install(self) -> bool:
        # TODO
        raise NotImplementedError


class VSCodeInstall(DependencyInstall):
    @property
    def dependency_name(self) -> str:
        return "VS Code"

    @property
    def installed(self) -> bool:
        return calkit.check_dep_exists("code")

    def install(self) -> bool:
        """Install VS Code."""
        # First check our platform and download the installer
        # Run the installer
        raise NotImplementedError


class PackageManagerInstallWidget(QWidget):
    """A widget to check for and install an app with the system package
    manager.
    """

    def __init__(
        self,
        app_name: str,
        app_title: str,
        child_steps: list[QWidget] = [],
    ):
        super().__init__()
        self.child_steps = child_steps
        self.layout = make_setup_step_layout(self)
        self.app_name = app_name
        self.app_title = app_title
        self.txt_installed = f"Install {self.app_title}:  ✅ "
        self.txt_not_installed = f"Install {self.app_title}:  ❌ "
        installed = calkit.check_dep_exists(self.app_name)
        for step in child_steps:
            step.setEnabled(installed)
        self.label = QLabel(
            self.txt_installed if installed else self.txt_not_installed
        )
        self.layout.addWidget(self.label)
        if not installed:
            self.install_button = QPushButton("Install")
            self.install_button.setStyleSheet("font-size: 10px;")
            self.install_button.clicked.connect(self.install)
            self.layout.addWidget(self.install_button)
            platform = get_platform()
            if platform == "windows" and not calkit.check_dep_exists("choco"):
                self.install_button.setEnabled(False)
                self.install_button.setToolTip(
                    "Chocolatey must be installed first"
                )
            elif platform == "mac" and not calkit.check_dep_exists("brew"):
                self.install_button.setEnabled(False)
                self.install_button.setToolTip(
                    "Homebrew must be installed first"
                )
            elif platform == "linux" and not calkit.check_dep_exists("apt"):
                self.install_button.setEnabled(False)
                self.install_button.setToolTip("APT must be installed")

    def install(self):
        # Disable install button
        self.install_button.setEnabled(False)
        # Show loading message
        self.install_button.setText("Installing...")
        if get_platform() == "windows":
            # Use Chocolatey to install Git
            process = subprocess.run(["choco", "install", self.app_name])
        elif get_platform() == "mac":
            process = subprocess.run(["brew", "install", self.app_name])
        elif get_platform() == "linux":
            # Use apt to install Git
            cmd = f"apt install {self.app_name}"
            process = subprocess.run(["pkexec", "sh", "-c", cmd])
        if process.returncode == 0:
            self.layout.removeWidget(self.install_button)
            self.install_button.deleteLater()
            self.install_button = None
            # Update label to show installed
            self.label.setText(self.txt_installed)
            for step in self.child_steps:
                step.setEnabled(True)
        else:
            print("Failed")
            # TODO: Error handling


class GitConfigStep(QWidget):
    def __init__(self, key: str, pretty_name: str, wsl: bool = False) -> None:
        super().__init__()
        self.key = key
        self.pretty_name = pretty_name
        self.wsl = wsl
        self.layout = make_setup_step_layout(self)
        self.txt_not_set = f"Set Git {self.key}:  ❌ "
        self.txt_set = f"Set Git {self.key}:  ✅ "
        value = self.value
        self.label = QLabel(self.txt_set if value else self.txt_not_set)
        self.fix_button = QPushButton("Set" if not value else "Update")
        self.fix_button.setStyleSheet("font-size: 10px;")
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.fix_button, stretch=0)
        self.fix_button.clicked.connect(self.open_dialog)

    @property
    def value(self) -> str:
        return (
            subprocess.check_output(["git", "config", self.key])
            .decode()
            .strip()
        )

    def open_dialog(self):
        text, ok = QInputDialog.getText(
            self,
            f"Set Git {self.key}",
            f"Enter your {self.pretty_name}:",
            text=self.value,
        )
        if ok and text:
            subprocess.run(["git", "config", "--global", self.key, text])
            self.label.setText(self.txt_set)
            self.fix_button.setText("Update")


def make_setup_steps_widget_list() -> list[QWidget]:
    """Create a list of setup steps.

    TODO: Figure out how to make some of these react to the others, e.g.,
    we can't install Git until we install a package manager,
    and once we do that, we want to enable the install button on the
    install widget.

    We also want to disable the Git config widgets until Git is installed.
    """
    steps = []
    # TODO: Check that this GUI is the latest version and add option to update
    # if not
    platform = get_platform()
    if platform == "mac":
        steps.append(HomebrewInstall())
    elif platform == "windows":
        steps.append(ChocolateyInstall())
        steps.append(WSLInstall())
    # Install and configure Git
    git_user_name = GitConfigStep(
        key="user.name", pretty_name="full name", wsl=False
    )
    git_user_email = GitConfigStep(
        key="user.email", pretty_name="email address", wsl=False
    )
    git_install = PackageManagerInstallWidget(
        app_name="git",
        app_title="Git",
        child_steps=[git_user_name, git_user_email],
    )
    steps.append(git_install)
    steps.append(git_user_name)
    steps.append(git_user_email)
    # TODO: Install everything in WSL if on Windows?
    # Install Docker
    steps.append(DockerInstall())
    # TODO: Ensure Docker is running
    # We can use `docker desktop status` and `docker desktop start` for this
    # However, this is not necessary on Linux
    # TODO: Ensure Docker permissions are set on Linux
    # TODO: Ensure we have GitHub credentials?
    # TODO: Install Miniforge, initializing shell
    steps.append(CondaInstall())
    # TODO: Install Calkit inside Miniforge base environment
    # Ensure Calkit token is set
    steps.append(CalkitToken())
    # TODO: Install VS Code
    steps.append(VSCodeInstall())
    # TODO: Install recommended VS Code extensions
    return steps


def get_project_dirs() -> list[str]:
    """Get a list of project directories.

    TODO: This should fetch from the cloud and show if it exists in the
    ``calkit`` directory, allowing users to clone.
    """
    raise NotImplementedError


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        # Set title and create layout
        self.setWindowTitle("Calkit")
        self.layout = QHBoxLayout(self)
        # Add Calkit logo
        self.logo = QLabel()
        # Left Section: Setup
        self.setup_widget = QWidget()
        self.setup_layout = QVBoxLayout(self.setup_widget)
        self.setup_layout.setAlignment(Qt.AlignTop)
        self.setup_layout.setSpacing(0)
        self.setup_title = QLabel("System setup")
        self.setup_title.setStyleSheet("font-weight: bold; font-size: 16px;")
        self.setup_layout.addWidget(self.setup_title)
        # Add setup steps to the left section
        self.setup_step_widgets = make_setup_steps_widget_list()
        for setup_step_widget in self.setup_step_widgets:
            self.setup_layout.addWidget(setup_step_widget, stretch=0)
        self.layout.addWidget(self.setup_widget)
        # Right half: Projects
        self.projects_widget = QWidget()
        self.projects_layout = QVBoxLayout(self.projects_widget)
        self.projects_layout.setAlignment(Qt.AlignTop)
        self.projects_title = QLabel("Projects")
        self.projects_title.setStyleSheet(
            "font-weight: bold; font-size: 16px;"
        )
        self.projects_layout.addWidget(self.projects_title)
        # Add a list of folders with "open" icons
        self.project_list = QListWidget()
        self.add_project_item("Project A")
        self.add_project_item("Project B")
        self.add_project_item("Project C")
        self.projects_layout.addWidget(self.project_list)
        # Add the projects widget to the layout
        self.layout.addWidget(self.projects_widget)

    def add_project_item(self, project_name):
        """Add a project item with an 'open' icon to the list."""
        item = QListWidgetItem(QIcon.fromTheme("folder-open"), project_name)
        self.project_list.addItem(item)


def run():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
