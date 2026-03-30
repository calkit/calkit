"""Functionality for managing project folders zipped for DVC.

These are are zipped for DVC and unzipped in the workspace.

A pipeline output can use ``dvc-zip`` for its storage if is a large folder
consisting of many small files, which makes the DVC transfer much more
efficient.
"""

import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Literal
from zipfile import ZipFile

import git
import typer
from pydantic import BaseModel
from sqlitedict import SqliteDict
from tqdm import tqdm

import calkit
import calkit.git
from calkit.core import DVC_SIZE_THRESH_BYTES

LOCAL_DIR = ".calkit/local"
ZIPS_DIR = ".calkit/zip"
HASH_CACHE_PATH = LOCAL_DIR + "/hash-cache.sqlite"
SYNC_RECORDS_PATH = LOCAL_DIR + "/zip-sync-records.sqlite"
PATH_MAP_PATH = ZIPS_DIR + "/paths.json"
# Average file size threshold below which a large directory is considered a
# zip candidate — files smaller than this are inefficient to track individually
# in DVC
ZIP_CANDIDATE_AVG_FILE_SIZE_BYTES = 10_000_000  # 10 MB
# Minimum number of files a directory must contain to be a zip candidate;
# a single large file is better tracked directly by DVC
ZIP_CANDIDATE_MIN_FILE_COUNT = 10


def _check_local_dir() -> Path:
    if not os.path.isdir(LOCAL_DIR):
        os.makedirs(LOCAL_DIR, exist_ok=True)
    gitignore_path = os.path.join(LOCAL_DIR, ".gitignore")
    if not os.path.isfile(gitignore_path):
        with open(gitignore_path, "w") as f:
            f.write("*\n")
    return Path(LOCAL_DIR)


def is_zip_candidate(path: str) -> bool:
    """Detect if a path is a good candidate for dvc-zip storage.

    A zip candidate is a directory whose total size exceeds the DVC tracking
    threshold but whose average file size is small, meaning DVC would have to
    track many individual files inefficiently.
    """
    if not os.path.isdir(path):
        return False
    file_count = 0
    total_size = 0
    for foldername, _, filenames in os.walk(path):
        for filename in filenames:
            file_count += 1
            total_size += os.stat(os.path.join(foldername, filename)).st_size
    if (
        file_count < ZIP_CANDIDATE_MIN_FILE_COUNT
        or total_size <= DVC_SIZE_THRESH_BYTES
    ):
        return False
    return (total_size / file_count) < ZIP_CANDIDATE_AVG_FILE_SIZE_BYTES


def get_mtime_ns(path: str) -> int:
    """Get the modification time of a path in nanoseconds."""
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


class HashCacheEntry(BaseModel):
    """Cache entry for a path's hash."""

    path: str
    hash: str
    mtime: int  # Nanoseconds
    size: int
    dir_sig: str | None = None  # Only used for directories, to avoid rehashing
    alg: str = "md5"


class SyncRecord(BaseModel):
    input_path: str
    output_path: str
    input_hash: str
    output_hash: str
    last_updated: float


def make_zip_path(input_path: str) -> str:
    """Make a zip path for a given input path."""
    return os.path.join(ZIPS_DIR, "files", input_path + ".zip")


def get_zip_path_map() -> dict[str, str]:
    """Get a mapping of input paths to zip paths."""
    if os.path.isfile(PATH_MAP_PATH):
        with open(PATH_MAP_PATH, "r") as f:
            return json.load(f)
    return {}


def write_zip_path_map(path_map: dict[str, str]):
    d = os.path.dirname(PATH_MAP_PATH)
    os.makedirs(d, exist_ok=True)
    with open(PATH_MAP_PATH, "w") as f:
        json.dump(path_map, f, indent=2)


def check_overlap(input_path: str, path_map: dict[str, str] | None = None):
    """Raise ValueError if input_path overlaps (is parent/child of) any
    existing zip path in path_map.
    """
    if path_map is None:
        path_map = get_zip_path_map()
    new = Path(input_path)
    for existing in path_map:
        ex = Path(existing)
        if new == ex:
            continue
        if new.is_relative_to(ex) or ex.is_relative_to(new):
            raise ValueError(
                f"Zip path {input_path!r} overlaps with existing zip "
                f"path {existing!r}"
            )


def add(input_path: str, is_stage_output: bool = False):
    """Add a zip for a given input path.

    This is sort of like a ``git add`` for zips. We should do any DVC staging
    if it's not a pipeline output.
    """
    repo = git.Repo()
    pm = get_zip_path_map()
    # Normalize input path as posix
    input_path = Path(input_path).as_posix()
    if input_path not in pm:
        check_overlap(input_path, pm)
        pm[input_path] = make_zip_path(input_path)
        write_zip_path_map(pm)
        # Stage the updated info file
        repo.git.add(PATH_MAP_PATH)
    # Ensure the workspace dir is gitignored
    calkit.git.ensure_path_is_ignored(repo, path=input_path)
    repo.git.add(".gitignore")
    cleanup_sync_records()
    if not is_stage_output:
        # If this is not a stage output, it exists, so we should sync it
        # Always zip from workspace — it's the source of truth on an explicit add
        sync_one(
            input_path=input_path,
            output_path=pm[input_path],
            direction="to-zip",
        )


def hash_path(path: str, alg="md5") -> str:
    """Hash a path."""
    if alg == "md5":
        return calkit.get_md5(path)
    raise ValueError(f"Unsupported hash algorithm: {alg}")


def calc_dir_sig(path: str) -> str:
    """Calculate a fast signature for a directory to know if we should
    rehash.
    """
    if not os.path.isdir(path):
        return ""
    file_count = 0
    total_size = 0
    latest_mtime = 0
    for foldername, subfolders, filenames in os.walk(path):
        for filename in filenames:
            file_count += 1
            fpath = os.path.join(foldername, filename)
            st = os.stat(fpath)
            total_size += st.st_size
            if st.st_mtime_ns > latest_mtime:
                latest_mtime = st.st_mtime_ns
    return f"{file_count}-{total_size}-{latest_mtime}"


def get_hash(path: str, alg="md5") -> str | None:
    """Get the hash of a path, using/updating the cache if applicable."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    _check_local_dir()
    # Normalize path as posix
    path = Path(path).as_posix()
    mtime = st.st_mtime_ns
    size = st.st_size
    dir_sig = calc_dir_sig(path)
    with SqliteDict(HASH_CACHE_PATH) as cache:
        record = None
        raw = cache.get(path)
        if raw is not None:
            try:
                record = HashCacheEntry.model_validate(raw)
            except Exception:
                record = None
        if (
            record is not None
            and record.mtime == mtime
            and record.size == size
            and record.dir_sig == dir_sig
            and record.alg == alg
        ):
            return record.hash
        # Cache miss — compute and store
        typer.echo(f"Computing {alg} for '{path}'")
        hash_val = hash_path(path, alg=alg)
        cache[path] = HashCacheEntry(
            path=path,
            hash=hash_val,
            mtime=mtime,
            size=size,
            dir_sig=dir_sig,
            alg=alg,
        ).model_dump(mode="json")
        cache.commit()
    return hash_val


def get_sync_record(input_path: str) -> SyncRecord | None:
    """Get a sync record for a given input path."""
    _check_local_dir()
    with SqliteDict(SYNC_RECORDS_PATH) as db:
        raw = db.get(input_path)
    if raw is not None:
        return SyncRecord.model_validate(raw)
    return None


def write_sync_record(record: SyncRecord):
    """Write a sync record."""
    _check_local_dir()
    with SqliteDict(SYNC_RECORDS_PATH) as db:
        db[record.input_path] = record.model_dump()
        db.commit()


def delete_sync_record(input_path: str):
    """Delete a sync record."""
    _check_local_dir()
    with SqliteDict(SYNC_RECORDS_PATH) as db:
        if input_path in db:
            del db[input_path]
            db.commit()


def cleanup_sync_records():
    """Remove sync records for paths no longer in the path map."""
    _check_local_dir()
    pm = get_zip_path_map()
    with SqliteDict(SYNC_RECORDS_PATH) as db:
        stale = [k for k in db if k not in pm]
        if stale:
            for k in stale:
                del db[k]
            db.commit()


def get_output_path(input_path: str) -> str:
    pm = get_zip_path_map()
    input_path = Path(input_path).as_posix()
    if input_path in pm:
        return pm[input_path]
    raise ValueError(f"No zip output path defined for {input_path}")


def zip_path(input_path: str, output_path: str):
    """Zip a path."""
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)
    all_files = [
        os.path.join(foldername, filename)
        for foldername, _, filenames in os.walk(input_path)
        for filename in filenames
    ]
    with ZipFile(
        output_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as zip_file:
        for file_path in tqdm(all_files, desc="Zipping", unit="file"):
            zip_file.write(file_path, os.path.relpath(file_path, input_path))


def unzip_path(input_path: str, output_path: str):
    """Unzip from output to input."""
    input_dir = os.path.dirname(input_path)
    if input_dir:
        os.makedirs(input_dir, exist_ok=True)
    with ZipFile(output_path, "r") as zip_file:
        members = zip_file.namelist()
        for member in tqdm(members, desc="Unzipping", unit="file"):
            zip_file.extract(member, input_path)


class SyncStatus(BaseModel):
    input_path: str
    output_path: str
    input_hash: str | None
    output_hash: str | None
    input_changed: bool
    output_changed: bool
    last_sync_record: SyncRecord | None = None


def get_sync_status(
    input_path: str, output_path: str | None = None
) -> SyncStatus:
    # First get cached information and see if we need to rehash
    input_hash = get_hash(input_path)
    if output_path is None:
        output_path = get_output_path(input_path)
    output_hash = get_hash(output_path)
    last_sync_record = get_sync_record(input_path)
    if last_sync_record is not None:
        input_changed = input_hash != last_sync_record.input_hash
        output_changed = output_hash != last_sync_record.output_hash
    else:
        # If we've never synced before, we should only have one or the other,
        # i.e., the input or the output path, not both
        input_changed = os.path.exists(input_path)
        output_changed = os.path.exists(output_path)
    return SyncStatus(
        input_path=input_path,
        output_path=output_path,
        input_hash=input_hash,
        output_hash=output_hash,
        input_changed=input_changed,
        output_changed=output_changed,
        last_sync_record=last_sync_record,
    )


def sync_one(
    input_path: str,
    output_path: str | None = None,
    direction: Literal["to-zip", "to-workspace", "both"] = "both",
) -> SyncRecord | None:
    """Process a single zip."""
    status = get_sync_status(input_path, output_path)
    input_changed = status.input_changed
    output_changed = status.output_changed
    input_hash = status.input_hash
    output_hash = status.output_hash
    output_path = status.output_path
    last_sync_record = status.last_sync_record
    # A deletion is when the path no longer exists but did at last sync
    input_deleted = input_hash is None and last_sync_record is not None
    output_deleted = output_hash is None and last_sync_record is not None
    # Both deleted — clear the stale sync record so a future recreated side
    # is treated as a fresh first sync rather than a spurious conflict
    if input_deleted and output_deleted:
        delete_sync_record(input_path)
        return None
    # Neither side exists and no sync record — nothing to do (e.g., a
    # pipeline output that hasn't been produced yet on a fresh run)
    if input_hash is None and output_hash is None:
        return None
    # Deletion + change on the other side is a conflict
    if input_deleted and output_changed and direction == "both":
        raise RuntimeError(
            f"Conflict detected for zip path '{input_path}'. "
            "Workspace was deleted but zip has also changed since last sync. "
            "Please resolve the conflict manually."
        )
    if output_deleted and input_changed and direction == "both":
        raise RuntimeError(
            f"Conflict detected for zip path '{input_path}'. "
            "Zip was deleted but workspace has also changed since last sync. "
            "Please resolve the conflict manually."
        )
    # Propagate workspace deletion to zip
    if input_deleted and direction in ["to-zip", "both"]:
        if os.path.exists(output_path):
            typer.echo(f"Deleting '{output_path}' (workspace was deleted)")
            os.remove(output_path)
        delete_sync_record(input_path)
        return None
    # Propagate zip deletion to workspace
    if output_deleted and direction in ["to-workspace", "both"]:
        if os.path.exists(input_path):
            typer.echo(f"Deleting '{input_path}' (zip was deleted)")
            shutil.rmtree(input_path)
        delete_sync_record(input_path)
        return None
    # Zip was deleted but workspace exists and direction is to-zip:
    # restore zip
    if output_deleted and direction == "to-zip":
        typer.echo(f"Rezipping '{input_path}' (zip was deleted)")
        zip_path(input_path=input_path, output_path=output_path)
        subprocess.run(["dvc", "add", output_path], check=True)
        output_hash = get_hash(output_path)
    # Workspace was deleted but zip exists and direction is to-workspace:
    # restore workspace
    if input_deleted and direction == "to-workspace":
        typer.echo(f"Unzipping to '{input_path}' (workspace was deleted)")
        unzip_path(input_path=input_path, output_path=output_path)
        input_hash = get_hash(input_path)
    # If hashes have changed since last check, we need to synchronize the
    # path with its zip file (unzip if zip is newer, rezip if path is newer)
    # If both have changed, we have a conflict and the user needs to decide
    # how we should resolve it (rezip, unzip, unzip+merge+rezip)
    if input_changed and output_changed and direction == "both":
        raise RuntimeError(
            f"Conflict detected for zip path '{input_path}'. "
            "Both input and output have changed since last sync. "
            "Please resolve the conflict manually."
        )
    # If we rezip, we need to add the zip file to DVC and update the hash
    if input_changed and (direction in ["to-zip", "both"]):
        typer.echo(f"Zipping '{input_path}' (workspace has changed)")
        zip_path(input_path=input_path, output_path=output_path)
        subprocess.run(["dvc", "add", output_path], check=True)
        output_hash = get_hash(output_path)
    # If we unzip, we need to update the hash
    if output_changed and (direction in ["to-workspace", "both"]):
        typer.echo(f"Unzipping to '{input_path}' (zip has changed)")
        unzip_path(input_path=input_path, output_path=output_path)
        input_hash = get_hash(input_path)
    assert input_hash is not None and output_hash is not None
    record = SyncRecord(
        input_path=input_path,
        output_path=output_path,
        last_updated=float(calkit.utcnow().timestamp()),
        input_hash=input_hash,
        output_hash=output_hash,
    )
    write_sync_record(record)
    return record


def sync_some(
    input_paths: list[str],
    direction: Literal["to-zip", "to-workspace", "both"] = "both",
):
    """Process a subset of project zips by their workspace input paths."""
    pm = get_zip_path_map()
    for input_path in input_paths:
        norm = Path(input_path).as_posix()
        output_path = pm.get(norm)
        sync_one(input_path=norm, output_path=output_path, direction=direction)


def sync_all(direction: Literal["to-zip", "to-workspace", "both"] = "both"):
    """Process all project zips."""
    for input_path, output_path in get_zip_path_map().items():
        sync_one(
            input_path=input_path, output_path=output_path, direction=direction
        )
