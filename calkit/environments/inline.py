"""Environments Python scripts declare for themselves in inline metadata.

A script's ``# /// script`` block (PEP 723) says what it needs, and uv runs it
in that environment, locked in a ``.lock`` file beside the script, which is
uv's convention.
"""

from __future__ import annotations

import os
import re
import subprocess

# From PEP 723
METADATA_REGEX = re.compile(
    r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$"
)


def has_metadata(script_path: str) -> bool:
    """Whether a Python script declares its environment in a script block."""
    with open(script_path, encoding="utf-8") as f:
        text = f.read()
    return any(
        m.group("type") == "script" for m in METADATA_REGEX.finditer(text)
    )


def get_lock_path(script_path: str) -> str:
    """Return the path of a script's lock file, where uv keeps it."""
    return script_path + ".lock"


def lock(script_path: str, force: bool = False, verbose: bool = False) -> str:
    """Lock a script's environment if it may have changed since it was,
    returning the lock file's path.

    That's judged by modification times, so it's fast enough to do before
    every run or status check; uv updates a lock that's already current
    without rewriting it, so it's touched after.
    """
    lock_path = get_lock_path(script_path)
    if not force and os.path.isfile(lock_path):
        if os.path.getmtime(lock_path) >= os.path.getmtime(script_path):
            return lock_path
    if not has_metadata(script_path):
        raise ValueError(
            f"{script_path} has no '# /// script' block declaring its "
            "environment"
        )
    try:
        res = subprocess.run(
            ["uv", "lock", "--script", script_path],
            capture_output=not verbose,
            text=True,
        )
    except FileNotFoundError:
        raise RuntimeError(f"uv is needed to lock {script_path}")
    if res.returncode != 0:
        raise RuntimeError(
            f"Failed to lock {script_path}:\n{(res.stderr or '').strip()}"
        )
    os.utime(lock_path)
    return lock_path


def get_stage_script_path(stage: dict) -> str | None:
    """Return the path of a stage's script, if it's a Python script stage
    run in the environment the script declares.
    """
    from calkit.models.pipeline import INLINE_ENVIRONMENT

    if stage.get("kind") != "python-script":
        return None
    if stage.get("environment") not in (None, INLINE_ENVIRONMENT):
        return None
    script_path = stage.get("script_path")
    if not script_path:
        return None
    return os.path.normpath(os.path.join(stage.get("wdir") or "", script_path))
