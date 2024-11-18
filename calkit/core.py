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


def load_calkit_info(wdir=None, process_includes=False) -> dict:
    """Load Calkit project information."""
    info = {}
    fpath = "calkit.yaml"
    if wdir is not None:
        fpath = os.path.join(wdir, fpath)
    if os.path.isfile(fpath):
        with open(fpath) as f:
            info = ryaml.load(f)
    # Check for any includes, i.e., entities with an _include key, for which
    # we should merge in another file
    # Currently this is only supported with environments because they may need
    # to be tracked as DVC dependencies
    if process_includes:
        if "environments" in info:
            for env_name, env in info["environments"].items():
                if "_include" in env:
                    include_fpath = env.pop("_include")
                    with open(include_fpath) as f:
                        include_data = ryaml.load(f)
                    info["environments"][env_name] |= include_data
    return info
