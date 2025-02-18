"""Git-related functionality."""

from __future__ import annotations

import git


def get_staged_files(path: str = None) -> list[str]:
    repo = git.Repo(path)
    cmd = ["--staged", "--name-only"]
    if path is not None:
        cmd.append(path)
    diff = repo.git.diff(cmd)
    paths = diff.split("\n")
    return paths
