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
from calkit.dvc.core import run_dvc_command

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
# Favor speed for dvc-zip by default; users can tune 0..9 via env var
# CALKIT_DVC_ZIP_COMPRESS_LEVEL
ZIP_COMPRESS_LEVEL = 1
# Use Python zipfile by default; set CALKIT_DVC_ZIP_USE_SYSTEM=1 to try
# the system zip/unzip tools instead (may be faster for very large files)
ZIP_USE_SYSTEM_CLI = False


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
    workspace_path: str
    zip_path: str
    workspace_hash: str
    zip_hash: str
    last_updated: float


def make_zip_path(workspace_path: str) -> str:
    """Make a zip path for a given workspace path."""
    return os.path.join(ZIPS_DIR, "files", workspace_path + ".zip")


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


def check_overlap(workspace_path: str, path_map: dict[str, str] | None = None):
    """Raise ValueError if workspace path overlaps (is parent/child of) any
    existing zip path in path_map.
    """
    if path_map is None:
        path_map = get_zip_path_map()
    new = Path(workspace_path)
    for existing in path_map:
        ex = Path(existing)
        if new == ex:
            continue
        if new.is_relative_to(ex) or ex.is_relative_to(new):
            raise ValueError(
                f"Zip path {workspace_path!r} overlaps with existing zip "
                f"path {existing!r}"
            )


def add(workspace_path: str, is_stage_output: bool = False):
    """Add a zip for a given workspace path.

    This is sort of like a ``git add`` for zips. We should do any DVC staging
    if it's not a pipeline output.
    """
    repo = git.Repo()
    pm = get_zip_path_map()
    # Normalize input path as posix
    workspace_path = Path(workspace_path).as_posix()
    if workspace_path not in pm:
        check_overlap(workspace_path, pm)
        pm[workspace_path] = make_zip_path(workspace_path)
        write_zip_path_map(pm)
        # Stage the updated info file
        repo.git.add(PATH_MAP_PATH)
    # Ensure the workspace dir is gitignored
    calkit.git.ensure_path_is_ignored(repo, path=workspace_path)
    repo.git.add(".gitignore")
    cleanup_sync_records()
    if not is_stage_output:
        # If this is not a stage output, it exists, so we should sync it
        # Always zip from workspace — it's the source of truth on an explicit add
        sync_one(
            workspace_path=workspace_path,
            zip_path=pm[workspace_path],
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

    The signature includes file count, total size, and latest mtime in
    nanoseconds over all files in the directory tree.
    """
    if not os.path.isdir(path):
        return ""
    file_count = 0
    total_size = 0
    latest_mtime = 0
    for foldername, _, filenames in os.walk(path):
        for filename in filenames:
            fpath = os.path.join(foldername, filename)
            try:
                st = os.stat(fpath)
            except OSError:
                continue
            file_count += 1
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


def get_sync_record(workspace_path: str) -> SyncRecord | None:
    """Get a sync record for a given workspace path."""
    _check_local_dir()
    with SqliteDict(SYNC_RECORDS_PATH) as db:
        raw = db.get(workspace_path)
    if raw is not None:
        return SyncRecord.model_validate(raw)
    return None


def write_sync_record(record: SyncRecord):
    """Write a sync record."""
    _check_local_dir()
    with SqliteDict(SYNC_RECORDS_PATH) as db:
        db[record.workspace_path] = record.model_dump()
        db.commit()


def delete_sync_record(workspace_path: str):
    """Delete a sync record."""
    _check_local_dir()
    with SqliteDict(SYNC_RECORDS_PATH) as db:
        if workspace_path in db:
            del db[workspace_path]
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


def get_zip_path(workspace_path: str) -> str:
    pm = get_zip_path_map()
    workspace_path = Path(workspace_path).as_posix()
    if workspace_path in pm:
        return pm[workspace_path]
    raise ValueError(f"No zip path defined for {workspace_path}")


def _get_zip_compress_level() -> int:
    raw = os.getenv("CALKIT_DVC_ZIP_COMPRESS_LEVEL", str(ZIP_COMPRESS_LEVEL))
    try:
        level = int(raw)
    except ValueError:
        typer.echo(
            "Invalid CALKIT_DVC_ZIP_COMPRESS_LEVEL value; "
            f"using default {ZIP_COMPRESS_LEVEL}.",
            err=True,
        )
        return ZIP_COMPRESS_LEVEL
    return min(max(level, 0), 9)


def _should_use_system_zip_cli() -> bool:
    raw = os.getenv("CALKIT_DVC_ZIP_USE_SYSTEM")
    if raw is None:
        return ZIP_USE_SYSTEM_CLI
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _iter_files(path: str):
    for foldername, _, filenames in os.walk(path):
        for filename in filenames:
            yield os.path.join(foldername, filename)


def zip_(workspace_path: str, zip_path: str):
    """Zip a path."""
    zip_path = os.path.abspath(zip_path)
    output_dir = os.path.dirname(zip_path)
    os.makedirs(output_dir, exist_ok=True)
    compress_level = _get_zip_compress_level()
    if _should_use_system_zip_cli() and shutil.which("zip"):
        try:
            subprocess.run(
                ["zip", "-q", f"-{compress_level}", "-r", zip_path, "."],
                check=True,
                cwd=workspace_path,
            )
            return
        except Exception:
            typer.echo(
                "System zip failed; falling back to Python zipfile.",
                err=True,
            )
    all_files = list(_iter_files(workspace_path))
    with ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=compress_level,
    ) as zip_file:
        for file_path in tqdm(all_files, desc="Zipping", unit="file"):
            zip_file.write(
                file_path, os.path.relpath(file_path, workspace_path)
            )


def unzip(workspace_path: str, zip_path: str):
    """Unzip from zip to workspace."""
    zip_path = os.path.abspath(zip_path)
    input_dir = os.path.dirname(workspace_path)
    if input_dir:
        os.makedirs(input_dir, exist_ok=True)
    if _should_use_system_zip_cli() and shutil.which("unzip"):
        try:
            os.makedirs(workspace_path, exist_ok=True)
            subprocess.run(
                ["unzip", "-oq", zip_path, "-d", workspace_path],
                check=True,
            )
            return
        except Exception:
            typer.echo(
                "System unzip failed; falling back to Python zipfile.",
                err=True,
            )
    with ZipFile(zip_path, "r") as zip_file:
        members = zip_file.infolist()
        for member in tqdm(members, desc="Unzipping", unit="file"):
            zip_file.extract(member, workspace_path)


class SyncStatus(BaseModel):
    workspace_path: str
    zip_path: str
    workspace_hash: str | None
    zip_hash: str | None
    workspace_changed: bool
    zip_changed: bool
    last_sync_record: SyncRecord | None = None


def get_sync_status(
    workspace_path: str, zip_path: str | None = None
) -> SyncStatus:
    # First get cached information and see if we need to rehash
    workspace_hash = get_hash(workspace_path)
    if zip_path is None:
        zip_path = get_zip_path(workspace_path)
    zip_hash = get_hash(zip_path)
    last_sync_record = get_sync_record(workspace_path)
    if last_sync_record is not None:
        workspace_changed = workspace_hash != last_sync_record.workspace_hash
        zip_changed = zip_hash != last_sync_record.zip_hash
    else:
        # If we've never synced before, we should only have one or the other,
        # i.e., the input or the output path, not both
        workspace_changed = os.path.exists(workspace_path)
        zip_changed = os.path.exists(zip_path)
    return SyncStatus(
        workspace_path=workspace_path,
        zip_path=zip_path,
        workspace_hash=workspace_hash,
        zip_hash=zip_hash,
        workspace_changed=workspace_changed,
        zip_changed=zip_changed,
        last_sync_record=last_sync_record,
    )


def sync_one(
    workspace_path: str,
    zip_path: str | None = None,
    direction: Literal["to-zip", "to-workspace", "both"] = "both",
) -> SyncRecord | None:
    """Process a single zip."""
    status = get_sync_status(workspace_path, zip_path)
    workspace_changed = status.workspace_changed
    zip_changed = status.zip_changed
    workspace_hash = status.workspace_hash
    zip_hash = status.zip_hash
    zip_path = status.zip_path
    last_sync_record = status.last_sync_record
    # A deletion is when the path no longer exists but did at last sync
    workspace_deleted = workspace_hash is None and last_sync_record is not None
    zip_deleted = zip_hash is None and last_sync_record is not None
    # Both deleted — clear the stale sync record so a future recreated side
    # is treated as a fresh first sync rather than a spurious conflict
    if workspace_deleted and zip_deleted:
        delete_sync_record(workspace_path)
        return None
    # Neither side exists and no sync record — nothing to do (e.g., a
    # pipeline output that hasn't been produced yet on a fresh run)
    if workspace_hash is None and zip_hash is None:
        return None
    # Deletion + change on the other side is a conflict
    if workspace_deleted and zip_changed and direction == "both":
        raise RuntimeError(
            f"Conflict detected for zip path '{workspace_path}'. "
            "Workspace was deleted but zip has also changed since last sync. "
            "Please resolve the conflict manually."
        )
    if zip_deleted and workspace_changed and direction == "both":
        raise RuntimeError(
            f"Conflict detected for zip path '{workspace_path}'. "
            "Zip was deleted but workspace has also changed since last sync. "
            "Please resolve the conflict manually."
        )
    # Propagate workspace deletion to zip
    if workspace_deleted and direction in ["to-zip", "both"]:
        if os.path.exists(zip_path):
            typer.echo(f"Deleting '{zip_path}' (workspace was deleted)")
            os.remove(zip_path)
        delete_sync_record(workspace_path)
        return None
    # Propagate zip deletion to workspace
    if zip_deleted and direction in ["to-workspace", "both"]:
        if os.path.exists(workspace_path):
            typer.echo(f"Deleting '{workspace_path}' (zip was deleted)")
            shutil.rmtree(workspace_path)
        delete_sync_record(workspace_path)
        return None
    # Zip was deleted but workspace exists and direction is to-zip:
    # restore zip
    if zip_deleted and direction == "to-zip":
        typer.echo(f"Rezipping '{workspace_path}' (zip was deleted)")
        zip_(workspace_path=workspace_path, zip_path=zip_path)
        run_dvc_command(["add", zip_path])
        zip_hash = get_hash(zip_path)
    # Workspace was deleted but zip exists and direction is to-workspace:
    # restore workspace
    if workspace_deleted and direction == "to-workspace":
        typer.echo(f"Unzipping to '{workspace_path}' (workspace was deleted)")
        unzip(workspace_path=workspace_path, zip_path=zip_path)
        workspace_hash = get_hash(workspace_path)
    # If hashes have changed since last check, we need to synchronize the
    # path with its zip file (unzip if zip is newer, rezip if path is newer)
    # If both have changed, we have a conflict and the user needs to decide
    # how we should resolve it (rezip, unzip, unzip+merge+rezip)
    if workspace_changed and zip_changed and direction == "both":
        raise RuntimeError(
            f"Conflict detected for zip path '{workspace_path}'. "
            "Both input and output have changed since last sync. "
            "Please resolve the conflict manually."
        )
    # If we rezip, we need to add the zip file to DVC and update the hash
    if workspace_changed and (direction in ["to-zip", "both"]):
        typer.echo(f"Zipping '{workspace_path}' (workspace has changed)")
        zip_(workspace_path=workspace_path, zip_path=zip_path)
        run_dvc_command(["add", zip_path])
        zip_hash = get_hash(zip_path)
    # If we unzip, we need to update the hash
    if zip_changed and (direction in ["to-workspace", "both"]):
        typer.echo(f"Unzipping to '{workspace_path}' (zip has changed)")
        unzip(workspace_path=workspace_path, zip_path=zip_path)
        workspace_hash = get_hash(workspace_path)
    assert workspace_hash is not None and zip_hash is not None
    record = SyncRecord(
        workspace_path=workspace_path,
        zip_path=zip_path,
        last_updated=float(calkit.utcnow().timestamp()),
        workspace_hash=workspace_hash,
        zip_hash=zip_hash,
    )
    write_sync_record(record)
    return record


def sync_some(
    workspace_paths: list[str],
    direction: Literal["to-zip", "to-workspace", "both"] = "both",
):
    """Process a subset of project zips by their workspace input paths."""
    pm = get_zip_path_map()
    for workspace_path in workspace_paths:
        norm = Path(workspace_path).as_posix()
        output_path = pm.get(norm)
        sync_one(
            workspace_path=norm, zip_path=output_path, direction=direction
        )


def sync_all(direction: Literal["to-zip", "to-workspace", "both"] = "both"):
    """Process all project zips."""
    for workspace_path, zip_path in get_zip_path_map().items():
        sync_one(
            workspace_path=workspace_path,
            zip_path=zip_path,
            direction=direction,
        )
