"""Functionality for working with Overleaf."""

import os

import calkit


def get_git_remote_url(project_id: str, token: str) -> str:
    """Form the Git remote URL for an Overleaf project.

    If running against a test environment, this will use a local directory.
    """
    if calkit.config.get_env() == "test":
        return os.path.join("/tmp", "overleaf", project_id)
    return f"https://git:{token}@git.overleaf.com/{project_id}"
