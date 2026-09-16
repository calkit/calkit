"""A GUI to help users manage their system.

This app helps install and track system-wide dependencies and open projects
in their editor of choice.
"""

__version__ = "0.0.5"

import glob
import itertools
import os
import platform
import re
import shutil
import subprocess
import sys
import webbrowser
from abc import ABCMeta, abstractmethod
from pathlib import Path
from typing import Literal
from urllib.request import urlopen

# Set env var for gitpython so it doesn't fail if not installed
os.environ["GIT_PYTHON_REFRESH"] = "quiet"

import git
import git.exc
import requests
import ruamel.yaml
from pydantic import BaseModel
from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
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

ryaml = ruamel.yaml.YAML()
ryaml.indent(mapping=2, sequence=4, offset=2)
ryaml.preserve_quotes = True
ryaml.width = 70


def to_kebab_case(str) -> str:
    """Convert a string to kebab-case."""
    return re.sub(r"[-_,\.\ ]", "-", str.lower())


def check_dep_exists(name: str) -> bool:
    return shutil.which(name) is not None


def load_calkit_info(
    wdir=None,
    process_includes: bool | str | list[str] = False,
) -> dict:
    """Load Calkit project information.

    Parameters
    ----------
    wdir : str
        Working directory. Defaults to current working directory.
    process_includes: bool, string or list of strings
        Whether or not to process any '_include' keys for a given kind of
        object. If a string is passed, only process includes for that kind.
        Similarly, if a list of strings is passed, only process those kinds.
        If True, process all default kinds.
    """
    info = {}
    fpath = "calkit.yaml"
    if wdir is not None:
        fpath = os.path.join(wdir, fpath)
    if os.path.isfile(fpath):
        with open(fpath) as f:
            info = ryaml.load(f)
    # Check for any includes, i.e., entities with an _include key, for which
    # we should merge in another file
    default_includes_enabled = ["environments", "procedures"]
    if process_includes:
        if isinstance(process_includes, bool):
            includes_enabled = default_includes_enabled
        elif isinstance(process_includes, str):
            includes_enabled = [process_includes]
        elif isinstance(process_includes, list):
            includes_enabled = process_includes
        for kind in includes_enabled:
            if kind in info:
                for obj_name, obj in info[kind].items():
                    if "_include" in obj:
                        include_fpath = obj.pop("_include")
                        if wdir is not None:
                            include_fpath = os.path.join(wdir, include_fpath)
                        if os.path.isfile(include_fpath):
                            with open(include_fpath) as f:
                                include_data = ryaml.load(f)
                            info[kind][obj_name] |= include_data
    return info


def detect_project_name(wdir: str = None) -> str:
    """Detect a Calkit project owner and name."""
    ck_info = load_calkit_info(wdir=wdir)
    name = ck_info.get("name")
    owner = ck_info.get("owner")
    if name is None or owner is None:
        try:
            url = git.Repo(path=wdir).remote().url
        except ValueError:
            raise ValueError("No Git remote set with name 'origin'")
        from_url = url.split("github.com")[-1][1:].removesuffix(".git")
        owner_name, project_name = from_url.split("/")
    if name is None:
        name = project_name
    if owner is None:
        owner = owner_name
    return f"{owner}/{name}"


def get_calkit_token() -> str:
    try:
        return (
            subprocess.check_output(["calkit", "config", "get", "token"])
            .decode()
            .strip()
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""


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


def wsl_installed() -> bool:
    try:
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
    except subprocess.CalledProcessError:
        return False


def vs_code_installed() -> bool:
    code_path = shutil.which("code")
    if code_path is None:
        return False
    try:
        subprocess.check_output([code_path, "--version"])
        return True
    except subprocess.CalledProcessError:
        return False


def get_installed_vs_code_extensions() -> list[str]:
    code_path = shutil.which("code")
    if code_path is None:
        return []
    return (
        subprocess.run(
            [code_path, "--list-extensions"], capture_output=True, text=True
        )
        .stdout.strip()
        .split("\n")
    )


def find_conda_prefix() -> str:
    """Attempt to find the Conda prefix.

    This must be under the user's home directory.
    """
    platform = get_platform()
    paths = [
        os.path.join(os.path.expanduser("~"), "miniforge3"),
        os.path.join(
            os.path.expanduser("~"),
            "anaconda3",
        ),
        os.path.join(
            os.path.expanduser("~"),
            "miniconda3",
        ),
        os.path.join(
            os.path.expanduser("~"),
            "mambaforge",
        ),
    ]
    for path in paths:
        if platform == "windows":
            exe = os.path.join(path, "python")
        else:
            exe = os.path.join(path, "bin", "python")
        if os.path.isdir(path):
            try:
                subprocess.check_output([exe, "--version"])
                return path
            except (subprocess.CalledProcessError, FileNotFoundError):
                return ""
    return ""


def get_conda_scripts_dir() -> str:
    prefix = find_conda_prefix()
    platform = get_platform()
    if platform == "windows":
        return os.path.join(prefix, "Scripts")
    return os.path.join(prefix, "bin")


def run_in_git_bash(
    command: str, capture_output: bool = False, check: bool = False
) -> subprocess.CompletedProcess:
    """Run a command in Git Bash on Windows."""
    # Find the Git Bash executable path
    # Common locations:
    paths = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\git-bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\git-bash.exe",
        os.path.join(
            os.path.expanduser("~"),
            "AppData",
            "Local",
            "Programs",
            "Git",
            "git-bash.exe",
        ),
    ]
    for path in paths:
        if os.path.isfile(path):
            return subprocess.run(
                [path, "--login", "-c", command],
                capture_output=capture_output,
                check=check,
            )
    raise FileNotFoundError("Git Bash executable not found")


def run_in_powershell(
    cmd: str,
    as_admin: bool = False,
    capture_output: bool = False,
    check: bool = False,
    wdir: str | None = None,
    bypass_execution_policy: bool = False,
) -> subprocess.CompletedProcess:
    if as_admin:
        cmd = f"Start-Process PowerShell -Verb RunAs -ArgumentList '{cmd}'"
    powershell_cmd = ["powershell"]
    if bypass_execution_policy:
        powershell_cmd += ["-ExecutionPolicy", "ByPass"]
    powershell_cmd += ["-Command", cmd]
    return subprocess.run(
        powershell_cmd,
        capture_output=capture_output,
        check=check,
        cwd=wdir,
    )


def get_downloads_folder() -> str:
    return os.path.join(os.path.expanduser("~"), "Downloads")


def make_setup_step_layout(widget: QWidget) -> QHBoxLayout:
    layout = QHBoxLayout(widget)
    layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    layout.setSpacing(0)
    layout.setContentsMargins(0, 0, 0, 0)
    return layout


class CalkitToken(QWidget):
    """A widget to set the Calkit token."""

    just_set = Signal()

    def __init__(self):
        super().__init__()
        print("Checking Calkit token status")
        is_set = self.is_set
        self.txt_not_set = "Set Calkit Cloud API token: ❌"
        self.txt_set = "Set Calkit Cloud API token: ✅"
        self.label = QLabel(self.txt_set if is_set else self.txt_not_set)
        self.update_button = QPushButton(self)
        self.update_button.setText("✏️")
        self.update_button.setCursor(Qt.PointingHandCursor)
        self.update_button.setStyleSheet(
            "font-size: 12px; padding: 0px; margin: 0px; border: none;"
        )
        self.update_button.setFixedSize(18, 18)
        self.update_button.setToolTip("Update")
        self.layout = make_setup_step_layout(self)
        self.update_button.clicked.connect(self.open_dialog)
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.update_button)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def show_context_menu(self, position):
        """Show a context menu at the given position."""
        menu = QMenu(self)
        menu.addAction("Refresh", self.refresh)
        # Show the menu at the cursor position
        menu.exec(self.mapToGlobal(position))

    def refresh(self) -> None:
        print("Refreshing Calkit token status")
        if self.is_set:
            self.label.setText(self.txt_set)
        else:
            self.label.setText(self.txt_not_set)

    @property
    def is_set(self) -> bool:
        return bool(get_calkit_token())

    def open_dialog(self):
        webbrowser.open("https://calkit.io/settings?tab=tokens")
        text, ok = QInputDialog.getText(
            self,
            "Set Calkit Cloud API token",
            "Enter API token created at calkit.io/settings:",
            echo=QLineEdit.Password,
        )
        if ok and text:
            exe = os.path.join(get_conda_scripts_dir(), "calkit")
            cmd = [exe, "config", "set", "token", text]
            subprocess.check_call(cmd)
            self.refresh()
            self.just_set.emit()


class QWidgetABCMeta(ABCMeta, type(QWidget)):
    pass


class DependencyInstall(QWidget, metaclass=QWidgetABCMeta):
    """An abstract base class to represent an installed dependency."""

    just_installed = Signal()

    def __init__(self, child_steps: list[QWidget] = []):
        super().__init__()
        self.child_steps = child_steps
        self.layout = make_setup_step_layout(self)
        self.txt_installed = f"Install {self.dependency_name}: ✅"
        self.txt_not_installed = f"Install {self.dependency_name}: ❌"
        self.label = QLabel()
        self.layout.addWidget(self.label)
        self.install_button = None
        self.refresh()
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    @property
    def restart_after_install(self) -> bool:
        return False

    def show_context_menu(self, position):
        """Show a context menu at the given position."""
        menu = QMenu(self)
        menu.addAction("Refresh", self.refresh)
        # Show the menu at the cursor position
        menu.exec(self.mapToGlobal(position))

    def refresh(self) -> bool:
        """Refresh the widget, e.g., if it's been installed and we want to
        update the check mark display.
        """
        print(f"Refreshing {self.dependency_name} install status")
        installed = self.installed
        for step in self.child_steps:
            step.setEnabled(installed)
        if not installed:
            self.label.setText(self.txt_not_installed)
            if self.install_button is None:
                self.install_button = QPushButton("⬇️")
                self.install_button.setCursor(Qt.PointingHandCursor)
                self.install_button.setToolTip("Install")
                self.install_button.setFixedSize(18, 18)
                self.install_button.setStyleSheet(
                    "font-size: 12px; padding: 0px; margin: 0px; border: none;"
                )
                self.install_button.clicked.connect(self.install)
                self.layout.addWidget(self.install_button)
        elif installed:
            if self.install_button is not None:
                self.layout.removeWidget(self.install_button)
                self.install_button.deleteLater()
                self.install_button = None
            # Update label to show installed
            self.label.setText(self.txt_installed)
        return installed

    @property
    @abstractmethod
    def dependency_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def installed(self) -> bool:
        """Return a bool indicating if the dependency is installed."""
        raise NotImplementedError

    @property
    def install_command(self) -> list[str] | None:
        return None

    @property
    def installer_download_url(self) -> str | None:
        return None

    def install(self) -> bool:
        """Install the app, returning a bool indicating success."""
        self.install_button.setEnabled(False)
        install_thread = InstallThread(
            url=self.installer_download_url,
            cmd=self.install_command,
            parent=self,
        )
        install_progress = QProgressDialog(
            f"Installing {self.dependency_name}...", None, 0, 0, self
        )
        install_progress.setWindowTitle("Calkit Assistant")
        install_thread.finished.connect(install_progress.close)
        install_thread.finished.connect(self.finish_install)
        install_thread.start()
        return True

    def finish_install(self):
        """After attempting to install, run this."""
        if self.restart_after_install:
            # Show a dialog box explaining why we need to restart
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Information)
            msg_box.setWindowTitle("Calkit Assistant")
            msg_box.setText(
                "Calkit Assistant needs to restart to check "
                f"{self.dependency_name} install."
            )
            msg_box.setStandardButtons(QMessageBox.Ok)
            if msg_box.exec() == QMessageBox.Ok:
                restart()
        installed = self.refresh()
        for step in self.child_steps:
            step.refresh()
        self.just_installed.emit()
        if not installed:
            QMessageBox.critical(
                self,
                "Installation failed",
                "Installation failed.",
            )


class HomebrewInstall(DependencyInstall):
    """A widget to check for and install Homebrew."""

    @property
    def dependency_name(self) -> str:
        return "Homebrew"

    @property
    def installed(self) -> bool:
        return check_dep_exists("brew")

    @property
    def install_command(self) -> list[str]:
        return [
            "/bin/bash",
            "-c",
            (
                "$(curl -fsSL https://raw.githubusercontent.com/"
                "Homebrew/install/HEAD/install.sh)"
            ),
        ]


class ChocolateyInstall(DependencyInstall):
    """A widget to check for and install Chocolatey."""

    @property
    def dependency_name(self) -> str:
        return "Chocolatey"

    @property
    def installed(self) -> bool:
        return check_dep_exists("choco")

    @property
    def install_command(self) -> list[str]:
        cmd = (
            "Set-ExecutionPolicy Bypass -Scope Process -Force; "
            "[System.Net.ServicePointManager]::SecurityProtocol = "
            "[System.Net.ServicePointManager]::SecurityProtocol -bor 3072; "
            "iex ((New-Object System.Net.WebClient).DownloadString("
            "'https://community.chocolatey.org/install.ps1'))"
        )
        return [
            "powershell",
            "-Command",
            "Start-Process",
            "powershell",
            "-Verb",
            "runAs",
            "-ArgumentList",
            f"'{cmd}'",
        ]


class WSLInstall(DependencyInstall):
    """A widget to check for and install WSL on Windows."""

    @property
    def dependency_name(self) -> str:
        return "WSL"

    @property
    def installed(self) -> bool:
        return wsl_installed()

    @property
    def install_command(self) -> list[str]:
        # Run command as administrator in PowerShell
        cmd = (
            "dism.exe /online /enable-feature "
            "/featurename:Microsoft-Windows-Subsystem-Linux /all /norestart "
            "&& dism.exe /online /enable-feature "
            "/featurename:VirtualMachinePlatform /all /norestart && "
            "wsl --set-default-version 2 && "
            "wsl --install -d Ubuntu"
        )
        return [
            "winget",
            "install",
            "--accept-source-agreements",
            "--accept-package-agreements",
            "Microsoft.WSL",
            "--force",
            "&&",
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "Start-Process",
            "cmd",
            "-Verb",
            "runAs",
            "-ArgumentList",
            f'"/k {cmd}"',
        ]

    def finish_install(self):
        """Prompt user to restart their computer for changes to take effect."""
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setWindowTitle("Calkit Assistant")
        msg_box.setText(
            "WSL is being installed in the background command prompt. "
            "After it finishes, please restart your computer for the "
            "changes to take effect."
        )
        # Create one button for restart now and one for restart later
        restart_button = msg_box.addButton("Restart now", QMessageBox.YesRole)
        msg_box.addButton("Restart later", QMessageBox.NoRole)
        msg_box.exec()
        if msg_box.clickedButton() == restart_button:
            subprocess.run("shutdown /r /t 0", shell=True)


class CondaInstall(DependencyInstall):
    @property
    def dependency_name(self) -> str:
        return "Conda"

    @property
    def installed(self) -> bool:
        return bool(find_conda_prefix())

    @property
    def installer_download_url(self) -> str:
        # See https://github.com/conda-forge/miniforge/releases/latest
        urls = {
            "windows": (
                "https://github.com/conda-forge/miniforge/"
                "releases/download/24.11.3-2/"
                "Miniforge3-24.11.3-2-Windows-x86_64.exe"
            ),
            "linux-aarch64": (
                "https://github.com/conda-forge/miniforge/releases/download/"
                "24.11.3-2/Miniforge3-24.11.3-2-Linux-aarch64.sh"
            ),
            "mac-arm64": (
                "https://github.com/conda-forge/miniforge/releases/download/"
                "24.11.3-2/Miniforge3-24.11.3-2-MacOSX-arm64.sh"
            ),
        }
        # First check our platform and download the installer
        pf = get_platform()
        arch = platform.machine().lower()
        if pf != "windows":
            pf += "-" + arch
        return urls[pf]

    @property
    def install_command(self) -> list[str]:
        pf = get_platform()
        fname = os.path.basename(self.installer_download_url)
        fpath = os.path.join(get_downloads_folder(), fname)
        if pf.startswith("mac"):
            cmd = ["/bin/zsh", fpath]
        elif pf.startswith("linux"):
            cmd = ["/bin/bash", fpath]
        elif pf.startswith("windows"):
            cmd = [fpath]
        return cmd


class DockerInstall(DependencyInstall):
    @property
    def dependency_name(self) -> str:
        return "Docker"

    @property
    def installed(self) -> bool:
        return check_dep_exists("docker")

    @property
    def install_command(self) -> list[str] | None:
        platform = get_platform()
        if platform == "windows":
            return [
                "winget",
                "install",
                "--accept-source-agreements",
                "--accept-package-agreements",
                "-e",
                "--id",
                "Docker.DockerDesktop",
            ]
        elif platform == "mac":
            return ["brew", "install", "--cask", "docker"]
        else:
            raise NotImplementedError


class VSCodeInstall(DependencyInstall):
    @property
    def dependency_name(self) -> str:
        return "VS Code"

    @property
    def installed(self) -> bool:
        return vs_code_installed()

    @property
    def install_command(self) -> list[str]:
        platform = get_platform()
        if platform == "windows":
            return [
                "winget",
                "install",
                "-e",
                "--id",
                "Microsoft.VisualStudioCode",
            ]
        elif platform == "mac":
            return ["brew", "install", "--cask", "visual-studio-code"]
        else:
            raise NotImplementedError


class VSCodeExtensionsInstall(DependencyInstall):
    recommended = [
        "james-yu.latex-workshop",
        "iterative.dvc",
        "mechatroner.rainbow-csv",
        "charliermarsh.ruff",
        "ms-python.python",
        "ms-toolsai.jupyter",
        "redhat.vscode-yaml",
        "eamodio.gitlens",
        "bierner.markdown-mermaid",
        "mathworks.language-matlab",
        "grapecity.gc-excelviewer",
        "ms-vscode-remote.remote-containers",
    ]

    @property
    def dependency_name(self) -> str:
        return "VS Code extensions"

    @property
    def installed(self) -> bool:
        return not (
            set(self.recommended) - set(get_installed_vs_code_extensions())
        )

    @property
    def install_command(self) -> list[str]:
        cmd = []
        installed = get_installed_vs_code_extensions()
        code_path = shutil.which("code")
        for ext in self.recommended:
            if ext not in installed:
                print("VS Code extension", ext, "not found")
                if cmd:
                    cmd.append("&&")
                cmd += [code_path, "--install-extension", ext]
        return cmd


class GitInstall(DependencyInstall):
    @property
    def dependency_name(self) -> str:
        return "Git"

    @property
    def installed(self) -> bool:
        return check_dep_exists("git")

    @property
    def install_command(self) -> list[str]:
        platform = get_platform()
        if platform == "windows":
            # Use winget to install Git
            return [
                "winget",
                "install",
                "--id",
                "Git.Git",
                "-e",
                "--source",
                "winget",
            ]
        elif platform == "mac":
            return ["brew", "install", "git"]
        else:
            raise NotImplementedError


class WSLGitInstall(DependencyInstall):
    @property
    def dependency_name(self) -> str:
        return "Git in WSL"

    @property
    def installed(self) -> bool:
        if not wsl_installed():
            return False
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
        print(f"Checking Git {key} config status")
        self.key = key
        self.pretty_name = pretty_name
        self.wsl = wsl
        self.layout = make_setup_step_layout(self)
        if self.wsl:
            self.txt_not_set = f"Set Git {self.key} in WSL: ❌"
            self.txt_set = f"Set Git {self.key} in WSL: ✅"
        else:
            self.txt_not_set = f"Set Git {self.key}: ❌"
            self.txt_set = f"Set Git {self.key}: ✅"
        value = self.value
        self.label = QLabel(self.txt_set if value else self.txt_not_set)
        # Create a button for updating
        self.update_button = QPushButton(self)
        self.update_button.setText("✏️")
        self.update_button.setCursor(Qt.PointingHandCursor)
        self.update_button.setStyleSheet(
            "font-size: 12px; padding: 0px; margin: 0px; border: none;"
        )
        self.update_button.setFixedSize(18, 18)
        self.update_button.setToolTip("Update")
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.update_button, stretch=0)
        self.update_button.clicked.connect(self.open_dialog)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def show_context_menu(self, position):
        """Show a context menu at the given position."""
        menu = QMenu(self)
        menu.addAction("Refresh", self.refresh)
        # Show the menu at the cursor position
        menu.exec(self.mapToGlobal(position))

    def refresh(self) -> None:
        print(f"Refreshing Git {self.key} config status")
        if self.value:
            self.label.setText(self.txt_set)
        else:
            self.label.setText(self.txt_not_set)

    @property
    def cmd(self) -> list[str]:
        cmd = ["git", "config", "--global"]
        if self.wsl:
            cmd = ["wsl"] + cmd
        return cmd

    @property
    def value(self) -> str:
        if self.wsl and not wsl_installed():
            return ""
        try:
            return (
                subprocess.check_output(self.cmd + [self.key]).decode().strip()
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""

    def open_dialog(self):
        text, ok = QInputDialog.getText(
            self,
            f"Set Git {self.key}",
            f"Enter your {self.pretty_name}:",
            text=self.value,
        )
        if ok and text:
            cmd = self.cmd + [self.key, text]
            try:
                subprocess.run(cmd, shell=False, check=True)
            except Exception as e:
                print(f"Failed to set Git {self.key}: {e}")
            self.refresh()


class CondaInit(QWidget):
    """A widget to ensure Conda has been initialized in the relevant shell."""

    def __init__(self):
        super().__init__()
        self.layout = make_setup_step_layout(self)
        self.txt_not_set = "Run conda init: ❌"
        self.txt_set = "Run conda init: ✅"
        self.label = QLabel()
        self.layout.addWidget(self.label)
        self.run_button = None
        self.refresh()
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def show_context_menu(self, position):
        """Show a context menu at the given position."""
        menu = QMenu(self)
        menu.addAction("Refresh", self.refresh)
        # Show the menu at the cursor position
        menu.exec(self.mapToGlobal(position))

    def refresh(self) -> bool:
        """Refresh the widget's display to reflect completion."""
        print("Refreshing Conda init status")
        is_done = self.is_done
        if not is_done:
            self.label.setText(self.txt_not_set)
            if self.run_button is None:
                self.run_button = QPushButton(self)
                self.run_button.setText("🪄")
                self.run_button.setCursor(Qt.PointingHandCursor)
                self.run_button.setStyleSheet(
                    "font-size: 12px; padding: 0px; margin: 0px; border: none;"
                )
                self.run_button.setFixedSize(18, 18)
                self.run_button.setToolTip("Run conda init")
                self.run_button.clicked.connect(self.run_conda_init)
                self.layout.addWidget(self.run_button)
            else:
                self.run_button.setEnabled(True)
        else:
            if self.run_button is not None:
                self.layout.removeWidget(self.run_button)
                self.run_button.deleteLater()
                self.run_button = None
            # Update label to show it's done
            self.label.setText(self.txt_set)
        return is_done

    @property
    def is_done(self) -> bool:
        platform = get_platform()
        if platform == "windows":
            print("Checking that Git Bash can run Conda")
            try:
                run_in_git_bash("conda --version", check=True)
            except Exception as e:
                print(f"Failed to run Conda in Git Bash: {e}")
                return False
            print("Checking that Powershell can run Conda")
            try:
                run_in_powershell("conda --version", check=True)
            except Exception as e:
                print(f"Failed to run Conda in Powershell: {e}")
                return False
            return True
        return bool(check_dep_exists("conda"))

    def run_conda_init(self):
        print("Running conda init")
        self.run_button.setEnabled(False)
        if get_platform() == "windows":
            # First make sure we can run scripts in PowerShell
            print("Setting PowerShell execution policy to RemoteSigned")
            run_in_powershell(
                (
                    "-ExecutionPolicy ByPass Set-ExecutionPolicy "
                    "RemoteSigned -Scope CurrentUser -Confirm:$false"
                ),
                as_admin=True,
                capture_output=False,
                check=False,
                bypass_execution_policy=True,
            )
            conda_exe = os.path.join(find_conda_prefix(), "Scripts", "conda")
            # Convert to posix path
            conda_exe = Path(conda_exe).as_posix()
            run_in_git_bash(f"{conda_exe} init bash powershell")
        else:
            conda_exe = os.path.join(find_conda_prefix(), "bin", "conda")
            cmd = [conda_exe, "init"]
            subprocess.run(cmd)
        is_done = self.refresh()
        if not is_done:
            QMessageBox.critical(
                self,
                "Conda init failed",
                "Conda init failed.",
            )


class CalkitInstall(DependencyInstall):
    @property
    def dependency_name(self) -> str:
        return "Calkit"

    @property
    def installed(self) -> bool:
        try:
            subprocess.check_output(["calkit", "--version"])
            return True
        except Exception:
            return False

    @property
    def install_command(self) -> list[str]:
        return ["uv", "tool", "install", "calkit-python"]


class UvInstall(DependencyInstall):
    @property
    def dependency_name(self) -> str:
        return "uv"

    @property
    def installed(self) -> bool:
        return check_dep_exists("uv")

    @property
    def install_command(self) -> list[str]:
        platform = get_platform()
        if platform == "windows":
            return [
                "powershell",
                "-ExecutionPolicy",
                "ByPass",
                "-c",
                "irm https://astral.sh/uv/0.6.12/install.ps1 | iex",
            ]
        return [
            "/bin/bash",
            "-c",
            "curl -LsSf https://astral.sh/uv/install.sh | sh",
        ]


def make_setup_step_widgets() -> dict[str, QWidget]:
    """Create a list of setup steps."""
    steps = {}
    # TODO: Check that this GUI is the latest version and add option to update
    # if not
    platform = get_platform()
    if platform == "mac":
        steps["homebrew"] = HomebrewInstall()
    elif platform == "windows":
        wsl_install = WSLInstall()
        steps["wsl"] = wsl_install
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
    calkit_token = CalkitToken()
    calkit_install = CalkitInstall(child_steps=[calkit_token])
    # Install uv
    steps["uv"] = UvInstall(child_steps=[calkit_install])
    # Install Calkit as a uv tool
    steps["calkit"] = calkit_install
    # Ensure Calkit token is set
    steps["calkit-token"] = calkit_token
    # Install VS Code and recommended extensions
    vs_code_extensions = VSCodeExtensionsInstall()
    steps["vscode"] = VSCodeInstall(child_steps=[vs_code_extensions])
    steps["vscode-extensions"] = vs_code_extensions
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
        token = get_calkit_token()
        if not token:
            raise ValueError("No Calkit token found")
        resp = requests.get(
            "https://api.calkit.io/user/projects",
            headers={"Authorization": f"Bearer {token}"},
        )
        cloud_projects = resp.json()["data"]
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
            project_full_name = detect_project_name(wdir=project_dir)
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
        # Project title
        self.project_title_label = QLabel("Title:")
        self.project_title_input = QLineEdit()
        self.project_title_input.textChanged.connect(
            self.update_project_name_from_title
        )
        self.layout.addWidget(self.project_title_label)
        self.layout.addWidget(self.project_title_input)
        # Project name
        self.project_name_label = QLabel("Name:")
        self.project_name_input = QLineEdit()
        self.layout.addWidget(self.project_name_label)
        self.layout.addWidget(self.project_name_input)
        # Description
        self.description_label = QLabel("Description:")
        self.description_input = QLineEdit()
        self.layout.addWidget(self.description_label)
        self.layout.addWidget(self.description_input)
        # Add dropdown menu for selecting a project template
        self.template_label = QLabel("Template:")
        self.template_combo = QComboBox()
        self.template_combo.addItems(
            [
                "calkit/example-basic",
                "None",
            ]
        )
        self.layout.addWidget(self.template_label)
        self.layout.addWidget(self.template_combo)
        # Checkbox for whether or not we want to make this public, which is
        # only possible if we are creating in the cloud
        self.public_checkbox = QCheckBox("Make project public")
        self.public_checkbox.setChecked(True)
        self.layout.addWidget(self.public_checkbox)
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

    def update_project_name_from_title(self) -> None:
        title_txt = self.project_title_input.text()
        name_txt = to_kebab_case(title_txt)
        self.project_name_input.setText(name_txt)

    def validate(self) -> None:
        """Validate the form data on each edit, disabling the submit button
        until it's okay.
        """
        # Check if the project title or name is empty
        if (
            not self.project_name_input.text()
            or not self.project_title_input.text()
        ):
            self.ok_button.setEnabled(False)
            return
        # If both are valid, enable the button
        self.ok_button.setEnabled(True)

    def get_form_data(self):
        """Retrieve the form data."""
        return {
            "title": self.project_title_input.text(),
            "name": self.project_name_input.text(),
            "description": self.description_input.text(),
            "cloud": True,  # Don't make this optional
            "public": self.public_checkbox.isChecked(),
            "template": self.template_combo.currentText(),
        }


class CloneThread(QThread):
    """A thread to clone a project."""

    def __init__(self, project_name: str, **kwargs):
        super().__init__(**kwargs)
        self.project_name = project_name

    def run(self) -> None:
        """Run Calkit in a subprocess to clone the project.

        If we just installed or initialized conda in this process and it
        wasn't previously, Calkit and DVC will not be on the path,
        so we need to be careful about that.
        """
        cmd = f"calkit clone {self.project_name}"
        platform = get_platform()
        wdir = os.path.join(os.path.expanduser("~"), "calkit")
        os.makedirs(wdir, exist_ok=True)
        if platform == "windows":
            self.process = run_in_powershell(cmd, wdir=wdir)
        else:
            self.process = subprocess.run(cmd, cwd=wdir, shell=True)
        if self.process.returncode != 0:
            QMessageBox.critical(
                self.parent, "Failed to clone", self.process.stdout.decode()
            )


class FileDownloadThread(QThread):
    """A thread to download a file."""

    total_size = Signal(int)
    current_progress = Signal(int)
    success = Signal()

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.downloads_folder = get_downloads_folder()
        os.makedirs(self.downloads_folder, exist_ok=True)
        self.download_fpath = os.path.join(
            self.downloads_folder, os.path.basename(url)
        )

    @property
    def file_exists(self) -> bool:
        return os.path.isfile(self.download_fpath)

    def run(self):
        url = self.url
        filename = self.download_fpath
        read_bytes = 0
        chunk_size = 1024
        # Open the URL address
        with urlopen(url) as r:
            # Tell the window the amount of bytes to be downloaded
            self.total_size.emit(int(r.info()["Content-Length"]))
            with open(filename, "ab") as f:
                while True:
                    # Read a piece of the file we are downloading
                    chunk = r.read(chunk_size)
                    # If the result is `None`, that means data is not
                    # downloaded yet
                    # Just keep waiting
                    if chunk is None:
                        continue
                    # If the result is an empty `bytes` instance, then
                    # the file is complete
                    elif chunk == b"":
                        break
                    # Write into the local file the downloaded chunk
                    f.write(chunk)
                    read_bytes += chunk_size
                    # Tell the window how many bytes we have received
                    self.current_progress.emit(read_bytes)
        # If this line is reached then no exception has occurred in
        # the previous lines
        self.success.emit()


class InstallThread(QThread):
    """A thread to install something, optionally downloading first."""

    def __init__(
        self, url: str | None = None, cmd: list[str] | None = None, parent=None
    ):
        super().__init__(parent)
        self.url = url
        self.cmd = cmd

    def download_installer(self):
        self.downloads_folder = get_downloads_folder()
        os.makedirs(self.downloads_folder, exist_ok=True)
        self.download_fpath = os.path.join(
            self.downloads_folder, os.path.basename(self.url)
        )
        if os.path.isfile(self.download_fpath):
            print("Installer already exists")
            return
        url = self.url
        filename = self.download_fpath
        read_bytes = 0
        chunk_size = 1024
        # Open the URL address
        with urlopen(url) as r:
            # Tell the window the amount of bytes to be downloaded
            with open(filename, "ab") as f:
                while True:
                    # Read a piece of the file we are downloading
                    chunk = r.read(chunk_size)
                    # If the result is `None`, that means data is not
                    # downloaded yet
                    # Just keep waiting
                    if chunk is None:
                        continue
                    # If the result is an empty `bytes` instance, then
                    # the file is complete
                    elif chunk == b"":
                        break
                    # Write into the local file the downloaded chunk
                    f.write(chunk)
                    read_bytes += chunk_size

    def run(self):
        if self.url is not None:
            self.download_installer()
        cmd = self.cmd
        if cmd is None:
            cmd = [self.download_fpath]
        # Split into subcommands based on the presence of &&
        subcommands = [
            list(group)
            for key, group in itertools.groupby(cmd, lambda x: x == "&&")
            if not key
        ]
        for subcommand in subcommands:
            print("Running", subcommand)
            subprocess.run(subcommand)


class NewProjectThread(QThread):
    """A thread to create a new project."""

    def __init__(self, project_data: dict, **kwargs):
        super().__init__(**kwargs)
        self.project_data = project_data
        self.success = None

    def run(self) -> None:
        """Run `calkit new project` to create the project.

        If we just installed or initialized conda in this process and it
        wasn't previously, Calkit and DVC will not be on the path,
        so we need to be careful about that.
        """
        cmd = f"calkit new project {self.project_data['name']} "
        if title := self.project_data["title"]:
            cmd += f"--title '{title}' "
        if description := self.project_data["description"]:
            cmd += f"--description '{description}' "
        template = self.project_data["template"]
        if template != "None":
            cmd += f"--template {template} "
        if self.project_data["cloud"]:
            cmd += "--cloud "
            if self.project_data["public"]:
                cmd += "--public "
        platform = get_platform()
        wdir = os.path.join(os.path.expanduser("~"), "calkit")
        os.makedirs(wdir, exist_ok=True)
        print("Running command:", cmd)
        if platform == "windows":
            self.process = run_in_powershell(cmd, wdir=wdir)
        else:
            self.process = subprocess.run(cmd, cwd=wdir, shell=True)
        if self.process.returncode != 0:
            self.success = False
            QMessageBox.critical(
                self.parent,
                "Failed",
                "Failed to create project.",
            )
        else:
            self.success = True


class ProjectListWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        self.layout.setSpacing(0)
        # Add projects title bar
        self.title_bar = QWidget(self)
        self.title_bar_layout = QHBoxLayout(self.title_bar)
        self.title_bar_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.title_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.title_bar_layout.setSpacing(0)
        self.title = QLabel("Projects")
        self.title.setStyleSheet("font-weight: bold; font-size: 16px;")
        self.title_bar_layout.addWidget(self.title)
        # Add plus icon to add a new project
        # This needs to be disabled if:
        # - Calkit token is not set
        # - Git is not installed
        # - Calkit is not installed
        # - GitHub credentials are not set?
        # TODO
        self.new_project_button = QPushButton(self.title_bar)
        self.new_project_button.setIcon(QIcon.fromTheme("list-add"))
        self.new_project_button.setStyleSheet(
            "padding: 0px; padding-top: 2px; margin: 0px; border: none;"
        )
        self.new_project_button.setCursor(Qt.PointingHandCursor)
        self.new_project_button.setFixedSize(30, 30)
        self.new_project_button.setIconSize(QSize(18, 18))
        self.new_project_button.setToolTip("Create new project")
        self.new_project_button.clicked.connect(self.create_new_project)
        self.title_bar_layout.addWidget(self.new_project_button)
        # Add refresh button to the projects title bar
        self.refresh_projects_button = QPushButton(self.title_bar)
        self.refresh_projects_button.setIcon(QIcon.fromTheme("view-refresh"))
        self.refresh_projects_button.setStyleSheet(
            "padding: 0px; margin: 0px; border: none;"
        )
        self.refresh_projects_button.setCursor(Qt.PointingHandCursor)
        self.refresh_projects_button.setFixedSize(18, 30)
        self.refresh_projects_button.setIconSize(QSize(16, 16))
        self.refresh_projects_button.setToolTip("Refresh projects")
        self.refresh_projects_button.clicked.connect(self.refresh)
        self.title_bar_layout.addWidget(self.refresh_projects_button)
        self.layout.addWidget(self.title_bar)
        # Add a list of folders with "open" icons
        self.list_widget = QListWidget()
        self.refresh()
        self.list_widget.itemDoubleClicked.connect(self.open_project_vs_code)
        # Add right-click context menu to the project list
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(
            self.show_project_context_menu
        )
        self.layout.addWidget(self.list_widget)

    def refresh(self) -> None:
        """Refresh the project list by clearing and re-adding items."""
        print("Refreshing project list")
        self.list_widget.clear()
        self.projects = get_projects()
        self.projects_by_name = {}
        for project in self.projects:
            name = f"{project.owner_name}/{project.project_name}"
            item = QListWidgetItem(self.list_widget)
            widget = QWidget(self)
            layout = QHBoxLayout()
            layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            widget.setLayout(layout)
            project_label = QLabel(name)
            button = QPushButton("📂" if project.wdir is not None else "⬇️")
            button.setStyleSheet(
                "font-size: 12px; padding: 0px; margin: 2px; border: none;"
            )
            button.setCursor(Qt.PointingHandCursor)
            if project.wdir is not None:
                button.setToolTip("Open in VS Code")
                button.clicked.connect(
                    lambda _, i=item: self.open_project_vs_code(i)
                )
            else:
                button.setToolTip("Clone to Calkit projects folder")
                button.clicked.connect(lambda _, i=item: self.clone_project(i))
            layout.addWidget(button)
            layout.addWidget(project_label)
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.UserRole, name)
            self.projects_by_name[name] = project
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

    def show_project_context_menu(self, position):
        """Show a context menu for the project list."""
        # Get the item at the clicked position
        item = self.list_widget.itemAt(position)
        if item is None:
            return  # Do nothing if no item was clicked
        project = self.projects_by_name[item.data(Qt.UserRole)]
        # Create the context menu
        menu = QMenu(self)
        open_vs_code_action = menu.addAction("Open with VS Code")
        open_vs_code_action.triggered.connect(
            lambda: self.open_project_vs_code(item)
        )
        platform = get_platform()
        if platform == "windows":
            open_folder_txt = "Open folder in Explorer"
        elif platform == "mac":
            open_folder_txt = "Open folder in Finder"
        elif platform == "linux":
            open_folder_txt = "Open folder in file explorer"
        open_folder_action = menu.addAction(open_folder_txt)
        open_folder_action.triggered.connect(
            lambda: self.open_project_folder(item)
        )
        clone_action = menu.addAction("Clone to Calkit projects folder")
        clone_action.setEnabled(project.wdir is None)
        clone_action.setToolTip(
            "Clone the project to the Calkit projects folder"
            if project.wdir is None
            else "Project already exists in Calkit projects folder"
        )
        clone_action.triggered.connect(lambda: self.clone_project(item))
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
        # Execute the menu
        menu.exec(self.list_widget.viewport().mapToGlobal(position))

    def open_project_vs_code(self, item) -> None:
        # If VS Code is not installed, show error message dialog
        if not vs_code_installed():
            print("VS Code is not installed")
            QMessageBox.critical(
                self,
                "VS Code not installed",
                "Please install VS Code first.",
            )
            return
        project = self.projects_by_name[item.data(Qt.UserRole)]
        cmd = f"code {project.wdir}"
        subprocess.run(cmd, shell=True)

    def clone_project(self, item: QListWidgetItem) -> None:
        project_name = item.data(Qt.UserRole)
        # Clone in a thread with a progress dialog
        progress = QProgressDialog(
            f"Cloning {project_name}...", None, 0, 0, self
        )
        progress.setWindowTitle("Please wait")
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)  # Show immediately
        progress.setRange(0, 0)  # Indeterminate progress
        progress.show()
        thread = CloneThread(project_name=project_name, parent=self)
        thread.finished.connect(progress.close)
        thread.finished.connect(self.refresh)
        thread.start()

    def open_project_folder(self, item: QListWidgetItem) -> None:
        """Open the project folder in the file explorer."""
        platform = get_platform()
        project = self.projects_by_name[item.data(Qt.UserRole)]
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
            project_name = form_data["name"]
            # Show a progress dialog while the project is being created
            progress = QProgressDialog(
                f"Creating {project_name}...", None, 0, 0, self
            )
            progress.setWindowTitle("Please wait")
            progress.setCancelButton(None)  # Remove the cancel button
            progress.setMinimumDuration(0)  # Show immediately
            progress.setRange(0, 0)  # Indeterminate progress
            progress.show()
            # Close the progress dialog
            self.thread = NewProjectThread(project_data=form_data, parent=self)
            self.thread.finished.connect(
                lambda: self.finish_project_creation(progress)
            )
            self.thread.start()

    def finish_project_creation(self, progress: QProgressDialog) -> None:
        """Finish the project creation process."""
        progress.close()
        if self.thread.success:
            # Refresh the project list
            self.refresh()
            QMessageBox.information(
                self, "Success", "Project created successfully!"
            )


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        # Set title and create layout
        self.setWindowTitle("Calkit Assistant")
        self.layout = QHBoxLayout(self)
        # Add Calkit logo
        self.logo = QLabel()
        # Left half: Setup
        self.setup_widget = QWidget()
        self.setup_layout = QVBoxLayout(self.setup_widget)
        self.setup_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setup_title = QLabel("System setup")
        self.setup_title.setStyleSheet("font-weight: bold; font-size: 16px;")
        self.setup_layout.setSpacing(0)
        self.setup_title_bar = QWidget(self.setup_widget)
        self.setup_title_bar_layout = QHBoxLayout(self.setup_title_bar)
        self.setup_title_bar_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setup_title_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.setup_title_bar_layout.setSpacing(0)
        self.setup_title_bar_layout.addWidget(self.setup_title)
        # Add refresh button to the setup title bar
        self.refresh_setup_button = QPushButton(self.setup_title_bar)
        self.refresh_setup_button.setIcon(QIcon.fromTheme("view-refresh"))
        self.refresh_setup_button.setStyleSheet(
            "padding: 0px; margin: 0px; margin-left: 2px; border: none;"
        )
        self.refresh_setup_button.setCursor(Qt.PointingHandCursor)
        self.refresh_setup_button.setFixedSize(20, 30)
        self.refresh_setup_button.setIconSize(QSize(16, 16))
        self.refresh_setup_button.setToolTip("Refresh setup status")
        self.refresh_setup_button.clicked.connect(self.refresh_setup_status)
        self.setup_title_bar_layout.addWidget(self.refresh_setup_button)
        self.setup_layout.addWidget(self.setup_title_bar)
        # Add setup steps to the left section
        print("Creating setup steps")
        self.setup_step_widgets = make_setup_step_widgets()
        for _, setup_step_widget in self.setup_step_widgets.items():
            setup_step_widget.setMinimumHeight(20)
            self.setup_layout.addWidget(setup_step_widget, stretch=0)
        self.layout.addWidget(self.setup_widget)
        # Right half: Projects
        self.projects_widget = ProjectListWidget(self)
        # Refresh projects widget on Calkit install or token set
        self.setup_step_widgets["calkit"].just_installed.connect(
            self.projects_widget.refresh
        )
        self.setup_step_widgets["calkit-token"].just_set.connect(
            self.projects_widget.refresh
        )
        # Add the projects widget to the layout
        self.layout.addWidget(self.projects_widget)

    def refresh_setup_status(self) -> None:
        """Refresh the status of all setup steps."""
        for _, step in self.setup_step_widgets.items():
            step.refresh()


def restart():
    print("Restarting")
    QApplication.exit(123)


def check_windows_path():
    """Check the `PATH` environmental variable on Windows.

    This is necessary so we don't need to restart after installing certain
    apps.
    """
    path = os.getenv("PATH")
    items = path.split(";")
    required_items = [
        "C:\\Program Files\\Git\\cmd",
        "C:\\Program Files\\Docker\\Docker\\resources\\bin",
        os.path.join(
            os.path.expanduser("~"),
            "AppData",
            "Local",
            "Programs",
            "Microsoft VS Code",
            "bin",
        ),
        os.path.join(
            os.path.expanduser("~"),
            ".local",
            "bin",
        ),
    ]
    for item in required_items:
        if item not in items:
            items.append(item)
    os.environ["PATH"] = ";".join(items)


def run():
    print(f"Starting Calkit Assistant v{__version__}")
    check_windows_path()
    app = QApplication(sys.argv)
    icon = QIcon("resources/icon.ico")
    app.setWindowIcon(icon)
    window = MainWindow()
    window.show()
    exit_code = app.exec()
    if exit_code == 123:
        if get_platform() == "windows":
            # Create a clean environmental variable dict free of PyInstaller
            # changes
            clean_env = os.environ.copy()
            for var in [
                "PYTHONHOME",
                "PYTHONPATH",
                "_MEIPASS2",
                "_PYI_APPLICATION_HOME_DIR",
                "_PYI_ARCHIVE_FILE",
                "_PYI_PARENT_PROCESS_LEVEL",
                "QT_PLUGIN_PATH",
                "QML2_IMPORT_PATH",
            ]:
                clean_env.pop(var, None)
            cmd = ["start", "cmd", "/c", sys.executable, *sys.argv]
            print("Using command:", cmd)
            subprocess.Popen(cmd, shell=True, env=clean_env)
        else:
            os.execl(sys.executable, sys.executable, *sys.argv)
        sys.exit(0)
    else:
        sys.exit(exit_code)


if __name__ == "__main__":
    run()
