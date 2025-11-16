"""Functionality for working with Overleaf."""

import json
import os
import warnings
from copy import deepcopy
from pathlib import Path

import calkit

PRIVATE_KEYS = ["project_id", "last_sync_commit"]


def get_git_remote_url(project_id: str, token: str) -> str:
    """Form the Git remote URL for an Overleaf project.

    If running against a test environment, this will use a local directory.
    """
    if calkit.config.get_env() == "test":
        return os.path.join("/tmp", "overleaf", project_id)
    return f"https://git:{token}@git.overleaf.com/{project_id}"


def project_id_to_url(project_id: str) -> str:
    return f"https://www.overleaf.com/project/{project_id}"


def project_id_from_url(url: str) -> str:
    return url.split("/")[-1]


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
            ol_info_private = json.load(f)
        for k, v in ol_info_private.items():
            if k not in overleaf_info:
                overleaf_info[k] = {}
            for k1, v1 in v.items():
                overleaf_info[k][k1] = v1
    # Override with any values defined in calkit.yaml
    if "overleaf_sync" in ck_info:
        ol_info_ck = deepcopy(ck_info["overleaf_sync"])
        for k, v in ol_info_ck.items():
            if k not in overleaf_info:
                overleaf_info[k] = {}
            for k1, v1 in v.items():
                overleaf_info[k][k1] = v1
    # Iterate through and fix data if necessary
    for synced_dir, dirinfo in overleaf_info.items():
        if "url" in dirinfo:
            dirinfo["project_id"] = project_id_from_url(dirinfo["url"])
    if fix_legacy:
        overleaf_sync_for_ck_info = ck_info.get("overleaf_sync", {})
        for synced_dir, info in overleaf_info.items():
            info_in_ck = overleaf_sync_for_ck_info.get(synced_dir, {})
            if "url" not in info_in_ck:
                info_in_ck["url"] = project_id_to_url(info["project_id"])
            if "sync_paths" in info:
                info_in_ck["sync_paths"] = info["sync_paths"]
            if "push_paths" in info:
                info_in_ck["push_paths"] = info["push_paths"]
        ck_info["overleaf_sync"] = overleaf_sync_for_ck_info
        with open(os.path.join(wdir, "calkit.yaml"), "w") as f:
            calkit.ryaml.dump(ck_info, f)
        os.makedirs(os.path.join(wdir, ".calkit"), exist_ok=True)
        private_info = {}
        for synced_dir, info in overleaf_info.items():
            private_info[synced_dir] = {k: info.get(k) for k in PRIVATE_KEYS}
        with open(info_path, "w") as f:
            json.dump(private_info, f, indent=2)
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
    existing[synced_path] = {k: info.get(k) for k in PRIVATE_KEYS}
    with open(fpath, "w") as f:
        json.dump(existing, f, indent=2)
    return fpath
