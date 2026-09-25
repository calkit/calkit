"""Registry of native install scripts for common Calkit dependencies.

When an ``app`` requirement is missing during ``calkit check reqs``
(or ``calkit run`` preflight), we look up the app here and -- on an
interactive TTY -- offer to run the upstream installer for the current
platform so users don't have to leave the terminal to satisfy a fresh
clone's requirements.

Each entry pairs an install command with the directory the installer
writes the binary into, so we can prepend that directory to ``PATH`` for
the rest of this process. That way the very next dependency check (and
the pipeline itself) sees the newly-installed tool without requiring a
shell restart.

Installing is always opt-in: nothing here runs without the user saying
yes, or passing ``--yes`` to ``calkit install``. Every install Calkit
performs is recorded in ``~/.calkit/installed.json`` so there's a record
of what it changed on the machine.

Entries are keyed by the binary the app provides, since that's both what
a project declares as an ``app`` requirement and what we check for
afterward. Where a platform's package manager is the sensible way in
(Homebrew on macOS, winget on Windows), the entry names it in
``requires`` so it's installed first.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Literal, TypedDict


class _InstallerRequired(TypedDict):
    script: str
    # Directory (or directories) the installer writes the new binary into;
    # prepended to ``PATH`` so the in-process re-check can find it. May use
    # ``~``, environment variables, and a glob for versioned directories.
    path_add: str | list[str]


class Installer(_InstallerRequired, total=False):
    # Registry apps that must be present first, e.g., Homebrew before
    # anything installed through it
    requires: list[str]


# ``unix`` is the fallback for both ``mac`` and ``linux`` when an entry
# doesn't need to tell them apart
Platform = Literal["mac", "linux", "windows", "unix"]

# Homebrew's prefix differs between Apple Silicon and Intel
_BREW_BINS = ["/opt/homebrew/bin", "/usr/local/bin"]
_WINGET = (
    "winget install -e --accept-source-agreements "
    "--accept-package-agreements --id "
)


# rustup installs the whole Rust toolchain (cargo + rustc); juliaup
# installs julia. Defined out-of-band so the binary-name aliases below
# share the same dict by reference and stay in lockstep.
_RUSTUP_INSTALLER: dict[Platform, Installer] = {
    "unix": {
        "script": (
            "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs "
            "| sh -s -- -y --default-toolchain stable"
        ),
        "path_add": "~/.cargo/bin",
    },
    "windows": {
        # winget is the path of least resistance on modern Windows; the
        # upstream rustup-init.exe download is not a one-liner.
        "script": _WINGET + "Rustlang.Rustup",
        "path_add": "~\\.cargo\\bin",
    },
}
_JULIAUP_INSTALLER: dict[Platform, Installer] = {
    "unix": {
        "script": "curl -fsSL https://install.julialang.org | sh -s -- -y",
        "path_add": "~/.juliaup/bin",
    },
    "windows": {
        "script": _WINGET + "Julialang.Juliaup",
        "path_add": "~\\.juliaup\\bin",
    },
}
# Miniforge in batch mode, into the default prefix and without touching
# shell startup files; Calkit finds conda by its usual locations, so no
# ``conda init`` is needed
_MINIFORGE_INSTALLER: dict[Platform, Installer] = {
    "unix": {
        "script": (
            'curl -fsSL -o "${TMPDIR:-/tmp}/Miniforge3.sh" '
            '"https://github.com/conda-forge/miniforge/releases/latest/'
            'download/Miniforge3-$(uname)-$(uname -m).sh" '
            '&& bash "${TMPDIR:-/tmp}/Miniforge3.sh" -b -p "$HOME/miniforge3"'
        ),
        "path_add": "~/miniforge3/bin",
    },
    "windows": {
        "script": (
            "powershell -ExecutionPolicy ByPass -c "
            '"irm -OutFile $env:TEMP\\Miniforge3.exe '
            "https://github.com/conda-forge/miniforge/releases/latest/"
            "download/Miniforge3-Windows-x86_64.exe; "
            "Start-Process -Wait $env:TEMP\\Miniforge3.exe -ArgumentList "
            "'/S','/InstallationType=JustMe','/RegisterPython=0',"
            "('/D=' + $env:USERPROFILE + '\\miniforge3')\""
        ),
        "path_add": "~\\miniforge3\\condabin",
    },
}
_R_INSTALLER: dict[Platform, Installer] = {
    "mac": {
        "script": "brew install --cask r",
        "path_add": _BREW_BINS,
        "requires": ["brew"],
    },
    "windows": {
        "script": _WINGET + "RProject.R",
        # The R installer doesn't add itself to PATH, and the directory is
        # versioned
        "path_add": "%ProgramFiles%\\R\\R-*\\bin",
    },
}


# name -> platform -> Installer
INSTALLERS: dict[str, dict[Platform, Installer]] = {
    "pixi": {
        "unix": {
            "script": "curl -fsSL https://pixi.sh/install.sh | sh",
            "path_add": "~/.pixi/bin",
        },
        "windows": {
            "script": (
                "powershell -ExecutionPolicy ByPass -c "
                '"iwr -useb https://pixi.sh/install.ps1 | iex"'
            ),
            "path_add": "~/.pixi/bin",
        },
    },
    "uv": {
        "unix": {
            "script": "curl -LsSf https://astral.sh/uv/install.sh | sh",
            "path_add": "~/.local/bin",
        },
        "windows": {
            "script": (
                "powershell -ExecutionPolicy ByPass -c "
                '"irm https://astral.sh/uv/install.ps1 | iex"'
            ),
            "path_add": "~/.local/bin",
        },
    },
    "rustup": _RUSTUP_INSTALLER,
    "juliaup": _JULIAUP_INSTALLER,
    # Determinate Systems' Nix installer ships flakes on by default and
    # uninstalls cleanly. ``--no-confirm`` makes it scriptable; the binary
    # ends up on the multi-user default profile path so we can prepend it
    # to PATH for the in-process re-check.
    "nix": {
        "unix": {
            "script": (
                "curl --proto '=https' --tlsv1.2 -fsSL "
                "https://install.determinate.systems/nix "
                "| sh -s -- install --no-confirm"
            ),
            "path_add": "/nix/var/nix/profiles/default/bin",
        },
    },
    # Package managers, which the entries below install through
    "brew": {
        "mac": {
            "script": (
                '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com'
                '/Homebrew/install/HEAD/install.sh)"'
            ),
            "path_add": _BREW_BINS,
        },
    },
    "choco": {
        "windows": {
            # Chocolatey has to be installed from an elevated shell, so
            # this opens one (with a UAC prompt) and waits for it
            "script": (
                'powershell -Command "Start-Process powershell -Verb runAs '
                "-Wait -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass',"
                "'-Command','irm https://community.chocolatey.org/install.ps1 "
                "| iex'\""
            ),
            "path_add": "%ProgramData%\\chocolatey\\bin",
        },
    },
    "git": {
        "mac": {
            "script": "brew install git",
            "path_add": _BREW_BINS,
            "requires": ["brew"],
        },
        "windows": {
            "script": _WINGET + "Git.Git --source winget",
            "path_add": "%ProgramFiles%\\Git\\cmd",
        },
    },
    "docker": {
        "mac": {
            "script": "brew install --cask docker",
            "path_add": _BREW_BINS,
            "requires": ["brew"],
        },
        "linux": {
            # Docker's convenience script; it needs root, and afterward the
            # user may still need adding to the docker group
            "script": "curl -fsSL https://get.docker.com | sudo sh",
            "path_add": "/usr/bin",
        },
        "windows": {
            "script": _WINGET + "Docker.DockerDesktop",
            "path_add": "%ProgramFiles%\\Docker\\Docker\\resources\\bin",
        },
    },
    "code": {
        "mac": {
            "script": "brew install --cask visual-studio-code",
            "path_add": _BREW_BINS,
            "requires": ["brew"],
        },
        "windows": {
            "script": _WINGET + "Microsoft.VisualStudioCode",
            "path_add": "%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\bin",
        },
    },
    "conda": _MINIFORGE_INSTALLER,
    "R": _R_INSTALLER,
}
# Aliases for the binaries users actually invoke / list as deps; sharing
# the same installer dict by reference keeps the entries in lockstep.
INSTALLERS["cargo"] = _RUSTUP_INSTALLER
INSTALLERS["julia"] = _JULIAUP_INSTALLER
INSTALLERS["mamba"] = _MINIFORGE_INSTALLER
INSTALLERS["Rscript"] = _R_INSTALLER


# Apps that are known to be unsupported on a given platform, mapped to the
# message the CLI should surface instead of the generic "no installer"
# error. Nix doesn't run natively on Windows -- users need WSL2 -- so we
# steer them there explicitly rather than letting them watch a download
# fail. Linux has too many package managers to pick one for the apps
# that don't ship their own installer, so those say what to run instead.
_PLATFORM_UNSUPPORTED: dict[str, dict[Platform, str]] = {
    "nix": {
        "windows": (
            "Nix is not supported natively on Windows. Run Calkit inside "
            "WSL2 (https://learn.microsoft.com/en-us/windows/wsl/install) "
            "and install Nix there."
        ),
    },
    "brew": {
        "linux": "Homebrew is only used on macOS here.",
        "windows": "Homebrew is only used on macOS here.",
    },
    "choco": {
        "mac": "Chocolatey is Windows-only.",
        "linux": "Chocolatey is Windows-only.",
    },
    "git": {
        "linux": (
            "Install Git with your system package manager, e.g., "
            "'sudo apt install git'."
        ),
    },
    "code": {
        "linux": (
            "Install VS Code with your system package manager; see "
            "https://code.visualstudio.com/docs/setup/linux."
        ),
    },
    "R": {
        "linux": (
            "Install R with your system package manager, e.g., "
            "'sudo apt install r-base', or see https://cloud.r-project.org."
        ),
    },
}
_PLATFORM_UNSUPPORTED["Rscript"] = _PLATFORM_UNSUPPORTED["R"]


def get_unsupported_message(app: str) -> str | None:
    """Return a platform-unsupported message for ``app``, if any.

    This is distinct from "no installer registered": the app is known but
    cannot be installed on this platform via this tool. Callers should
    surface this message before falling back to the generic "no installer"
    error.
    """
    platform_messages = _PLATFORM_UNSUPPORTED.get(app)
    if platform_messages is None:
        return None
    return platform_messages.get(_current_platform())


def _current_platform() -> Platform:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def get_installer(app: str) -> Installer | None:
    """Return the installer entry for ``app`` on the current platform.

    Returns ``None`` when the app isn't in the registry, which the caller
    treats as "no auto-install available; just report the missing dep."
    """
    entry = INSTALLERS.get(app)
    if entry is None:
        return None
    platform = _current_platform()
    installer = entry.get(platform)
    if installer is None and platform != "windows":
        installer = entry.get("unix")
    return installer


def get_install_log_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".calkit", "installed.json")


def read_install_log() -> list[dict]:
    """Return the record of apps Calkit has installed on this machine."""
    fpath = get_install_log_path()
    if not os.path.isfile(fpath):
        return []
    with open(fpath, encoding="utf-8") as f:
        return list(json.load(f))


def record_install(app: str, entry: Installer) -> None:
    """Append ``app`` to the record of what Calkit installed.

    The script is kept alongside the name, since what an installer did is
    what someone undoing it later needs to know.
    """
    from datetime import datetime, timezone

    log = read_install_log()
    log.append(
        {
            "app": app,
            "platform": _current_platform(),
            "installed_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
            "script": entry["script"],
        }
    )
    fpath = get_install_log_path()
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
        f.write("\n")


def _expand_path(path: str) -> str:
    """Resolve ``~``, environment variables, and a glob to one directory."""
    expanded = os.path.expandvars(os.path.expanduser(path))
    if any(c in expanded for c in "*?["):
        # Newest version last, which is the one we want on PATH; compared
        # numerically so 4.10 sorts after 4.9
        matches = sorted(
            glob.glob(expanded),
            key=lambda p: [int(n) for n in re.findall(r"\d+", p)],
        )
        if matches:
            return matches[-1]
    return expanded


def _add_to_path(entry: Installer) -> None:
    paths = entry["path_add"]
    if isinstance(paths, str):
        paths = [paths]
    for path in paths:
        path_add = _expand_path(path)
        if not os.path.isdir(path_add):
            continue
        current_path = os.environ.get("PATH", "")
        # Prepend so our new install wins over any stale copy
        if path_add not in current_path.split(os.pathsep):
            os.environ["PATH"] = path_add + os.pathsep + current_path


def install(app: str) -> bool:
    """Run the registered install script for ``app`` and update ``PATH``.

    Anything the entry ``requires`` is installed first. Returns True iff
    the install command exits 0 AND the binary is then findable on
    ``PATH`` (after prepending the installer's known output directory).
    Both must hold -- exiting 0 isn't enough if the binary landed
    somewhere we still can't see.
    """
    entry = get_installer(app)
    if entry is None:
        return False
    for req in entry.get("requires", []):
        if shutil.which(req) is None and not install(req):
            return False
    # capture=False so installers can stream their own progress output
    # and (for some) take TTY input.
    result = subprocess.run(entry["script"], shell=True)
    if result.returncode != 0:
        return False
    _add_to_path(entry)
    ok = shutil.which(app) is not None
    if ok:
        record_install(app, entry)
    return ok


def prompt_and_install(app: str, *, interactive: bool) -> bool:
    """Ask the user (if on a TTY) whether to install ``app`` and do it.

    Returns True iff the app is installed and on ``PATH`` afterward.
    Non-interactive callers always get False here -- they're expected to
    surface the missing dep so the user can install it themselves.
    """
    entry = get_installer(app)
    if entry is None:
        return False
    if not interactive:
        print(
            f"  An installer is available; to install, run:  {entry['script']}"
        )
        return False
    # Each prerequisite gets its own prompt, so saying yes to one thing
    # never silently installs another
    for req in entry.get("requires", []):
        if shutil.which(req) is None:
            print(f"'{app}' is installed with '{req}', which is missing.")
            if not prompt_and_install(req, interactive=True):
                return False
    try:
        answer = (
            input(f"Install '{app}' now via the upstream installer? [Y/n] ")
            .strip()
            .lower()
        )
    except EOFError:
        answer = "n"
    if answer not in ("", "y", "yes"):
        print(f"  Skipped. To install, run:  {entry['script']}")
        return False
    ok = install(app)
    if not ok:
        print(
            f"  Install ran but '{app}' is still not on PATH; restart your "
            "shell and re-run."
        )
    return ok
