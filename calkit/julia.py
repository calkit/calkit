"""Functionality for working with Julia."""

import shutil
import subprocess


def ensure_startup_file_disabled_in_command(cmd: list[str]) -> list[str]:
    """Ensure Julia startup files are disabled for deterministic execution.

    Removes any existing --startup-file arguments and ensures --startup-file=no
    is present in the correct position.
    """
    if not cmd:
        raise ValueError("Command list is empty")
    if cmd[0] != "julia":
        raise ValueError("This doesn't appear to be a Julia command")

    # Remove any existing --startup-file arguments (e.g., --startup-file=yes)
    filtered_cmd = [arg for arg in cmd if not arg.startswith("--startup-file")]

    # Determine insertion position (after juliaup version specifier if present)
    insert_idx = (
        2 if len(filtered_cmd) > 1 and filtered_cmd[1].startswith("+") else 1
    )

    # Insert --startup-file=no at the correct position
    return (
        filtered_cmd[:insert_idx]
        + ["--startup-file=no"]
        + filtered_cmd[insert_idx:]
    )


def check_version_in_command(cmd: list[str]) -> list[str]:
    """Whether to include the version in the command.

    This is only possible if ``juliaup`` is installed. If it's not installed,
    we will return the command without the version spec as long as it matches
    the current Julia version.
    """
    if not cmd:
        raise ValueError("Command list is empty")
    if cmd[0] != "julia":
        raise ValueError("This doesn't appear to be a Julia command")
    if len(cmd) < 2:
        raise ValueError(
            "Command must have at least 2 elements (julia and version)"
        )
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
    """Get the current Julia version with startup files disabled."""
    try:
        cmd = ensure_startup_file_disabled_in_command(["julia", "--version"])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError("Julia executable not found") from exc
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if stderr:
            raise ValueError(f"Failed to run 'julia --version': {stderr}")
        raise ValueError("Failed to run 'julia --version'")
    stdout = (result.stdout or "").strip()
    if not stdout:
        raise ValueError("No output from 'julia --version'")
    parts = stdout.split()
    if not parts:
        raise ValueError("Unexpected output from 'julia --version'")
    return parts[-1]


def current_version_is_compatible(target_version: str) -> bool:
    """Check if the current Julia version is compatible with the target
    version.
    """
    current_version = get_version()
    return current_version[: len(target_version)] == target_version
