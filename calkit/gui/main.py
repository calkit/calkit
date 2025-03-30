"""A GUI to help users manage their system.

This app helps install and track system-wide dependencies and open projects
in their editor of choice.
"""

import subprocess
import sys
import webbrowser
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
        self.layout = QHBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0, 0, 0, 0)
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


class HomebrewInstall(QWidget):
    """A widget to check for and install Homebrew."""

    def __init__(self):
        super().__init__()
        self.layout = QHBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.txt_installed = "Install Homebrew:  ✅ "
        self.txt_not_installed = "Install Homebrew:  ❌ "
        installed = calkit.check_dep_exists("brew")
        self.label = QLabel(
            self.txt_installed if installed else self.txt_not_installed
        )
        self.layout.addWidget(self.label)
        if not installed:
            self.install_button = QPushButton("Install")
            self.install_button.clicked.connect(self.install)
            self.layout.addWidget(self.install_button)

    def install(self):
        # Disable install button
        self.install_button.setEnabled(False)
        # Show loading message
        self.install_button.setText("Installing...")
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
        # Check if this was successful
        if subprocess.returncode == 0:
            self.layout.removeWidget(self.install_button)
            self.install_button.deleteLater()
            self.install_button = None
            # Update label to show installed
            self.label.setText(self.txt_installed)
        else:
            print("Failed")
            # TODO: Show error message to user


class ChocolateyInstall(QWidget):
    """A widget to check for and install Chocolatey."""

    def __init__(self):
        super().__init__()
        self.layout = QHBoxLayout(self)
        self.txt_installed = "Install Chocolatey:  ✅ "
        self.txt_not_installed = "Install Chocolatey:  ❌ "
        installed = calkit.check_dep_exists("choco")
        self.label = QLabel(
            self.txt_installed if installed else self.txt_not_installed
        )
        self.layout.addWidget(self.label)
        if not installed:
            self.install_button = QPushButton("Install")
            self.install_button.clicked.connect(self.install)
            self.layout.addWidget(self.install_button)

    def install(self):
        # Disable install button
        self.install_button.setEnabled(False)
        # Show loading message
        self.install_button.setText("Installing...")
        # Run command as administrator in PowerShell
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
        # Check if this was successful
        if process.returncode == 0:
            self.layout.removeWidget(self.install_button)
            self.install_button.deleteLater()
            self.install_button = None
            # Update label to show installed
            self.label.setText(self.txt_installed)
        else:
            print("Failed")
            # TODO: Show error message to user


class GitInstall(QWidget):
    """A widget to check for and install Git."""

    def __init__(
        self,
        package_manager_install_widget: HomebrewInstall
        | ChocolateyInstall
        | None = None,
    ):
        super().__init__()
        self.package_manager_install_widget = package_manager_install_widget
        self.layout = QHBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.txt_installed = "Install Git:  ✅ "
        self.txt_not_installed = "Install Git:  ❌ "
        installed = calkit.check_dep_exists("git")
        self.label = QLabel(
            self.txt_installed if installed else self.txt_not_installed
        )
        self.layout.addWidget(self.label)
        if not installed:
            self.install_button = QPushButton("Install")
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
            process = subprocess.run(["choco", "install", "git"])
        elif get_platform() == "mac":
            process = subprocess.run(["brew", "install", "git"])
        elif get_platform() == "linux":
            # Use apt to install Git
            cmd = "apt install git"
            process = subprocess.run(["pkexec", "sh", "-c", cmd])
        if process.returncode == 0:
            self.layout.removeWidget(self.install_button)
            self.install_button.deleteLater()
            self.install_button = None
            # Update label to show installed
            self.label.setText(self.txt_installed)
        else:
            print("Failed")
            # TODO: Error handling


class GitUserName(QWidget):
    """A widget to set the Git user name."""

    def __init__(self):
        super().__init__()
        self.layout = QHBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.txt_not_set = "Set Git user.name:  ❌ "
        self.txt_set = "Set Git user.name:  ✅ "
        self.git_user_name = git_user_name()
        self.label = QLabel(
            self.txt_set if self.git_user_name else self.txt_not_set
        )
        self.fix_button = QPushButton(
            "Set" if not self.git_user_name else "Update"
        )
        self.fix_button.setStyleSheet("font-size: 10px;")
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.fix_button, stretch=0)
        self.fix_button.clicked.connect(self.open_dialog)

    def open_dialog(self):
        text, ok = QInputDialog.getText(
            self,
            "Set Git user.name",
            "Enter your full name:",
            text=self.git_user_name,
        )
        if ok and text:
            subprocess.run(["git", "config", "--global", "user.name", text])
            self.label.setText(self.txt_set)
            self.git_user_name = git_user_name()
            self.fix_button.setText("Update")


class GitUserEmail(QWidget):
    """A widget to set the Git user email."""

    def __init__(self):
        super().__init__()
        self.layout = QHBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.txt_not_set = "Set Git user.email:  ❌ "
        self.txt_set = "Set Git user.email:  ✅ "
        self.git_email = git_email()
        self.label = QLabel(
            self.txt_set if self.git_email else self.txt_not_set
        )
        self.fix_button = QPushButton(
            "Set" if not self.git_email else "Update"
        )
        self.fix_button.setStyleSheet("font-size: 10px;")
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.fix_button, stretch=0)
        self.fix_button.clicked.connect(self.open_dialog)

    def open_dialog(self):
        text, ok = QInputDialog.getText(
            self,
            "Set Git user.email",
            "Enter your email address:",
            text=self.git_email,
        )
        if ok and text:
            subprocess.run(["git", "config", "--global", "user.email", text])
            self.label.setText(self.txt_set)
            self.git_email = git_email()
            self.fix_button.setText("Update")


def make_setup_steps_list() -> list[QWidget]:
    """Create a list of setup steps."""
    steps = [CalkitToken()]
    platform = get_platform()
    if platform == "mac":
        steps.append(HomebrewInstall())
    elif platform == "windows":
        steps.append(ChocolateyInstall())
    steps.append(GitInstall())
    steps.append(GitUserName())
    steps.append(GitUserEmail())
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
        # Add checkboxes to the left section
        self.checkboxes = make_setup_steps_list()
        for checkbox in self.checkboxes:
            self.setup_layout.addWidget(checkbox, stretch=0)
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
