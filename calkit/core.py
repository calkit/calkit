"""Core functionality."""

from __future__ import annotations

import glob
import logging
import os

import ruamel.yaml
from git import Repo
from git.exc import InvalidGitRepositoryError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__package__)

ryaml = ruamel.yaml.YAML()
ryaml.indent(mapping=2, sequence=4, offset=2)
ryaml.preserve_quotes = True
ryaml.width = 70


def find_project_dirs(relative=False, max_depth=3) -> list[str]:
    """Find all Calkit project directories."""
    if relative:
        start = ""
    else:
        start = os.path.expanduser("~")
    res = []
    for i in range(max_depth):
        pattern = os.path.join(start, *["*"] * (i + 1), "calkit.yaml")
        res += glob.glob(pattern)
        # Check GitHub documents for users who use GitHub Desktop
        pattern = os.path.join(
            start, "*", "GitHub", *["*"] * (i + 1), "calkit.yaml"
        )
        res += glob.glob(pattern)
    final_res = []
    for ck_fpath in res:
        path = os.path.dirname(ck_fpath)
        # Make sure this path is a Git repo
        try:
            Repo(path)
        except InvalidGitRepositoryError:
            continue
        final_res.append(path)
    return final_res


def load_calkit_info() -> dict:
    if os.path.isfile("calkit.yaml"):
        with open("calkit.yaml") as f:
            return ryaml.load(f)
    return {}
