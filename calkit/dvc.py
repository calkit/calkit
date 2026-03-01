"""Working with DVC."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import git

import calkit
from calkit.cli import warn
from calkit.config import get_app_name

logger = logging.getLogger(__package__)
logger.setLevel(logging.INFO)


def configure_remote(wdir: str | None = None) -> str:
    try:
        project_name = calkit.detect_project_name(wdir=wdir)
    except ValueError as e:
        raise ValueError(f"Can't detect project name: {e}")
    # If Git origin is not set, set that
    repo = git.Repo(wdir)
    try:
        repo.remote()
    except ValueError:
        warn("No Git remote defined; querying Calkit Cloud")
        # Try to fetch Git repo URL from Calkit cloud
        try:
            project = calkit.cloud.get(f"/projects/{project_name}")
            url = project["git_repo_url"]
        except Exception as e:
            raise ValueError(f"Could not fetch project info: {e}")
        if not url.endswith(".git"):
            url += ".git"
        repo.git.remote(["add", "origin", url])
    base_url = calkit.cloud.get_base_url()
    remote_url = f"{base_url}/projects/{project_name}/dvc"
    remote_name = get_app_name()
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "dvc",
            "remote",
            "add",
            "-d",
            "-f",
            remote_name,
            remote_url,
        ],
        cwd=wdir,
    )
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "dvc",
            "remote",
            "modify",
            remote_name,
            "auth",
            "custom",
        ],
        cwd=wdir,
    )
    return remote_name


def set_remote_auth(
    remote_name: str | None = None,
    always_auth: bool = False,
    wdir: str | None = None,
):
    """Get a token and set it in the local DVC config so we can interact with
    the cloud as an HTTP remote.
    """
    if remote_name is None:
        remote_name = get_app_name()
    settings = calkit.config.read()
    if settings.dvc_token is None or always_auth:
        logger.info("Creating token for DVC scope")
        token = calkit.cloud.post(
            "/user/tokens", json=dict(expires_days=365, scope="dvc")
        )["access_token"]
        settings.dvc_token = token
        settings.write()
    p1 = subprocess.run(
        [
            sys.executable,
            "-m",
            "dvc",
            "remote",
            "modify",
            "--local",
            remote_name,
            "custom_auth_header",
            "Authorization",
        ],
        cwd=wdir,
    )
    p2 = subprocess.run(
        [
            sys.executable,
            "-m",
            "dvc",
            "remote",
            "modify",
            "--local",
            remote_name,
            "password",
            f"Bearer {settings.dvc_token}",
        ],
        cwd=wdir,
    )
    if p1.returncode != 0 or p2.returncode != 0:
        raise RuntimeError(
            f"Failed to set DVC remote authentication for {remote_name}"
        )


def add_external_remote(owner_name: str, project_name: str) -> dict:
    base_url = calkit.cloud.get_base_url()
    remote_url = f"{base_url}/projects/{owner_name}/{project_name}/dvc"
    remote_name = f"{get_app_name()}:{owner_name}/{project_name}"
    subprocess.call(
        [
            sys.executable,
            "-m",
            "dvc",
            "remote",
            "add",
            "-f",
            remote_name,
            remote_url,
        ]
    )
    subprocess.call(
        [
            sys.executable,
            "-m",
            "dvc",
            "remote",
            "modify",
            remote_name,
            "auth",
            "custom",
        ]
    )
    set_remote_auth(remote_name)
    return {"name": remote_name, "url": remote_url}


def read_pipeline(wdir: str = ".") -> dict:
    fpath = os.path.join(wdir, "dvc.yaml")
    if not os.path.isfile(fpath):
        return {}
    with open(fpath) as f:
        return calkit.ryaml.load(f)


def get_remotes(wdir: str | None = None) -> dict[str, str]:
    """Get a dictionary of DVC remotes, keyed by name, with URL as the
    value.
    """
    p = subprocess.run(
        [sys.executable, "-m", "dvc", "remote", "list"],
        cwd=wdir,
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"Error getting DVC remotes: {p.stderr.strip()}")
    out = p.stdout.strip()
    if not out:
        return {}
    resp = {}
    out = out.replace("(default)", "").strip()
    is_name = True
    for token in out.split():
        token = token.strip()
        if is_name:
            name = token
        else:
            url = token
            resp[name] = url
        is_name = not is_name
    return resp


def list_paths(wdir: str | None = None, recursive=False) -> list[str]:
    """List paths tracked with DVC."""
    return [
        p.get("path", "") for p in list_files(wdir=wdir, recursive=recursive)
    ]


def list_files(wdir: str | None = None, recursive=True) -> list[dict]:
    """Return a list with all files in DVC, including their path and md5
    checksum.
    """
    import dvc.repo

    dvc_repo = dvc.repo.Repo(wdir)
    return dvc_repo.ls(".", dvc_only=True, recursive=recursive)


def get_output_revisions(path: str):
    """Get all revisions of a pipeline output."""
    pass


def out_paths_from_stage(dvc_stage: dict) -> list[str]:
    """Get output paths from a DVC stage dictionary taking into account that
    some might be single key dictionaries.
    """
    outs = dvc_stage.get("outs", [])
    out_paths = []
    for out in outs:
        if isinstance(out, str):
            out_paths.append(out)
        elif isinstance(out, dict):
            out_path = list(out.keys())[0]
            out_paths.append(out_path)
    return out_paths


def hash_file(path: str) -> dict:
    """Compute MD5 hash and size of a file.

    Returns a dictionary formatted like a DVC lock file entry.
    """
    md5_hash = hashlib.md5()
    size = 0
    with open(path, "rb") as f:
        while chunk := f.read(65536):  # 64KB chunks
            md5_hash.update(chunk)
            size += len(chunk)
    return {
        "path": path,
        "hash": "md5",
        "md5": md5_hash.hexdigest(),
        "size": size,
    }


def hash_directory(path: str) -> dict:
    """Compute MD5 hash, total size, and file count of directory.

    Returns a dictionary formatted like a DVC lock file entry.
    Uses DVC's approach: hash each file and combine into directory hash.
    """
    entries = []
    total_size = 0
    num_files = 0
    # Walk directory in sorted order for deterministic results
    for root, dirs, files in os.walk(path):
        # Sort directories to ensure consistent walk order
        dirs.sort()
        # Sort files within each directory
        for name in sorted(files):
            file_path = os.path.join(root, name)
            try:
                rel_path = Path(os.path.relpath(file_path, path)).as_posix()
                file_info = hash_file(file_path)
                # DVC format: entry with "md5" and "relpath" keys
                entries.append({"md5": file_info["md5"], "relpath": rel_path})
                total_size += file_info["size"]
                num_files += 1
            except Exception:
                continue
    # Compute directory hash from entries
    # DVC uses json.dumps with sort_keys=True to ensure deterministic output
    dir_hash = hashlib.md5(
        json.dumps(entries, sort_keys=True).encode()
    ).hexdigest()
    return {
        "path": path,
        "hash": "md5",
        "md5": f"{dir_hash}.dir",
        "size": total_size,
        "nfiles": num_files,
    }


def hash_path(path: str) -> dict:
    """Hash a file or directory and return DVC lock file entry."""
    if os.path.isdir(path):
        return hash_directory(path)
    elif os.path.isfile(path):
        return hash_file(path)
    else:
        raise ValueError(f"Path does not exist: {path}")
