"""Git-related functionality."""

import git


def detect_project_name() -> str:
    """Read the project owner and name from the remote.

    TODO: Currently only works with GitHub remotes.
    """
    url = git.Repo().remote().url
    return (
        url.removeprefix("git@github.com:")
        .removeprefix("https://github.com/")
        .removesuffix(".git")
    )
