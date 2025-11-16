"""Functionality for working with Overleaf."""

import json
import os
import warnings
from pathlib import Path

import calkit


def get_git_remote_url(project_id: str, token: str) -> str:
    """Form the Git remote URL for an Overleaf project.

    If running against a test environment, this will use a local directory.
    """
    if calkit.config.get_env() == "test":
        return os.path.join("/tmp", "overleaf", project_id)
    return f"https://git:{token}@git.overleaf.com/{project_id}"


def get_sync_info(
    wdir: str | None = None,
    ck_info: dict | None = None,
    fix_legacy: bool = True,
) -> dict:
    """Load in a dictionary of Overleaf sync data, keyed by path relative to
    ``wdir``.
    """
    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    overleaf_info = {}
    # If we have any publications synced with Overleaf, get those and remove
    # from calkit.yaml if desired, since that's legacy behavior
    pubs = ck_info.get("publications", [])
    for pub in pubs:
        if "overleaf" in pub:
            pub_overleaf = pub.pop("overleaf")
            pub_wdir = pub_overleaf.get("wdir")
            if not pub_wdir:
                if "path" not in pub:
                    warnings.warn(f"Publication '{pub}' has no path")
                pub_wdir = os.path.dirname(pub["path"])
            overleaf_info[Path(pub_wdir).as_posix()] = pub_overleaf
    if wdir is None:
        wdir = ""
    info_path = os.path.join(wdir, ".calkit", "overleaf.json")
    if os.path.isfile(info_path):
        with open(info_path) as f:
            overleaf_info.update(json.load(f))
    if fix_legacy:
        with open(os.path.join(wdir, "calkit.yaml"), "w") as f:
            calkit.ryaml.dump(ck_info, f)
        os.makedirs(os.path.join(wdir, ".calkit"), exist_ok=True)
        print(f"Writing to {info_path}")
        with open(info_path, "w") as f:
            json.dump(overleaf_info, f, indent=2)
    return overleaf_info


def write_sync_info(
    synced_path: str, info: dict, wdir: str | None = None
) -> str:
    """Write sync info for a given path, overwriting the data for that path."""
    # First read in the data
    if wdir is None:
        wdir = ""
    fpath = os.path.join(wdir, ".calkit", "overleaf.json")
    if os.path.isfile(fpath):
        with open(fpath) as f:
            existing = json.load(f)
    else:
        existing = {}
    existing[synced_path] = info
    with open(fpath, "w") as f:
        json.dump(existing, f, indent=2)
    return fpath
