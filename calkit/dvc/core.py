"""Working with DVC."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Literal

import dvc.repo
from configobj import ConfigObj
from dvc.utils.objects import cached_property
from dvc_objects.fs.base import ObjectFileSystem
from fsspec import Callback
from fsspec.callbacks import DEFAULT_CALLBACK

import calkit
from calkit.cli import warn
from calkit.config import get_app_name

logger = logging.getLogger(__package__)
logger.setLevel(logging.INFO)

USE_CK_REMOTE_BY_DEFAULT = True


class _FrozenStageWarningFilter(logging.Filter):
    """Drop DVC's "stage is frozen" warnings.

    DVC emits these for every frozen stage on every ``status``/``repro`` call
    ("... not going to be shown in the status output." and "... not going to
    be reproduced."). Frozen stages are pinned by design, so the warnings are
    noise — the substring shared by both variants is matched here.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "is frozen. Its dependencies are" not in record.getMessage()


class _StaleRWLockWarningFilter(logging.Filter):
    """Drop DVC's "auto removed it from the lock file" warnings.

    DVC records a read/write entry in its ``rwlock`` files while a command
    runs. Background pollers like ``calkit status --json -c pipeline`` (run by
    the VS Code extension) acquire read locks, and when such a process is
    killed mid-run its entries are left behind. The next DVC command notices
    the owning PID is gone and cleans them up, logging a WARNING per stale
    entry. That auto-recovery is expected and not actionable, so it's filtered.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "Auto removed it from the lock file" not in record.getMessage()


_frozen_stage_warning_filter = _FrozenStageWarningFilter()
for _name in ("dvc.repo.reproduce", "dvc.repo.status"):
    logging.getLogger(_name).addFilter(_frozen_stage_warning_filter)
logging.getLogger("dvc.rwlock").addFilter(_StaleRWLockWarningFilter())


# Default seconds to wait for DVC's repo-level lock during a pipeline run.
#
# DVC's own default is only 3 seconds (``dvc.lock.DEFAULT_TIMEOUT``), after
# which it raises "Unable to acquire lock". That is far too short whenever
# more than one DVC process briefly touches the same repo: a background
# ``calkit status`` poller (e.g. the VS Code extension), a stage whose command
# is itself ``calkit run``, or DVC's own per-stage *re-lock* (DVC releases the
# repo lock while a stage command runs---see ``dvc.stage.run.unlocked_repo``---
# and re-acquires it the instant the command finishes, which collides with any
# poller that grabbed it meanwhile). The lock is only ever held for short,
# bounded operations, so waiting generously lets these resolve instead of
# failing the run. It stays bounded (rather than waiting forever, as DVC's
# ``--wait-for-lock`` does) so a genuinely stale lock---e.g. a ``hardlink_lock``
# left behind by a crashed process on an NFS share, common on HPC clusters---is
# still surfaced as an error the user can act on.
DEFAULT_RUN_LOCK_TIMEOUT = 120.0


@contextlib.contextmanager
def dvc_lock_timeout(seconds: float):
    """Temporarily raise DVC's repo-lock acquisition timeout.

    Patches ``dvc.lock.DEFAULT_TIMEOUT`` for the duration. Both lock backends
    (``Lock`` via ``zc.lockfile`` and ``HardlinkLock`` via ``flufl.lock``) read
    that module global at acquisition time---including DVC's internal per-stage
    re-lock---so this covers every repo-lock acquisition made while the context
    is active without having to thread a flag through DVC. Never lowers the
    timeout, so a more generous outer context is preserved.
    """
    import dvc.lock

    previous = dvc.lock.DEFAULT_TIMEOUT
    if seconds > previous:
        dvc.lock.DEFAULT_TIMEOUT = seconds
    try:
        yield
    finally:
        dvc.lock.DEFAULT_TIMEOUT = previous


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


def ensure_dvc_lock_not_ignored(wdir: str | None = None) -> bool:
    """Ensure ``dvc.lock`` is not Git-ignored.

    DVC raises ``FileIsGitIgnored`` when ``dvc.lock`` is excluded by Git, which
    breaks ``dvc status`` and pipeline runs. This un-ignores it (editing the
    relevant ``.gitignore`` as needed) so those operations keep working.

    Returns True if a ``.gitignore`` was modified.
    """
    import calkit.git

    lock_path = os.path.join(wdir, "dvc.lock") if wdir else "dvc.lock"
    try:
        repo = calkit.git.get_repo(wdir)
    except Exception:
        return False
    return bool(calkit.git.ensure_path_is_not_ignored(repo, path=lock_path))


def get_running_pipeline_processes(wdir: str | None = None) -> list[dict]:
    """Return live processes holding DVC's read/write lock.

    While ``dvc repro`` runs a stage, DVC records the owning process in its
    ``rwlock`` file (under ``.dvc/tmp/rwlock``); this is the same lock that
    makes ``dvc status`` fail with a ``LockError`` mid-run. Each returned item
    is ``{"pid": int, "cmd": str}``, with stale entries (PIDs that are no
    longer running) filtered out. An empty list means no pipeline run is
    currently in progress.
    """
    import psutil  # Always available as a DVC dependency

    rwlock_path = os.path.join(wdir or ".", ".dvc", "tmp", "rwlock")
    if not os.path.isfile(rwlock_path):
        return []
    try:
        with open(rwlock_path) as f:
            lock = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    # The rwlock format is
    # {"write": {path: {pid, cmd}}, "read": {path: [{pid, cmd}]}}
    by_pid: dict[int, str] = {}
    for info in lock.get("write", {}).values():
        if isinstance(info, dict) and "pid" in info:
            by_pid[info["pid"]] = info.get("cmd", "")
    for infos in lock.get("read", {}).values():
        for info in infos or []:
            if isinstance(info, dict) and "pid" in info:
                by_pid[info["pid"]] = info.get("cmd", "")
    result = []
    for pid, cmd in by_pid.items():
        try:
            alive = psutil.pid_exists(pid)
        except Exception:
            # If we can't tell, assume the process is still alive
            alive = True
        if alive:
            result.append({"pid": pid, "cmd": cmd})
    return result


def get_dvc_lock_holder(wdir: str | None = None) -> dict | None:
    """Return the process holding DVC's repo-level lock, or ``None``.

    A long-running ``dvc pull``/``push`` (or another ``calkit run``) holds the
    repo-level lock (``.dvc/tmp/lock``), into which ``zc.lockfile`` writes the
    holder's PID. This lets callers report *what* is running---e.g. "a pull is
    in progress"---when a status check can't acquire the lock.

    Only meaningful right after a ``LockError``: the lock file persists with a
    stale PID after release, so the recorded PID is the genuine holder only when
    the lock is actually held (i.e. we just failed to acquire it). Returns
    ``{"pid": int, "cmd": str}`` or ``None`` if it can't be determined (no lock
    file, an unparseable/hardlink-lock file, or the process is gone).
    """
    import psutil  # Always available as a DVC dependency

    lock_path = os.path.join(wdir or ".", ".dvc", "tmp", "lock")
    try:
        with open(lock_path) as f:
            content = f.read()
    except OSError:
        return None
    try:
        # zc.lockfile writes " <pid>\n"; hardlink locks use another format.
        pid = int(content.split()[0])
    except (ValueError, IndexError):
        return None
    try:
        proc = psutil.Process(pid)
        cmdline = proc.cmdline()
        # Drop the interpreter's full path so the command reads cleanly, e.g.
        # "calkit pull" rather than "/.../python /.../calkit pull".
        cmd = " ".join(
            ([os.path.basename(cmdline[0])] + cmdline[1:])
            if cmdline
            else [proc.name()]
        )
    except Exception:
        return None
    return {"pid": pid, "cmd": cmd}


def run_dvc_command(
    argv: list[str],
    cwd: str | None = None,
    lock_timeout: float | None = None,
) -> int:
    """Run a DVC command, optionally in a specific working directory.

    Uses DVC's --cd flag to handle directory changes.

    If ``lock_timeout`` is given, DVC waits that many seconds for the repo lock
    instead of failing after its 3s default. ``pull``/``push`` use this because
    a background ``calkit status`` poller (e.g. the VS Code extension) or a
    concurrent run can briefly hold the lock---the original symptom in issue
    #942, where ``calkit pull`` failed and succeeded on a second try. See
    :func:`dvc_lock_timeout`.
    """
    if cwd:
        argv = ["--cd", cwd] + argv
    if lock_timeout is not None:
        with dvc_lock_timeout(lock_timeout):
            return run_dvc_cli(argv)
    return run_dvc_cli(argv)


def make_remote_name(use_ck: bool = USE_CK_REMOTE_BY_DEFAULT) -> str:
    """Generate a DVC remote name based on the app name or a default."""
    return get_app_name() if not use_ck else "calkit"


def detect_calkit_remote_type(
    name: str, url: str
) -> Literal["ck", "http"] | None:
    """Detect whether a DVC remote is a Calkit remote, and its scheme.

    Returns ``"ck"`` or ``"http"`` for recognized Calkit remotes (including
    external project remotes named like ``"<base>:<owner>/<project>"``), or
    ``None`` if the remote isn't a Calkit remote we recognize.
    """
    candidates = {
        make_remote_name(use_ck=False),
        make_remote_name(use_ck=True),
    }
    name_matches = any(
        name == c or name.startswith(f"{c}:") for c in candidates
    )
    if not name_matches:
        return None
    if url.startswith("ck://"):
        return "ck"
    if url.startswith("http"):
        return "http"
    return None


def configure_remote(
    wdir: str | None = None, use_ck: bool = USE_CK_REMOTE_BY_DEFAULT
) -> str:
    """Configure a DVC remote for the current project."""
    try:
        project_name = calkit.detect_project_name(wdir=wdir)
    except ValueError as e:
        raise ValueError(f"Can't detect project name: {e}")
    # If Git origin is not set, set that
    repo = calkit.git.get_repo(wdir)
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
    remote_name = make_remote_name(use_ck=use_ck)
    if use_ck:
        clear_remote_local_http_auth(remote_name=remote_name, wdir=wdir)
        remote_url = f"ck://{project_name}"
    else:
        base_url = calkit.cloud.get_base_url()
        remote_url = f"{base_url}/projects/{project_name}/dvc"
    result = run_dvc_command(
        ["remote", "add", "-d", "-f", remote_name, remote_url],
        cwd=wdir,
    )
    if result != 0:
        raise RuntimeError(f"Failed to add DVC remote {remote_name}")
    if not use_ck:
        result = run_dvc_command(
            ["remote", "modify", remote_name, "auth", "custom"],
            cwd=wdir,
        )
        if result != 0:
            raise RuntimeError(
                f"Failed to configure auth for DVC remote {remote_name}"
            )
    return remote_name


def clear_remote_local_http_auth(
    remote_name: str | None = None, wdir: str | None = None
) -> None:
    """Remove HTTP-specific local auth settings for a DVC remote.

    This clears values written to ``.dvc/config.local`` by HTTP auth setup.
    """
    if remote_name is None:
        remote_name = make_remote_name()
    config_local = Path(wdir or ".") / ".dvc" / "config.local"
    if not config_local.is_file():
        return
    cfg = ConfigObj(str(config_local), encoding="utf-8")
    section_name = f'remote "{remote_name}"'
    remote = cfg.get(section_name)
    if not isinstance(remote, dict):
        return
    changed = False
    for option in ("custom_auth_header", "password", "auth"):
        if option in remote:
            remote.pop(option)
            changed = True
    if not changed:
        return
    if not remote:
        cfg.pop(section_name, None)
    cfg.write()


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
        remote_name = make_remote_name()
    # Check if this is a ck:// remote (doesn't need HTTP auth)
    remotes = get_remotes(wdir=wdir)
    remote_url = remotes.get(remote_name, "")
    if remote_url.startswith("ck://"):
        clear_remote_local_http_auth(remote_name=remote_name, wdir=wdir)
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


def add_external_remote(
    owner_name: str,
    project_name: str,
    use_ck: bool = USE_CK_REMOTE_BY_DEFAULT,
) -> dict:
    if use_ck:
        remote_url = f"ck://{owner_name}/{project_name}"
    else:
        base_url = calkit.cloud.get_base_url()
        remote_url = f"{base_url}/projects/{owner_name}/{project_name}/dvc"
    remote_name = (
        f"{make_remote_name(use_ck=use_ck)}:{owner_name}/{project_name}"
    )
    run_dvc_command(["remote", "add", "-f", remote_name, remote_url])
    if not use_ck:
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


def _path_item_as_posix(item):
    # Renamed entries are dicts like {"old": ..., "new": ...}.
    if isinstance(item, dict):
        return {k: Path(v).as_posix() for k, v in item.items()}
    return Path(item).as_posix()


def data_status_as_posix(data_status: dict) -> dict:
    """Convert all paths in DVC data status to posix format.

    We skip the ``git`` entry since Git already formats as posix.
    """
    data_status_fmt = {}
    for cat, obj in data_status.items():
        if cat == "git":
            data_status_fmt[cat] = obj
        elif isinstance(obj, list):
            data_status_fmt[cat] = [_path_item_as_posix(p) for p in obj]
        elif isinstance(obj, dict):
            obj_fmt = {}
            for cat2, obj_i in obj.items():
                obj_fmt[cat2] = [_path_item_as_posix(p) for p in obj_i]
            data_status_fmt[cat] = obj_fmt
        else:
            data_status_fmt[cat] = obj
    return data_status_fmt


def status_as_posix(status: dict) -> dict:
    """Convert all paths in repo status to posix format."""
    status_fmt = {}
    for stage_name, st_list in status.items():
        st_list_fmt = []
        for st_dict in st_list:
            if isinstance(st_dict, str):
                st_list_fmt.append(st_dict)
                continue
            st_dict_fmt = {}
            for st_cat, path_st_dict in st_dict.items():
                if not isinstance(path_st_dict, dict):
                    # e.g. {"changed command": "python src/new-script.py"}
                    st_dict_fmt[st_cat] = path_st_dict
                    continue
                path_st_dict_fmt = {}
                for p, st in path_st_dict.items():
                    path_st_dict_fmt[Path(p).as_posix()] = st
                st_dict_fmt[st_cat] = path_st_dict_fmt
            st_list_fmt.append(st_dict_fmt)
        status_fmt[stage_name] = st_list_fmt
    return status_fmt
