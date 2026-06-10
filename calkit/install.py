"""Registry of native install scripts for common Calkit dependencies.

When an ``app`` dependency is missing during ``calkit check dependencies``
(or ``calkit run`` preflight), we look up the app here and -- on an
interactive TTY -- offer to run the upstream installer for the current
platform so users don't have to leave the terminal to satisfy a fresh
clone's requirements.

Each entry pairs an install command with the directory the installer
writes the binary into, so we can prepend that directory to ``PATH`` for
the rest of this process. That way the very next dependency check (and
the pipeline itself) sees the newly-installed tool without requiring a
shell restart.

The registry is intentionally small for now. Adding a new entry is a
matter of finding the upstream one-liner installer and the directory it
writes to.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Literal, TypedDict


class Installer(TypedDict):
    script: str
    # Directory the installer writes the new binary into; prepended to
    # ``PATH`` so the in-process re-check can find it.
    path_add: str


Platform = Literal["unix", "windows"]


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
        "script": (
            "winget install --id Rustlang.Rustup -e "
            "--accept-source-agreements --accept-package-agreements"
        ),
        "path_add": "~\\.cargo\\bin",
    },
}
_JULIAUP_INSTALLER: dict[Platform, Installer] = {
    "unix": {
        "script": "curl -fsSL https://install.julialang.org | sh -s -- -y",
        "path_add": "~/.juliaup/bin",
    },
    "windows": {
        "script": (
            "winget install --id Julialang.Juliaup -e "
            "--accept-source-agreements --accept-package-agreements"
        ),
        "path_add": "~\\.juliaup\\bin",
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
}
# Aliases for the binaries users actually invoke / list as deps; sharing
# the same installer dict by reference keeps the entries in lockstep.
INSTALLERS["cargo"] = _RUSTUP_INSTALLER
INSTALLERS["julia"] = _JULIAUP_INSTALLER


# Apps that are known to be unsupported on a given platform, mapped to the
# message the CLI should surface instead of the generic "no installer"
# error. Nix doesn't run natively on Windows -- users need WSL2 -- so we
# steer them there explicitly rather than letting them watch a download
# fail.
_PLATFORM_UNSUPPORTED: dict[str, dict[Platform, str]] = {
    "nix": {
        "windows": (
            "Nix is not supported natively on Windows. Run Calkit inside "
            "WSL2 (https://learn.microsoft.com/en-us/windows/wsl/install) "
            "and install Nix there."
        ),
    },
}


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
    return "windows" if sys.platform.startswith("win") else "unix"


def get_installer(app: str) -> Installer | None:
    """Return the installer entry for ``app`` on the current platform.

    Returns ``None`` when the app isn't in the registry, which the caller
    treats as "no auto-install available; just report the missing dep."
    """
    entry = INSTALLERS.get(app)
    if entry is None:
        return None
    return entry.get(_current_platform())


def install(app: str) -> bool:
    """Run the registered install script for ``app`` and update ``PATH``.

    Returns True iff the install command exits 0 AND the binary is then
    findable on ``PATH`` (after prepending the installer's known output
    directory). Both must hold -- exiting 0 isn't enough if the binary
    landed somewhere we still can't see.
    """
    entry = get_installer(app)
    if entry is None:
        return False
    # capture=False so installers can stream their own progress output
    # and (for some) take TTY input.
    result = subprocess.run(entry["script"], shell=True)
    if result.returncode != 0:
        return False
    path_add = os.path.expanduser(entry["path_add"])
    if path_add and os.path.isdir(path_add):
        current_path = os.environ.get("PATH", "")
        # Prepend so our new install wins over any stale copy.
        if path_add not in current_path.split(os.pathsep):
            os.environ["PATH"] = path_add + os.pathsep + current_path
    return shutil.which(app) is not None


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
