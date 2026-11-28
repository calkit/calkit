"""Environments Python scripts declare for themselves in inline metadata.

A script's ``# /// script`` block (PEP 723) says what it needs, and uv runs it
in that environment, locked in a ``.lock`` file beside the script, which is
uv's convention.
"""

from __future__ import annotations

import os
import posixpath
import re
import subprocess
from pathlib import Path

# From PEP 723
METADATA_REGEX = re.compile(
    r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$"
)


def get_metadata(script_path: str) -> dict | None:
    """Return what a Python script's ``# /// script`` block declares, if it
    has one.
    """
    import tomllib

    with open(script_path, encoding="utf-8") as f:
        text = f.read()
    for m in METADATA_REGEX.finditer(text):
        if m.group("type") != "script":
            continue
        content = "".join(
            line[2:] if line.startswith("# ") else line[1:]
            for line in m.group("content").splitlines(keepends=True)
        )
        return tomllib.loads(content)
    return None


def get_lock_path(script_path: str) -> str:
    """Return the path of a script's lock file, where uv keeps it."""
    return script_path + ".lock"


def get_python_version_path(
    script_path: str, project_dir: str = ""
) -> str | None:
    """Return the path of the ``.python-version`` uv picks a script's
    interpreter with, i.e., the first in its directory or those above it,
    up to the project's.

    Paths are relative to the project.
    """
    rel_dir = posixpath.dirname(
        posixpath.normpath(Path(script_path).as_posix())
    )
    while True:
        path = posixpath.join(rel_dir, ".python-version")
        if os.path.isfile(os.path.join(project_dir, path)):
            return path
        if not rel_dir:
            return None
        rel_dir = posixpath.dirname(rel_dir)


def lock_is_current(script_path: str) -> bool:
    """Whether a script's lock is newer than it and its ``.python-version``,
    which is fast enough to check before every run or status check.

    The path is relative to the project, which is the working directory.
    """
    lock_path = get_lock_path(script_path)
    if not os.path.isfile(lock_path):
        return False
    lock_mtime = os.path.getmtime(lock_path)
    paths = [script_path, get_python_version_path(script_path)]
    return all(lock_mtime >= os.path.getmtime(p) for p in paths if p)


def lock(script_path: str, force: bool = False, verbose: bool = False) -> str:
    """Lock a script's environment unless its lock is current, returning the
    lock file's path.

    The path is relative to the project, which is the working directory.
    uv leaves a lock that's already current as it is, so it's touched after,
    to be skipped next time.
    """
    lock_path = get_lock_path(script_path)
    if not force and lock_is_current(script_path):
        return lock_path
    metadata = get_metadata(script_path)
    if metadata is None:
        raise ValueError(
            f"{script_path} has no '# /// script' block declaring its "
            "environment"
        )
    if "requires-python" not in metadata:
        # uv would lock it for whichever Python it found, so the lock would
        # be out of date on a machine with another
        raise ValueError(
            f"{script_path} declares no 'requires-python' in its "
            "'# /// script' block"
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
    """Return the project-relative path of a stage's script, if it's a
    Python script stage run in the environment the script declares.
    """
    from calkit.models.pipeline import INLINE_ENVIRONMENT_NAME

    if stage.get("kind") != "python-script":
        return None
    if stage.get("environment") not in (None, INLINE_ENVIRONMENT_NAME):
        return None
    script_path = stage.get("script_path")
    if not script_path:
        return None
    return os.path.normpath(os.path.join(stage.get("wdir") or "", script_path))
