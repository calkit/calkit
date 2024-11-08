"""Git-related functionality."""

from __future__ import annotations

import git


def detect_project_name(path=None) -> str:
    """Read the project owner and name from the remote.

    TODO: Currently only works with GitHub remotes where the GitHub repo
    name is identical to the Calkit project name, which is not guaranteed.
    We should probably look inside ``calkit.yaml`` in ``project.name``
    first, and fallback to the GitHub remote URL if we can't find that.
    """
    url = git.Repo(path=path).remote().url
    return url.split("github.com")[-1][1:].removesuffix(".git")
