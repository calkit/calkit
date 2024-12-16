"""Checking things."""

import os
from typing import Callable

import git
from git.exc import InvalidGitRepositoryError
from pydantic import BaseModel


def _bool_to_check_x(val: bool) -> str:
    """Convert a boolean to a checkmark or an X.

    TODO: Need to detect if the terminal can handle these characters so we
    don't get a UnicodeEncodeError, e.g., on Git Bash.
    """
    if val:
        return "✅"
    else:
        return "❌"


class ReproCheck(BaseModel):
    has_pipeline: bool
    is_dvc_repo: bool
    is_git_repo: bool
    has_calkit_info: bool

    def to_pretty(self) -> str:
        """Format as a nice string to print."""
        txt = f"Is a Git repo: {_bool_to_check_x(self.is_git_repo)}\n"
        txt += f"DVC initialized: {_bool_to_check_x(self.is_dvc_repo)}\n"
        txt += f"Has pipeline: {_bool_to_check_x(self.has_pipeline)}\n"
        txt += f"Has Calkit info: {_bool_to_check_x(self.has_calkit_info)}\n"
        return txt


def check_reproducibility(
    wdir: str = ".", log_func: Callable = None
) -> ReproCheck:
    """Check the reproducibility of a project."""
    if log_func is None:
        log_func = print
    try:
        repo = git.Repo(wdir)
        is_git_repo = True
    except InvalidGitRepositoryError:
        is_git_repo = False
    is_dvc_repo = os.path.isfile(os.path.join(wdir, ".dvc", "config"))
    has_pipeline = os.path.isfile(os.path.join(wdir, "dvc.yaml"))
    has_ck_info = os.path.isfile(os.path.join(wdir, "calkit.yaml"))
    # TODO: Check for artifacts not produced by the pipeline
    return ReproCheck(
        has_pipeline=has_pipeline,
        is_dvc_repo=is_dvc_repo,
        is_git_repo=is_git_repo,
        has_calkit_info=has_ck_info,
    )
