"""Functionality for managing project DVC zips/unzips.

A zip is a collection of files that are zipped for DVC and
unzipped in the workspace.

A pipeline output can use ``dvc-zip`` for its storage if is a large folder
consisting of many small files, which makes the DVC transfer much more
efficient.

There is a CLI command ``calkit check zips`` to make sure all are up-to-date.

If a zip input is modified, it means we need to rezip and add the zip file
to DVC.

If a zip output is modified, it means we need to unzip to its path in the
project.

When looking at project status, anything showing up as modified in ``ZIPS_DIR``
should be transformed into its path in the project.

Zips should be synced:
- After a pull
- After a clone
- Before computing status
- Before running the pipeline
- After running the pipeline (one way, workspace to zip?)
- Before an add, and then the zip should be added with DVC
- If we call ``calkit check zips``
"""

import json
import os
from pathlib import Path

from pydantic import BaseModel

import calkit

ZIPS_DIR = ".calkit/zips"
ZIP_CACHE_PATH = ".calkit/local/zip-cache.json"
ZIP_INFO_PATH = ".calkit/zips/info.json"


class ZipInfoEntry(BaseModel):
    path: str  # Path in the project--should be a folder
    zip_path: str  # Path to the zip file, like .calkit/zips/{uuid}.zip


class ZipCacheEntry(BaseModel):
    path: str  # Path in the project--should be a folder
    last_updated: int
    input_hash: str
    input_size: int
    input_mtime: int
    output_hash: str
    output_mtime: int
    output_size: int


def make_zip_path(input_path: str) -> str:
    """Make a zip path for a given input path."""
    return os.path.join(ZIPS_DIR, input_path + ".zip")


def get_zip_path_map() -> dict[str, str]:
    """Get a mapping of input paths to zip paths."""
    if os.path.isfile(ZIP_INFO_PATH):
        with open(ZIP_INFO_PATH, "r") as f:
            return json.load(f)
    return {}


def write_zip_path_map(path_map: dict[str, str]):
    d = os.path.dirname(ZIP_INFO_PATH)
    os.makedirs(d, exist_ok=True)
    with open(ZIP_INFO_PATH, "w") as f:
        json.dump(path_map, f, indent=2)


def add_zip(input_path: str):
    """Add a zip for a given input path.

    If one already exists, skip.

    This may need to happen during pipeline compilation if there's a stage
    with an output with dvc-zip storage.
    """
    pm = get_zip_path_map()
    # Normalize input path as posix
    input_path = Path(input_path).as_posix()
    if input_path not in pm:
        pm[input_path] = make_zip_path(input_path)
    write_zip_path_map(pm)


def hash_path(path: str) -> str:
    """Hash a path.

    TODO: Use SHA256?
    """
    return calkit.get_md5(path)


def process_single(path: str):
    """Process a single zip."""
    # First get cached information and see if we need to rehash
    # If hashes have changed since last check, we need to synchronize the
    # path with its zip file (unzip if zip is newer, rezip if path is newer)
    # If both have changed, we have a conflict and the user needs to decide
    # how we should resolve it (rezip, unzip, unzip+merge+rezip)


def process_all():
    """Process all project zips."""
    # First get zip metadata
