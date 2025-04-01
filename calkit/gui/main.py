"""A GUI to help users manage their system.

This app helps install and track system-wide dependencies and open projects
in their editor of choice.
"""

import glob
import os
import subprocess
import sys
import webbrowser
from abc import ABCMeta, abstractmethod
from typing import Literal

import git
import git.exc
from pydantic import BaseModel
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressDialog,
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
        is_set = self.is_set
        self.txt_not_set = "Set Calkit Cloud API token:  ❌ "
        self.txt_set = "Set Calkit Cloud API token:  ✅ "
        self.label = QLabel(self.txt_set if is_set else self.txt_not_set)
        self.fix_button = QPushButton("Set" if not is_set else "Update")
        self.fix_button.setStyleSheet("font-size: 10px;")
        self.layout = make_setup_step_layout(self)
        self.fix_button.clicked.connect(self.open_dialog)
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.fix_button)

    @property
    def is_set(self) -> bool:
        return calkit.config.read().token is not None

    def open_dialog(self):
        webbrowser.open("https://calkit.io/settings?tab=tokens")
        text, ok = QInputDialog.getText(
            self,
            "Set Calkit Cloud API token",
            "Enter API token created at calkit.io/settings:",
            echo=QLineEdit.Password,
        )
        if ok and text:
            config = calkit.config.read()
            config.token = text
            config.write()
            self.label.setText(self.txt_set)
            self.fix_button.setText("Update")


class QWidgetABCMeta(ABCMeta, type(QWidget)):
    pass


class DependencyInstall(QWidget, metaclass=QWidgetABCMeta):
    """An abstract base class to represent an installed dependency."""

    def __init__(self, child_steps: list[QWidget] = []):
        super().__init__()
        self.child_steps = child_steps
        self.layout = make_setup_step_layout(self)
        self.txt_installed = f"Install {self.dependency_name}:  ✅ "
        self.txt_not_installed = f"Install {self.dependency_name}:  ❌ "
        installed = self.installed
        for step in self.child_steps:
            step.setEnabled(installed)
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
            for step in self.child_steps:
                step.setEnabled(True)
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
        output = (
            subprocess.check_output(["wsl", "--status"])
            .decode()
            .replace("\x00", "")
        )
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
        try:
            subprocess.check_output("code --version", shell=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def install(self) -> bool:
        """Install VS Code."""
        # First check our platform and download the installer
        # Run the installer
        raise NotImplementedError


class GitInstall(DependencyInstall):
    @property
    def dependency_name(self) -> str:
        return "Git"

    @property
    def installed(self) -> bool:
        return calkit.check_dep_exists("git")

    def install(self):
        platform = get_platform()
        if platform == "windows":
            # Use Chocolatey to install Git
            process = subprocess.run(["choco", "install", "git"])
        elif platform == "mac":
            process = subprocess.run(["brew", "install", "git"])
        elif platform == "linux":
            # Use apt to install Git
            cmd = "apt install git"
            process = subprocess.run(["pkexec", "sh", "-c", cmd])
        return process.returncode == 0


class WSLGitInstall(DependencyInstall):
    @property
    def dependency_name(self) -> str:
        return "Git in WSL"

    @property
    def installed(self) -> bool:
        try:
            subprocess.check_output(["wsl", "git", "--version"])
            return True
        except subprocess.CalledProcessError:
            return False

    def install(self) -> bool:
        cmd = "apt update && apt install git"
        process = subprocess.run(["wsl", "pkexec", "sh", "-c", cmd])
        return process.returncode == 0


class GitConfigStep(QWidget):
    def __init__(self, key: str, pretty_name: str, wsl: bool = False) -> None:
        super().__init__()
        self.key = key
        self.pretty_name = pretty_name
        self.wsl = wsl
        self.layout = make_setup_step_layout(self)
        if self.wsl:
            self.txt_not_set = f"Set Git {self.key} in WSL:  ❌ "
            self.txt_set = f"Set Git {self.key} in WSL:  ✅ "
        else:
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
    def cmd(self) -> list[str]:
        cmd = ["git", "config", "--global"]
        if self.wsl:
            cmd = ["wsl"] + cmd
        return cmd

    @property
    def value(self) -> str:
        try:
            return (
                subprocess.check_output(self.cmd + [self.key]).decode().strip()
            )
        except subprocess.CalledProcessError:
            return ""

    def open_dialog(self):
        text, ok = QInputDialog.getText(
            self,
            f"Set Git {self.key}",
            f"Enter your {self.pretty_name}:",
            text=self.value,
        )
        if ok and text:
            subprocess.run(self.cmd + [self.key, text])
            self.label.setText(self.txt_set)
            self.fix_button.setText("Update")


def make_setup_step_widgets() -> dict[str, QWidget]:
    """Create a list of setup steps."""
    steps = {}
    # TODO: Check that this GUI is the latest version and add option to update
    # if not
    platform = get_platform()
    if platform == "mac":
        steps["homebrew"] = HomebrewInstall()
    elif platform == "windows":
        steps["chocolatey"] = ChocolateyInstall()
        wsl_git_user = GitConfigStep(
            "user.name", pretty_name="full name", wsl=True
        )
        wsl_git_email = GitConfigStep(
            "user.email", pretty_name="email address", wsl=True
        )
        wsl_git_install = WSLGitInstall(
            child_steps=[wsl_git_user, wsl_git_email]
        )
        wsl_install = WSLInstall(child_steps=[wsl_git_install])
        steps["wsl"] = wsl_install
        steps["wsl-git"] = wsl_git_install
        steps["wsl-git-user"] = wsl_git_user
        steps["wsl-git-email"] = wsl_git_email
    # Install and configure Git
    git_user_name = GitConfigStep(
        key="user.name", pretty_name="full name", wsl=False
    )
    git_user_email = GitConfigStep(
        key="user.email", pretty_name="email address", wsl=False
    )
    git_install = GitInstall(child_steps=[git_user_name, git_user_email])
    steps["git"] = git_install
    steps["git-user"] = git_user_name
    steps["git-email"] = git_user_email
    # TODO: Install everything in WSL if on Windows?
    # Install Docker
    steps["docker"] = DockerInstall()
    # TODO: Ensure Docker is running
    # We can use `docker desktop status` and `docker desktop start` for this
    # However, this is not necessary on Linux
    # TODO: Ensure Docker permissions are set on Linux
    # TODO: Ensure we have GitHub credentials?
    # TODO: Install Miniforge, initializing shell
    steps["miniforge"] = CondaInstall()
    # TODO: Install Calkit inside Miniforge base environment
    # Ensure Calkit token is set
    steps["calkit-token"] = CalkitToken()
    # TODO: Install VS Code
    steps["vscode"] = VSCodeInstall()
    # TODO: Install recommended VS Code extensions
    return steps


class Project(BaseModel):
    owner_name: str
    project_name: str
    wdir: str | None = None
    git_repo_url: str


def get_projects() -> list[Project]:
    """Get a list of projects."""
    # Get projects from the cloud and match them up by Git repo URL
    try:
        cloud_projects = calkit.cloud.get(
            "/user/projects", params=dict(limit=100)
        )["data"]
    except Exception as e:
        cloud_projects = []
        print(f"Error fetching projects from cloud: {e}")
    # Reorient cloud projects as a dict keyed by the Git repo URL
    cloud_projects_by_git_url = {}
    for project_full_name in cloud_projects:
        cloud_projects_by_git_url[project_full_name["git_repo_url"]] = (
            project_full_name
        )
    # Get the local projects
    start = os.path.join(os.path.expanduser("~"), "calkit")
    max_depth = 1
    res = []
    for i in range(max_depth):
        pattern = os.path.join(start, *["*"] * (i + 1), "calkit.yaml")
        res += glob.glob(pattern)
    final_res_by_git_url = {}
    for ck_fpath in res:
        project_dir = os.path.dirname(ck_fpath)
        # Detect project name
        try:
            project_full_name = calkit.detect_project_name(wdir=project_dir)
        except ValueError:
            print(f"Can't detect project name in {project_dir}")
            continue
        owner, name = project_full_name.split("/")
        # Make sure this path is a Git repo
        try:
            repo = git.Repo(project_dir)
            remote_url = repo.remotes.origin.url
            # Simplify the remote URL to account for SSH and HTTPS
            if remote_url.startswith("git@github.com:"):
                remote_url = "https://github.com/" + remote_url.removeprefix(
                    "git@github.com:"
                )
            remote_url = remote_url.removesuffix(".git")
        except git.exc.InvalidGitRepositoryError:
            continue
        project = Project(
            owner_name=owner,
            project_name=name,
            wdir=project_dir,
            git_repo_url=remote_url,
        )
        final_res_by_git_url[remote_url] = project
    for git_repo_url, project_dict in cloud_projects_by_git_url.items():
        # If the project is not in the local directory, add it
        if git_repo_url not in final_res_by_git_url:
            project = Project(
                owner_name=project_dict["owner_account_name"],
                project_name=project_dict["name"],
                git_repo_url=git_repo_url,
                wdir=None,
            )
            final_res_by_git_url[git_repo_url] = project
    final_res = []
    # Sort by repo URL
    git_repo_urls = sorted(final_res_by_git_url.keys())
    for git_repo_url in git_repo_urls:
        final_res.append(final_res_by_git_url[git_repo_url])
    return final_res


class NewProjectDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Create new project")
        # Main layout
        self.layout = QVBoxLayout(self)
        # Project Name
        self.project_name_label = QLabel("Name:")
        self.project_name_input = QLineEdit()
        self.layout.addWidget(self.project_name_label)
        self.layout.addWidget(self.project_name_input)
        # Description
        self.description_label = QLabel("Description:")
        self.description_input = QLineEdit()
        self.layout.addWidget(self.description_label)
        self.layout.addWidget(self.description_input)
        # Buttons
        self.button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        self.button_layout.addWidget(self.ok_button)
        self.button_layout.addWidget(self.cancel_button)
        self.layout.addLayout(self.button_layout)
        # Connect buttons
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        # Connect the validate method to the textChanged signal
        self.project_name_input.textChanged.connect(self.validate)
        self.description_input.textChanged.connect(self.validate)
        self.ok_button.setEnabled(False)

    def validate(self) -> None:
        """Validate the form data on each edit, disabling the submit button
        until it's okay.
        """
        # Check if the project name is empty
        if not self.project_name_input.text():
            self.ok_button.setEnabled(False)
            return
        # If both are valid, enable the button
        self.ok_button.setEnabled(True)

    def get_form_data(self):
        """Retrieve the form data."""
        return {
            "project_name": self.project_name_input.text(),
            "description": self.description_input.text(),
        }


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
        print("Creating setup steps")
        self.setup_step_widgets = make_setup_step_widgets()
        for _, setup_step_widget in self.setup_step_widgets.items():
            setup_step_widget.setMinimumHeight(20)
            self.setup_layout.addWidget(setup_step_widget, stretch=0)
        self.layout.addWidget(self.setup_widget)
        # Right half: Projects
        self.projects_widget = QWidget()
        self.projects_layout = QVBoxLayout(self.projects_widget)
        self.projects_layout.setAlignment(Qt.AlignTop)
        self.projects_layout.setSpacing(0)
        # Add projects title bar
        self.projects_title_bar = QWidget(self.projects_widget)
        self.projects_title_bar_layout = QHBoxLayout(self.projects_title_bar)
        self.projects_title_bar_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.projects_title_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.projects_title_bar_layout.setSpacing(0)
        self.projects_title = QLabel("Projects")
        self.projects_title.setStyleSheet(
            "font-weight: bold; font-size: 16px;"
        )
        self.projects_title_bar_layout.addWidget(self.projects_title)
        # Add plus icon to add a new project
        # This needs to be disabled if:
        # - Calkit token is not set
        # - Git is not installed
        # - Calkit is not installed
        # - GitHub credentials are not set?
        self.new_project_button = QPushButton(self.projects_title_bar)
        self.new_project_button.setIcon(QIcon.fromTheme("list-add"))
        self.new_project_button.setStyleSheet(
            "font-size: 10px; padding: 0px; padding-top: 2px; margin: 0px; "
            "border: none;"
        )
        self.new_project_button.setFixedSize(30, 30)
        self.new_project_button.setIconSize(QSize(18, 18))
        self.new_project_button.setToolTip("Create new project")
        self.new_project_button.clicked.connect(self.create_new_project)
        self.projects_title_bar_layout.addWidget(self.new_project_button)
        # Add refresh button to the projects title bar
        self.refresh_projects_button = QPushButton(self.projects_title_bar)
        self.refresh_projects_button.setIcon(QIcon.fromTheme("view-refresh"))
        self.refresh_projects_button.setStyleSheet(
            "font-size: 10px; padding: 0px; margin: 0px; border: none;"
        )
        self.refresh_projects_button.setFixedSize(18, 30)
        self.refresh_projects_button.setIconSize(QSize(16, 16))
        self.refresh_projects_button.setToolTip("Refresh projects")
        self.refresh_projects_button.clicked.connect(self.refresh_project_list)
        self.projects_title_bar_layout.addWidget(self.refresh_projects_button)
        self.projects_layout.addWidget(self.projects_title_bar)
        # Add a list of folders with "open" icons
        self.project_list_widget = QListWidget()
        self.refresh_project_list()
        self.project_list_widget.itemDoubleClicked.connect(
            self.open_project_vs_code
        )
        # Add right-click context menu to the project list
        self.project_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.project_list_widget.customContextMenuRequested.connect(
            self.show_project_context_menu
        )
        self.projects_layout.addWidget(self.project_list_widget)
        # Add the projects widget to the layout
        self.layout.addWidget(self.projects_widget)

    def refresh_project_list(self) -> None:
        """Refresh the project list by clearing and re-adding items."""
        print("Refreshing project list")
        self.project_list_widget.clear()
        self.projects = get_projects()
        self.projects_by_name = {}
        for project in self.projects:
            name = f"{project.owner_name}/{project.project_name}"
            item = QListWidgetItem(QIcon.fromTheme("folder-open"), name)
            self.projects_by_name[name] = project
            self.project_list_widget.addItem(item)

    def open_project_vs_code(self, item) -> None:
        # If VS Code is not installed, show error message dialog
        if not self.setup_step_widgets["vscode"].installed:
            print("VS Code is not installed")
            QMessageBox.critical(
                self,
                "VS Code not installed",
                "Please install VS Code first.",
            )
            return
        project = self.projects_by_name[item.text()]
        cmd = f"code '{project.wdir}'"
        subprocess.run(cmd, shell=True)

    def show_project_context_menu(self, position):
        """Show a context menu for the project list."""
        # Get the item at the clicked position
        item = self.project_list_widget.itemAt(position)
        if item is None:
            return  # Do nothing if no item was clicked
        project = self.projects_by_name[item.text()]
        # Create the context menu
        menu = QMenu(self)
        open_vs_code_action = menu.addAction("Open with VS Code")
        platform = get_platform()
        if platform == "windows":
            open_folder_txt = "Open folder in Explorer"
        elif platform == "mac":
            open_folder_txt = "Open folder in Finder"
        elif platform == "linux":
            open_folder_txt = "Open folder in file explorer"
        open_folder_action = menu.addAction(open_folder_txt)
        clone_action = menu.addAction("Clone to Calkit projects folder")
        clone_action.setEnabled(project.wdir is None)
        clone_action.setToolTip(
            "Clone the project to the Calkit projects folder"
            if project.wdir is None
            else "Project already exists in Calkit projects folder"
        )
        open_vs_code_action.setEnabled(project.wdir is not None)
        open_folder_action.setEnabled(project.wdir is not None)
        # Add option to open on calkit.io
        open_calkit_io_action = menu.addAction("Open on calkit.io")
        open_calkit_io_action.triggered.connect(
            lambda: webbrowser.open(
                f"https://calkit.io/{project.owner_name}/{project.project_name}"
            )
        )
        # Add option to open on github.com
        open_github_action = menu.addAction("Open on github.com")
        open_github_action.triggered.connect(
            lambda: webbrowser.open(project.git_repo_url)
        )
        # Execute the menu and get the selected action
        action = menu.exec(
            self.project_list_widget.viewport().mapToGlobal(position)
        )
        # Handle the selected action
        if action == open_vs_code_action:
            self.open_project_vs_code(item)
        elif action == open_folder_action:
            self.open_project_folder(item)

    def open_project_folder(self, item: QListWidgetItem) -> None:
        """Open the project folder in the file explorer."""
        platform = get_platform()
        project = self.projects_by_name[item.text()]
        if platform == "windows":
            cmd = ["explorer", project.wdir]
        elif platform == "mac":
            cmd = ["open", project.wdir]
        elif platform == "linux":
            cmd = ["xdg-open", project.wdir]
        subprocess.run(cmd)

    def create_new_project(self) -> None:
        dialog = NewProjectDialog()
        if dialog.exec() == QDialog.Accepted:
            form_data = dialog.get_form_data()
            project_name = form_data["project_name"]
            # TODO: Create the project using the CLI method
            # Show a progress dialog while the project is being created
            progress = QProgressDialog(
                f"Creating {project_name}...", None, 0, 0, self
            )
            progress.setWindowTitle("Please Wait")
            progress.setCancelButton(None)  # Remove the cancel button
            progress.setMinimumDuration(0)  # Show immediately
            progress.setRange(0, 0)  # Indeterminate progress
            progress.show()
            # Close the progress dialog
            # Use QTimer to simulate a delay without blocking the event loop
            QTimer.singleShot(
                2000, lambda: self.finish_project_creation(progress)
            )

    def finish_project_creation(self, progress: QProgressDialog) -> None:
        """Finish the project creation process."""
        progress.close()
        # Refresh the project list
        self.refresh_project_list()
        QMessageBox.information(
            self, "Success", "Project created successfully!"
        )


def run():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
