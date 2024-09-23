"""Git-related functionality."""

from __future__ import annotations

import git


def detect_project_name(path=None) -> str:
    """Read the project owner and name from the remote.

    TODO: Currently only works with GitHub remotes.
    """
    url = git.Repo(path=path).remote().url
    return url.split("github.com")[-1][1:].removesuffix(".git")
