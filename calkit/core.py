"""Core functionality."""

from __future__ import annotations

import glob
import logging
import os
from datetime import UTC, datetime

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


def load_calkit_info(
    wdir=None, process_includes: bool | str | list[str] = False
) -> dict:
    """Load Calkit project information.

    Parameters
    ----------
    wdir : str
        Working directory. Defaults to current working directory.
    process_includes: bool, string or list of strings
        Whether or not to process any '_include' keys for a given kind of
        object. If a string is passed, only process includes for that kind.
        Similarly, if a list of strings is passed, only process those kinds.
        If True, process all default kinds.
    """
    info = {}
    fpath = "calkit.yaml"
    if wdir is not None:
        fpath = os.path.join(wdir, fpath)
    if os.path.isfile(fpath):
        with open(fpath) as f:
            info = ryaml.load(f)
    # Check for any includes, i.e., entities with an _include key, for which
    # we should merge in another file
    default_includes_enabled = ["environments", "procedures"]
    if process_includes:
        if isinstance(process_includes, bool):
            includes_enabled = default_includes_enabled
        elif isinstance(process_includes, str):
            includes_enabled = [process_includes]
        elif isinstance(process_includes, list):
            includes_enabled = process_includes
        for kind in includes_enabled:
            if kind in info:
                for obj_name, obj in info[kind].items():
                    if "_include" in obj:
                        include_fpath = obj.pop("_include")
                        with open(include_fpath) as f:
                            include_data = ryaml.load(f)
                        info[kind][obj_name] |= include_data
    return info


def utcnow(remove_tz=True) -> datetime:
    """Return now in UTC, optionally stripping timezone information."""
    dt = datetime.now(UTC)
    if remove_tz:
        dt = dt.replace(tzinfo=None)
    return dt
