"""Working with DVC."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import dvc.repo
import git
from dvc.utils.objects import cached_property
from dvc_objects.fs.base import ObjectFileSystem
from fsspec import Callback
from fsspec.callbacks import DEFAULT_CALLBACK

import calkit
from calkit.cli import warn
from calkit.config import get_app_name

logger = logging.getLogger(__package__)
logger.setLevel(logging.INFO)


class CalkitDVCFileSystem(ObjectFileSystem):
    """DVC-facing filesystem wrapper for the ``ck://`` scheme."""

    protocol = "ck"

    @classmethod
    def _strip_protocol(cls, path: str) -> str:
        prefix = f"{cls.protocol}://"
        if path.startswith(prefix):
            return path[len(prefix) :]
        return path

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cache for batch operation results in the DVC wrapper
        # Format: {path: {'info': {...}, 'content': bytes, 'exists': bool}}
        self._cache: dict[str, dict[str, Any]] = {}

    @cached_property
    def fs(self):
        from calkit.fs import CalkitFileSystem

        # Pass endpointurl from DVC config to CalkitFileSystem
        kwargs = {}
        if "endpointurl" in self.config:
            kwargs["endpoint_url"] = self.config["endpointurl"]
        fs = CalkitFileSystem(**kwargs)

        # DVC may call `self.fs.info(...)` directly, bypassing this wrapper's
        # `info()` method. Wrap low-level info calls so cache ownership stays
        # in CalkitDVCFileSystem.
        orig_info = fs.info

        def cached_info(path: str, **inner_kwargs):
            if path in self._cache and "info" in self._cache[path]:
                return self._cache[path]["info"]
            info = orig_info(path, **inner_kwargs)
            if path not in self._cache:
                self._cache[path] = {}
            self._cache[path]["info"] = info
            return info

        fs.info = cached_info  # type: ignore[method-assign]
        return fs

    def _extract_owner_project(self) -> tuple[str, str] | None:
        """Extract owner and project from the path_info."""
        try:
            # path_info is an ObjectPath with a path attribute like
            # "owner/project"
            path = self.path_info.path  # type: ignore
            parts = path.split("/", 1)
            if len(parts) >= 2:
                return parts[0], parts[1]
        except Exception:
            pass
        return None

    def find(self, path, **kwargs):
        """Override find to optimize DVC hex-prefixed searches.

        DVC often passes lists of 256+ hex-prefixed paths
        (files/md5/00 through /ff).
        Instead of searching each individually, we find the common parent and
        search once.
        """
        # Handle list of paths - find common parent and search once
        if isinstance(path, list) and len(path) > 1:
            # Strip trailing slashes and split into parts
            paths = [p.rstrip("/") for p in path]
            parts_list = [p.split("/") for p in paths]
            # Find the deepest common parent directory
            common_parts = []
            min_len = min(len(p) for p in parts_list)
            for i in range(min_len):
                if all(parts[i] == parts_list[0][i] for parts in parts_list):
                    common_parts.append(parts_list[0][i])
                else:
                    break
            # Only optimize if we have a common md5 ancestor with reasonable
            # depth
            # (prevents going too shallow like just 'files')
            if len(common_parts) >= 3 and "md5" in common_parts:
                # Add trailing slash to indicate it's a directory, not a file
                parent = "/".join(common_parts) + "/"
                return super().find(parent, **kwargs)
        # Single path -- pass through to parent
        return super().find(path, **kwargs)

    def info(
        self,
        path,
        callback: Callback = DEFAULT_CALLBACK,
        batch_size=None,
        return_exceptions=False,
        **kwargs,
    ):
        if isinstance(path, list) and hasattr(self.fs, "info_many"):
            # Separate cached vs uncached paths
            uncached_paths = []
            for p in path:
                cached_entry = self._cache.get(p, {})
                # Skip if we have info OR if we know it doesn't exist
                if (
                    "info" not in cached_entry
                    and cached_entry.get("exists") is not False
                ):
                    uncached_paths.append(p)
            # Only fetch info for uncached paths
            if uncached_paths:
                infos = self.fs.info_many(uncached_paths, **kwargs)
                # Cache the newly fetched info
                for p in uncached_paths:
                    exists = p in infos and isinstance(infos[p], dict)
                    if p not in self._cache:
                        self._cache[p] = {}
                    self._cache[p]["exists"] = exists
                    if exists:
                        self._cache[p]["info"] = infos[p]
            # Build result list from cache, raising FileNotFoundError for
            # missing
            result = []
            for p in path:
                cached_entry = self._cache.get(p, {})
                if "info" in cached_entry:
                    result.append(cached_entry["info"])
                else:
                    # We know it doesn't exist (either from cache or fresh fetch)
                    error = FileNotFoundError(p)
                    if return_exceptions:
                        result.append(error)
                    else:
                        raise error
            return result
        if not isinstance(path, str):
            return super().info(
                path,
                callback=callback,
                batch_size=batch_size,
                return_exceptions=return_exceptions,
                **kwargs,
            )
        # Check cache for single path
        if path in self._cache and "info" in self._cache[path]:
            return self._cache[path]["info"]
        # Call underlying fs.info and cache the result
        info = self.fs.info(path, **kwargs)
        if path not in self._cache:
            self._cache[path] = {}
        self._cache[path]["info"] = info
        return info

    def exists(
        self,
        path,
        callback: Callback = DEFAULT_CALLBACK,
        batch_size=None,
        **kwargs,
    ):
        if isinstance(path, list) and hasattr(self.fs, "info_many"):
            # Separate cached vs uncached paths
            uncached_paths = []
            for p in path:
                if p not in self._cache or "exists" not in self._cache[p]:
                    uncached_paths.append(p)
            # Only fetch info for uncached paths
            # Use info_many to get and cache both info and existence
            if uncached_paths:
                infos = self.fs.info_many(uncached_paths, **kwargs)
                for p in uncached_paths:
                    exists = p in infos and isinstance(infos[p], dict)
                    if p not in self._cache:
                        self._cache[p] = {}
                    self._cache[p]["exists"] = exists
                    if exists:
                        self._cache[p]["info"] = infos[p]
            # Build result list from cache
            results = []
            for p in path:
                cached_entry = self._cache.get(p, {})
                results.append(cached_entry.get("exists", False))
            return results
        # Check cache for single path
        if path in self._cache and "exists" in self._cache[path]:
            return self._cache[path]["exists"]
        return super().exists(path, callback=callback, batch_size=batch_size)


def register_ck_scheme() -> None:
    """Register ``ck://`` support in DVC runtime schema and FS registry."""
    from dvc.config_schema import REMOTE_COMMON, REMOTE_SCHEMAS, SCHEMA, ByUrl
    from dvc_objects.fs import known_implementations

    # Include endpointurl for multi-cloud support
    ck_schema = {**REMOTE_COMMON, "endpointurl": str}
    REMOTE_SCHEMAS.setdefault("ck", ck_schema)
    SCHEMA["remote"] = {str: ByUrl(REMOTE_SCHEMAS)}
    known_implementations["ck"] = {
        "class": "calkit.dvc.CalkitDVCFileSystem",
        "err": "ck is supported, but requires calkit-python to be installed",
    }


def run_dvc_cli(argv: list[str] | None = None) -> int:
    """Run DVC CLI with ``ck://`` scheme pre-registered."""
    from dvc.cli import main as dvc_main

    register_ck_scheme()
    return dvc_main(argv)


def get_dvc_repo(wdir: str | None = None) -> dvc.repo.Repo:
    """Return a DVC repo with ``ck://`` scheme support registered."""
    register_ck_scheme()
    return dvc.repo.Repo(wdir)


def run_dvc_command(argv: list[str], cwd: str | None = None) -> int:
    """Run a DVC command, optionally in a specific working directory.

    Uses DVC's --cd flag to handle directory changes.
    """
    if cwd:
        argv = ["--cd", cwd] + argv
    return run_dvc_cli(argv)


def configure_remote(wdir: str | None = None) -> str:
    """Configure a DVC remote for the current project.

    TODO: Use the ck:// scheme.
    """
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
    result = run_dvc_command(
        ["remote", "add", "-d", "-f", remote_name, remote_url],
        cwd=wdir,
    )
    if result != 0:
        raise RuntimeError(f"Failed to add DVC remote {remote_name}")
    result = run_dvc_command(
        ["remote", "modify", remote_name, "auth", "custom"],
        cwd=wdir,
    )
    if result != 0:
        raise RuntimeError(
            f"Failed to configure auth for DVC remote {remote_name}"
        )
    return remote_name


def set_remote_auth(
    remote_name: str | None = None,
    always_auth: bool = False,
    wdir: str | None = None,
):
    """Get a token and set it in the local DVC config so we can interact with
    the cloud as an HTTP remote.

    Note: This only applies to HTTP remotes. The ck:// scheme doesn't need
    HTTP auth configuration.
    """
    if remote_name is None:
        remote_name = get_app_name()
    # Check if this is a ck:// remote (doesn't need HTTP auth)
    remotes = get_remotes(wdir=wdir)
    remote_url = remotes.get(remote_name, "")
    if remote_url.startswith("ck://"):
        logger.info(
            f"Remote {remote_name} uses ck:// scheme; skipping HTTP auth setup"
        )
        return
    settings = calkit.config.read()
    if settings.dvc_token is None or always_auth:
        logger.info("Creating token for DVC scope")
        token = calkit.cloud.post(
            "/user/tokens", json=dict(expires_days=365, scope="dvc")
        )["access_token"]
        settings.dvc_token = token
        settings.write()
    r1 = run_dvc_command(
        [
            "remote",
            "modify",
            "--local",
            remote_name,
            "custom_auth_header",
            "Authorization",
        ],
        cwd=wdir,
    )
    r2 = run_dvc_command(
        [
            "remote",
            "modify",
            "--local",
            remote_name,
            "password",
            f"Bearer {settings.dvc_token}",
        ],
        cwd=wdir,
    )
    if r1 != 0 or r2 != 0:
        raise RuntimeError(
            f"Failed to set DVC remote authentication for {remote_name}"
        )


def add_external_remote(owner_name: str, project_name: str) -> dict:
    base_url = calkit.cloud.get_base_url()
    remote_url = f"{base_url}/projects/{owner_name}/{project_name}/dvc"
    remote_name = f"{get_app_name()}:{owner_name}/{project_name}"
    run_dvc_command(["remote", "add", "-f", remote_name, remote_url])
    run_dvc_command(["remote", "modify", remote_name, "auth", "custom"])
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
    from dvc.exceptions import NotDvcRepoError

    try:
        repo = get_dvc_repo(wdir)
    except NotDvcRepoError:
        return {}
    try:
        remote_cfg = repo.config.get("remote", {})
        if not isinstance(remote_cfg, dict):
            return {}
        remotes: dict[str, str] = {}
        for name, cfg in remote_cfg.items():
            if isinstance(name, str) and isinstance(cfg, dict):
                url = cfg.get("url")
                if isinstance(url, str):
                    remotes[name] = url
        return remotes
    finally:
        repo.close()


def list_paths(wdir: str | None = None, recursive=False) -> list[str]:
    """List paths tracked with DVC."""
    return [
        p.get("path", "") for p in list_files(wdir=wdir, recursive=recursive)
    ]


def list_files(wdir: str | None = None, recursive=True) -> list[dict]:
    """Return a list with all files in DVC, including their path and md5
    checksum.
    """
    dvc_repo = get_dvc_repo(wdir)
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
