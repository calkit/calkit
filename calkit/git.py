"""Git-related functionality."""

from __future__ import annotations

import git

import calkit


def detect_project_name(path: str = None) -> str:
    """Read the project owner and name from the remote."""
    ck_info = calkit.load_calkit_info(wdir=path)
    name = ck_info.get("name")
    owner = ck_info.get("owner")
    url = git.Repo(path=path).remote().url
    from_url = url.split("github.com")[-1][1:].removesuffix(".git")
    owner_name, project_name = from_url.split("/")
    if name is None:
        name = project_name
    if owner is None:
        owner = owner_name
    return f"{owner}/{name}"
