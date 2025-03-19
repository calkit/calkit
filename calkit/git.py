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


def get_staged_files_with_status(path: str = None) -> list[dict]:
    repo = git.Repo(path)
    cmd = ["--staged", "--name-status"]
    if path is not None:
        cmd.append(path)
    diff = repo.git.diff(cmd)
    paths = diff.split("\n")
    res = []
    for path in paths:
        status, p = path.split("\t")
        res.append({"status": status, "path": p})
    return res
