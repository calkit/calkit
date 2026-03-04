"""Functionality for working with Julia."""

import shutil
import subprocess


def check_version_in_command(cmd: list[str]) -> list[str]:
    """Whether to include the version in the command.

    This is only possible if ``juliaup`` is installed. If it's not installed,
    we will return the command without the version spec as long as it matches
    the current Julia version.
    """
    if cmd[0] != "julia":
        raise ValueError("This doesn't appear to be a Julia command")
    if not cmd[1].startswith("+"):
        raise ValueError("There is no target Julia version in this command")
    if shutil.which("juliaup") is not None:
        # Always include the version if juliaup is available, since it can
        # install on the fly for us
        return cmd
    # Find the version in the command
    target_version = cmd[1][1:]
    if not current_version_is_compatible(target_version):
        raise ValueError("Current Julia version doesn't match")
    return cmd[0:1] + cmd[2:]


def get_version() -> str:
    """Get the current Julia version."""
    return (
        subprocess.run(["julia", "--version"], capture_output=True, text=True)
        .stdout.strip()
        .split()[-1]
    )


def current_version_is_compatible(target_version: str) -> bool:
    """Check if the current Julia version is compatible with the target
    version.
    """
    current_version = get_version()
    return current_version[: len(target_version)] == target_version
