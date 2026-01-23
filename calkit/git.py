"""Git-related functionality."""

from __future__ import annotations

import os
from os import PathLike
from pathlib import Path

import git


def get_staged_files(
    path: str | None = None, repo: git.Repo | None = None
) -> list[str]:
    """Get a list of staged files for the repo at ``path`` or the provided
    repo.
    """
    if repo is None:
        repo = git.Repo(path)
    cmd = ["--staged", "--name-only"]
    if path is not None:
        cmd.append(path)
    diff = repo.git.diff(cmd)
    paths = diff.split("\n")
    return [p for p in paths if p]


def get_changed_files(
    path: str | None = None, repo: git.Repo | None = None
) -> list[str]:
    """Get a list of files that have been changed but not staged."""
    if repo is None:
        repo = git.Repo(path)
    return [
        item.a_path
        for item in repo.index.diff(None)
        if item.a_path is not None
    ]


def get_untracked_files(
    path: str | None = None, repo: git.Repo | None = None
) -> list[str]:
    """Get a list of untracked files."""
    if repo is None:
        repo = git.Repo(path)
    return repo.untracked_files


def get_staged_files_with_status(
    path: str | None = None, repo: git.Repo | None = None
) -> list[dict]:
    if repo is None:
        repo = git.Repo(path)
    cmd = ["--staged", "--name-status"]
    if path is not None:
        cmd.append(path)
    diff = repo.git.diff(cmd)
    paths = diff.split("\n")
    res = []
    for pathi in paths:
        # Make sure line is not empty, e.g., a trailing newline
        if pathi:
            status, p = pathi.split("\t")
            res.append({"status": status, "path": p})
    return res


def ls_files(repo: git.Repo, *args, **kwargs) -> list[str]:
    """Get a list of all files tracked by git."""
    output = repo.git.ls_files(*args, **kwargs)
    return [f for f in output.split("\n") if f]


def ensure_path_is_ignored(
    repo: git.Repo, path: str | PathLike
) -> None | bool:
    """Ensure that the given path is ignored by Git.

    Returns True if ``.gitignore`` was modified.
    """
    if repo.ignored(path):
        return
    # Read gitignore first to check if the path is already ignored
    # If not, we don't want to add a line for it since it was added
    # TODO: Add an option to remove cached (`git rm --cached`)
    gitignore_path = os.path.join(repo.working_dir, ".gitignore")
    if os.path.isfile(gitignore_path):
        with open(gitignore_path) as f:
            gitignore_txt = f.read()
        lines = gitignore_txt.splitlines()
        path = Path(path).as_posix()
        if path in lines:
            return
    with open(gitignore_path, "a") as f:
        f.write(f"\n{path}\n")
        return True


def ensure_path_is_not_ignored(
    repo: git.Repo, path: str | PathLike
) -> None | bool:
    """Ensure a path is not ignored by Git."""
    if not repo.ignored(path):
        return
    gitignore_path = os.path.join(repo.working_dir, ".gitignore")
    with open(gitignore_path) as f:
        gitignore_txt = f.read()
    lines = gitignore_txt.splitlines()
    path = Path(path).as_posix()
    no_ignore_line = f"!{path}"
    if path in lines:
        lines.remove(path)
    elif no_ignore_line not in lines:
        lines.append(f"!{path}")
    with open(gitignore_path, "w") as f:
        f.write(os.linesep.join(lines))
    return True
