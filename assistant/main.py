"""A GUI to help users manage their system.

This app helps install and track system-wide dependencies and open projects
in their editor of choice.
"""

import glob
import os
import platform
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
from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
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

ryaml = ruamel.yaml.YAML()
ryaml.indent(mapping=2, sequence=4, offset=2)
ryaml.preserve_quotes = True
ryaml.width = 70


def check_dep_exists(name: str) -> bool:
    cmd = [name]
    # Executables with non-conventional CLIs
    if name == "matlab":
        cmd.append("-help")
    else:
        # Fall back to simply calling ``--version``
        cmd.append("--version")
    try:
        subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except FileNotFoundError:
        return False


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
    except FileNotFoundError:
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
) -> subprocess.CompletedProcess:
    if as_admin:
        cmd = f"Start-Process PowerShell -Verb RunAs -ArgumentList '{cmd}'"
    return subprocess.run(
        ["powershell", "-Command", cmd],
        capture_output=capture_output,
        check=check,
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

    def __init__(self):
        super().__init__()
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
            self.label.setText(self.txt_set)


class QWidgetABCMeta(ABCMeta, type(QWidget)):
    pass


class DependencyInstall(QWidget, metaclass=QWidgetABCMeta):
    """An abstract base class to represent an installed dependency."""

    def __init__(self, child_steps: list[QWidget] = []):
        super().__init__()
        self.child_steps = child_steps
        self.layout = make_setup_step_layout(self)
        self.txt_installed = f"Install {self.dependency_name}: ✅"
        self.txt_not_installed = f"Install {self.dependency_name}: ❌"
        installed = self.installed
        for step in self.child_steps:
            step.setEnabled(installed)
        self.label = QLabel(
            self.txt_installed if installed else self.txt_not_installed
        )
        self.layout.addWidget(self.label)
        if not installed:
            self.install_button = QPushButton("⬇️")
            self.install_button.setCursor(Qt.PointingHandCursor)
            self.install_button.setToolTip("Install")
            self.install_button.setFixedSize(18, 18)
            self.install_button.setStyleSheet(
                "font-size: 12px; padding: 0px; margin: 0px; border: none;"
            )
            self.install_button.clicked.connect(self.install)
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
        install_progress.setWindowTitle("Calkit")
        install_thread.finished.connect(install_progress.close)
        install_thread.finished.connect(self.finish_install)
        install_thread.start()
        return True

    def finish_install(self):
        """After attempting to install, run this."""
        installed = self.installed
        if installed:
            self.layout.removeWidget(self.install_button)
            self.install_button.deleteLater()
            self.install_button = None
            # Update label to show installed
            self.label.setText(self.txt_installed)
            for step in self.child_steps:
                step.setEnabled(True)
        else:
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
        cmd = "wsl --install -d Ubuntu"
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
        code_path = shutil.which("code")
        if code_path is None:
            return False
        try:
            subprocess.check_output([code_path, "--version"])
            return True
        except subprocess.CalledProcessError:
            return False

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


class GitInstall(DependencyInstall):
    @property
    def dependency_name(self) -> str:
        return "Git"

    @property
    def installed(self) -> bool:
        if get_platform() == "windows":
            process = run_in_git_bash("git --version")
            return process.returncode == 0
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
            subprocess.run(self.cmd + [self.key, text])
            self.label.setText(self.txt_set)


class CondaInit(QWidget):
    """A widget to ensure Conda has been initialized in the relevant shell."""

    def __init__(self):
        super().__init__()
        self.layout = make_setup_step_layout(self)
        is_done = self.is_done
        self.txt_not_set = "Run conda init: ❌"
        self.txt_set = "Run conda init: ✅"
        self.label = QLabel(self.txt_set if is_done else self.txt_not_set)
        self.layout.addWidget(self.label)
        if not is_done:
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

    @property
    def is_done(self) -> bool:
        platform = get_platform()
        if platform == "windows":
            print("Checking that Git Bash can run Conda")
            try:
                process = run_in_git_bash("conda --version")
                process.check_returncode()
            except Exception as e:
                print(f"Failed to run Conda in Git Bash: {e}")
                return False
            print("Checking that Powershell can run Conda")
            try:
                process = run_in_powershell("conda --version")
                process.check_returncode()
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
                "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned",
                as_admin=True,
                capture_output=False,
                check=False,
            )
            conda_exe = os.path.join(find_conda_prefix(), "Scripts", "conda")
            # Convert to posix path
            conda_exe = Path(conda_exe).as_posix()
            run_in_git_bash(f"{conda_exe} init bash powershell")
        else:
            conda_exe = os.path.join(find_conda_prefix(), "bin", "conda")
            cmd = [conda_exe, "init"]
            subprocess.run(cmd)
        if self.is_done:
            self.layout.removeWidget(self.run_button)
            self.run_button.deleteLater()
            self.run_button = None
            # Update label to show it's done
            self.label.setText(self.txt_set)
        else:
            self.run_button.setEnabled(True)
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
        exe = os.path.join(get_conda_scripts_dir(), "calkit")
        return check_dep_exists(exe)

    @property
    def install_command(self) -> list[str]:
        pip_exe = os.path.join(get_conda_scripts_dir(), "pip")
        return [pip_exe, "install", "--upgrade", "calkit-python"]


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
        print("Adding Homebrew install widget")
        steps["homebrew"] = HomebrewInstall()
    elif platform == "windows":
        print("Adding WSL install widget")
        wsl_install = WSLInstall()
        steps["wsl"] = wsl_install
    # Install and configure Git
    print("Adding Git config widgets")
    git_user_name = GitConfigStep(
        key="user.name", pretty_name="full name", wsl=False
    )
    git_user_email = GitConfigStep(
        key="user.email", pretty_name="email address", wsl=False
    )
    print("Adding Git install widget")
    git_install = GitInstall(child_steps=[git_user_name, git_user_email])
    steps["git"] = git_install
    steps["git-user"] = git_user_name
    steps["git-email"] = git_user_email
    # TODO: Install everything in WSL if on Windows?
    # Install Docker
    print("Adding Docker install widget")
    steps["docker"] = DockerInstall()
    # TODO: Ensure Docker is running
    # We can use `docker desktop status` and `docker desktop start` for this
    # However, this is not necessary on Linux
    # TODO: Ensure Docker permissions are set on Linux
    # TODO: Ensure we have GitHub credentials?
    # Install Miniforge and check that shell is initialized
    print("Adding Calkit install widget")
    calkit_install = CalkitInstall()
    print("Adding Conda init widget")
    conda_init = CondaInit()
    print("Adding Conda install widget")
    steps["miniforge"] = CondaInstall(child_steps=[conda_init, calkit_install])
    steps["conda-init"] = conda_init
    # Install uv
    print("Adding uv install widget")
    steps["uv"] = UvInstall()
    # Install Calkit inside Miniforge base environment
    steps["calkit"] = calkit_install
    # Ensure Calkit token is set
    print("Adding Calkit token widget")
    steps["calkit-token"] = CalkitToken()
    # Install VS Code
    print("Adding VS Code install widget")
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


class SubprocessThread(QThread):
    """A thread to run a subprocess."""

    def __init__(self, cmd: list[str], wdir: str = None, **kwargs):
        super().__init__(**kwargs)
        self.cmd = cmd
        self.wdir = wdir

    def run(self) -> None:
        """Run the subprocess."""
        self.process = subprocess.run(self.cmd, cwd=self.wdir)
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
        subprocess.run(cmd)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        # Set title and create layout
        self.setWindowTitle("Calkit")
        self.layout = QHBoxLayout(self)
        # Add Calkit logo
        self.logo = QLabel()
        # Left half: Setup
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
        # TODO
        self.new_project_button = QPushButton(self.projects_title_bar)
        self.new_project_button.setIcon(QIcon.fromTheme("list-add"))
        self.new_project_button.setStyleSheet(
            "font-size: 10px; padding: 0px; padding-top: 2px; margin: 0px; "
            "border: none;"
        )
        self.new_project_button.setCursor(Qt.PointingHandCursor)
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
        self.refresh_projects_button.setCursor(Qt.PointingHandCursor)
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
            item = QListWidgetItem(self.project_list_widget)
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
            self.project_list_widget.addItem(item)
            self.project_list_widget.setItemWidget(item, widget)

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
        project = self.projects_by_name[item.data(Qt.UserRole)]
        cmd = f"code {project.wdir}"
        subprocess.run(cmd, shell=True)

    def show_project_context_menu(self, position):
        """Show a context menu for the project list."""
        # Get the item at the clicked position
        item = self.project_list_widget.itemAt(position)
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
        menu.exec(self.project_list_widget.viewport().mapToGlobal(position))

    def clone_project(self, item: QListWidgetItem) -> None:
        project_name = item.data(Qt.UserRole)
        exe = os.path.join(get_conda_scripts_dir(), "calkit")
        cmd = [exe, "clone", project_name]
        wdir = os.path.join(os.path.expanduser("~"), "calkit")
        os.makedirs(wdir, exist_ok=True)
        # Clone in a thread with a progress dialog
        progress = QProgressDialog(
            f"Cloning {project_name}...", None, 0, 0, self
        )
        progress.setWindowTitle("Please wait")
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)  # Show immediately
        progress.setRange(0, 0)  # Indeterminate progress
        progress.show()
        thread = SubprocessThread(cmd=cmd, wdir=wdir, parent=self)
        thread.finished.connect(progress.close)
        thread.finished.connect(self.refresh_project_list)
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
            project_name = form_data["project_name"]
            # TODO: Create the project using the CLI method
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
    icon = QIcon("resources/icon.ico")
    app.setWindowIcon(icon)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
