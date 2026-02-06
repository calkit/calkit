"""Functionality related to environments."""

import hashlib
import json
import os
import platform
from pathlib import Path

from pydantic import BaseModel
from sqlitedict import SqliteDict

import calkit

DOCKER_ARCHS = [
    "amd64",
    "arm64",
    "arm-v7",
    "arm-v6",
    "ppc64le",
    "s390x",
    "386",
    "riscv64",
]
CONDA_VENV_ARCHS = [
    "osx-arm64",
    "osx-64",
    "linux-aarch64",
    "linux-ppc64le",
    "linux-64",
    "win-64",
]
ENV_CHECK_CACHE_TTL_SECONDS = 3600
KINDS_NO_CHECK = ["_system", "slurm", "ssh"]


def get_env_lock_dir(wdir: str | None = None) -> str:
    env_lock_dir = os.path.join(".calkit", "env-locks")
    if wdir is not None:
        env_lock_dir = os.path.join(wdir, env_lock_dir)
    return env_lock_dir


def _conda_venv_platform() -> str:
    sys = platform.system().lower()
    mach = platform.machine().lower()
    if sys == "darwin":
        return "osx-arm64" if mach in ("arm64", "aarch64") else "osx-64"
    if sys == "linux":
        if mach in ("arm64", "aarch64"):
            return "linux-aarch64"
        elif mach in ("ppc64le",):
            return "linux-ppc64le"
        else:
            return "linux-64"
    if sys == "windows":
        return "win-64"
    # Fallback for unusual platforms
    return f"{sys}-{mach}"


def _docker_platform() -> str:
    """Get Docker platform string (arch part only)."""
    mach = platform.machine().lower()
    # Map common platform.machine() outputs to Docker arch names
    if mach in ("x86_64", "amd64"):
        return "amd64"
    elif mach in ("aarch64", "arm64"):
        return "arm64"
    elif mach in ("armv7l", "armv7"):
        return "arm-v7"
    elif mach in ("armv6l", "armv6"):
        return "arm-v6"
    elif mach == "ppc64le":
        return "ppc64le"
    elif mach == "s390x":
        return "s390x"
    elif mach in ("i386", "i686"):
        return "386"
    elif mach == "riscv64":
        return "riscv64"
    # Fallback
    return mach


def get_all_docker_lock_fpaths(
    env_name: str,
    wdir: str | None = None,
    as_posix: bool = True,
) -> list[str]:
    """Return docker environment lock file paths for every supported
    architecture.

    This intentionally excludes legacy (pre-arch) lock file locations;
    legacy handling is performed separately.
    """
    env_lock_dir = get_env_lock_dir(wdir=wdir)
    docker_dir = os.path.join(env_lock_dir, env_name)
    fpaths = [
        os.path.join(docker_dir, arch + ".json") for arch in DOCKER_ARCHS
    ]
    if as_posix:
        fpaths = [Path(p).as_posix() for p in fpaths]
    return fpaths


def get_all_conda_lock_fpaths(
    env_name: str,
    wdir: str | None = None,
    as_posix: bool = True,
) -> list[str]:
    """Return conda environment lock file paths for every supported
    architecture.
    """
    env_lock_dir = get_env_lock_dir(wdir=wdir)
    env_lock_dir = os.path.join(env_lock_dir, env_name)
    fpaths = [
        os.path.join(env_lock_dir, arch + ".yml") for arch in CONDA_VENV_ARCHS
    ]
    if as_posix:
        fpaths = [Path(p).as_posix() for p in fpaths]
    return fpaths


def get_all_venv_lock_fpaths(
    env_name: str,
    wdir: str | None = None,
    as_posix: bool = True,
) -> list[str]:
    """Return venv environment lock file paths for every supported
    architecture.
    """
    env_lock_dir = get_env_lock_dir(wdir=wdir)
    venv_dir = os.path.join(env_lock_dir, env_name)
    fpaths = [
        os.path.join(venv_dir, arch + ".txt") for arch in CONDA_VENV_ARCHS
    ]
    if as_posix:
        fpaths = [Path(p).as_posix() for p in fpaths]
    return fpaths


def get_env_lock_fpath(
    env: dict,
    env_name: str,
    wdir: str | None = None,
    as_posix: bool = True,
    legacy: bool = False,
    for_dvc: bool = False,
) -> str | None:
    """Create the environment lock file path.

    If `for_dvc` is True, return the directory containing the lock file
    instead of the lock file itself for Docker, venv, and conda environments,
    which store a separate lock file for each platform/architecture.
    """
    env_lock_dir = get_env_lock_dir(wdir=wdir)
    env_kind = env.get("kind")
    lock_fpath = os.path.join(env_lock_dir, env_name)
    if env_kind == "docker":
        if legacy:
            lock_fpath += ".json"
        else:
            lock_fpath = os.path.join(
                env_lock_dir, env_name, _docker_platform() + ".json"
            )
            if for_dvc:
                lock_fpath = os.path.dirname(lock_fpath)
    elif env_kind == "uv":
        env_dir = os.path.dirname(env.get("path", ""))
        if env_dir:
            lock_fpath = os.path.join(env_dir, "uv.lock")
        else:
            lock_fpath = "uv.lock"
    elif env_kind in ["venv", "uv-venv"]:
        if legacy:
            lock_fpath += ".txt"
        else:
            lock_fpath = os.path.join(
                env_lock_dir,
                env_name,
                _conda_venv_platform() + ".txt",
            )
            if for_dvc:
                lock_fpath = os.path.dirname(lock_fpath)
    elif env_kind == "conda":
        if legacy:
            lock_fpath += ".yml"
        else:
            lock_fpath = os.path.join(
                env_lock_dir,
                env_name,
                _conda_venv_platform() + ".yml",
            )
            if for_dvc:
                lock_fpath = os.path.dirname(lock_fpath)
    elif env_kind == "matlab":
        lock_fpath += ".json"
    elif env_kind == "julia":
        env_path = env.get("path")
        if env_path is None:
            raise ValueError(
                "Julia environments require a path pointing to Project.toml"
            )
        env_fname = os.path.basename(env_path)
        if not env_fname == "Project.toml":
            raise ValueError(
                "Julia environments require a path pointing to Project.toml"
            )
        # Simply replace Project.toml with Manifest.toml
        env_dir = os.path.dirname(env_path)
        lock_fpath = os.path.join(env_dir, "Manifest.toml")
    else:
        return
    if as_posix:
        lock_fpath = Path(lock_fpath).as_posix()
    return lock_fpath


def get_cache_db(name="cache") -> SqliteDict:
    env_check_cache_dir = os.path.join(
        os.path.expanduser("~"), ".calkit", "env-checks"
    )
    os.makedirs(env_check_cache_dir, exist_ok=True)
    env_check_cache_path = os.path.join(env_check_cache_dir, f"{name}.sqlite")
    return SqliteDict(env_check_cache_path)


def make_cache_key(env_name: str, wdir: str | None = None) -> str:
    if wdir is None:
        wdir = os.getcwd()
    else:
        wdir = os.path.abspath(wdir)
    return f"{wdir}::{env_name}"


def hash_dict(d: dict) -> str:
    json_str = json.dumps(d, sort_keys=True)
    return hashlib.sha256(json_str.encode()).hexdigest()


def calc_data_for_env(
    env_name: str, env: dict, wdir: str | None = None
) -> dict:
    """Hash important data from the environment.

    This includes:
    1. A hash of the env definition.
    2. A hash of the env path file, if present.
    3. A hash of the env prefix, if applicable.
    4. A hash of the env lock file, if applicable.
    """

    def get_cached_md5(path: str) -> str | None:
        """Get a cached MD5 hash for a path, recalculating if mtime doesn't
        match the cached mtime.
        """
        key = os.path.abspath(path)
        cached_data = {}
        with get_cache_db(name="md5s") as db:
            if key in db:
                cached_data = db[key]
                if os.path.exists(path):
                    mtime = os.path.getmtime(path)
                    if mtime == cached_data.get("mtime"):
                        return cached_data.get("md5")
        if os.path.exists(path):
            md5 = calkit.get_md5(path)
            mtime = os.path.getmtime(path)
            with get_cache_db(name="md5s") as db:
                db[key] = {"md5": md5, "mtime": mtime}
                db.commit()
            return md5

    if wdir is None:
        wdir = os.getcwd()
    else:
        wdir = os.path.abspath(wdir)
    env_hash = hash_dict(env)
    env_path = env.get("path", "")
    env_path_hash = None
    if env_path:
        env_path_full = os.path.join(wdir, env_path)
        if os.path.isfile(env_path_full):
            env_path_hash = calkit.get_md5(env_path_full)
    env_prefix = env.get("prefix", "")
    env_prefix_hash = None
    if env_prefix:
        env_prefix_full = os.path.join(wdir, env_prefix)
        if os.path.exists(env_prefix_full):
            env_prefix_hash = get_cached_md5(env_prefix_full)
        else:
            env_prefix_hash = None
    env_lock_hash = None
    env_lock_fpath = get_env_lock_fpath(env_name=env_name, env=env, wdir=wdir)
    if env_lock_fpath is not None:
        env_lock_full = os.path.join(wdir, env_lock_fpath)
        if os.path.isfile(env_lock_full):
            env_lock_hash = calkit.get_md5(env_lock_full)
    return {
        "hashes": {
            "env_hash": env_hash,
            "env_path_hash": env_path_hash,
            "env_prefix_hash": env_prefix_hash,
            "env_lock_hash": env_lock_hash,
        },
        "checked_at": calkit.utcnow(),
    }


def check_cache(env_name: str, env: dict, wdir: str | None = None) -> bool:
    """Check if the environment is up-to-date based on cached data."""
    if wdir is None:
        wdir = os.getcwd()
    else:
        wdir = os.path.abspath(wdir)
    with get_cache_db() as db:
        key = make_cache_key(env_name=env_name, wdir=wdir)
        if key not in db:
            return False
        cached_data = db[key]
    # If our last check failed, we're definitely not up-to-date
    if not cached_data.get("success", False):
        return False
    # Check if this environment is up-to-date
    current_data = calc_data_for_env(env_name=env_name, env=env, wdir=wdir)
    time_diff = current_data["checked_at"] - cached_data.get("checked_at")
    if time_diff.total_seconds() > ENV_CHECK_CACHE_TTL_SECONDS:
        return False
    if env.get("path") and not current_data["hashes"]["env_path_hash"]:
        return False
    if env.get("prefix") and not current_data["hashes"]["env_prefix_hash"]:
        return False
    if (
        get_env_lock_fpath(env=env, env_name=env_name, wdir=wdir)
        and not current_data["hashes"]["env_lock_hash"]
    ):
        return False
    return current_data["hashes"] == cached_data["hashes"]


def save_cache(
    env_name: str, env: dict, wdir: str | None = None, success: bool = True
) -> dict:
    with get_cache_db() as db:
        key = make_cache_key(env_name=env_name, wdir=wdir)
        data = calc_data_for_env(env_name=env_name, env=env, wdir=wdir)
        data["success"] = success
        db[key] = data
        db.commit()
    return data


def check_all_in_pipeline(
    ck_info: dict | None = None,
    wdir: str | None = None,
    targets: list[str] | None = None,
    force: bool = False,
) -> dict:
    """Check all environments in the pipeline, caching for efficiency.

    The cache file is a simple JSON file keyed by project path.
    Each object inside tracks the last check timestamp, pass/fail,
    and some sort of hash(es) for the important file content involved.
    """
    import calkit
    from calkit.cli.check import check_environment

    # TODO: ``check_environment`` should be able to take a wdir argument
    if wdir is not None:
        raise ValueError(
            "Can currently only run from current working directory"
        )
    res = {}
    # First get a list of environments used in the pipeline
    if ck_info is None:
        ck_info = calkit.load_calkit_info(wdir=wdir)
    stages = ck_info.get("pipeline", {}).get("stages", {})
    if targets:
        stages = {k: v for k, v in stages.items() if k in targets}
    envs_in_pipeline = [stage.get("environment") for stage in stages.values()]
    envs_in_pipeline = [
        e for e in envs_in_pipeline if e and not (str(e)).startswith("_")
    ]
    envs_in_pipeline = list(set(envs_in_pipeline))
    envs = ck_info.get("environments", {})
    for env_name in envs_in_pipeline:
        env = envs.get(env_name)
        if env.get("kind") in KINDS_NO_CHECK:
            continue
        if not force:
            up_to_date = check_cache(env_name=env_name, env=env, wdir=wdir)
            if up_to_date:
                res[env_name] = {"success": True, "cached": True}
                continue
        try:
            check_environment(env_name, verbose=False)
            res[env_name] = save_cache(
                env_name=env_name, env=env, wdir=wdir, success=True
            )
        except Exception:
            res[env_name] = save_cache(
                env_name=env_name, env=env, wdir=wdir, success=False
            )
    return res


class EnvDetectResult(BaseModel):
    name: str
    env: dict
    exists: bool


def env_from_name_or_path(
    name_or_path: str,
    ck_info: dict | None = None,
    path_only: bool = False,
) -> EnvDetectResult:
    """Get an environment from its name or path.

    Names take precedence.
    """

    def name_from_path(path: str, all_env_names: list[str]) -> str:
        dirname = os.path.basename(os.path.dirname(env_path))
        # TODO: Increment env name if already exists
        return dirname or "main"

    if ck_info is None:
        ck_info = calkit.load_calkit_info()
    envs = ck_info.get("environments", {})
    all_env_names = list(envs.keys())
    for env_name, env in envs.items():
        if (not path_only and env_name == name_or_path) or env.get(
            "path"
        ) == name_or_path:
            return EnvDetectResult(name=env_name, env=env, exists=True)
    env_path = name_or_path
    if os.path.isfile(env_path):
        if env_path.endswith("requirements.txt"):
            # TODO: Detect if uv is installed, and use a plain venv if not
            # TODO: Detect appropriate prefix
            return EnvDetectResult(
                name=name_from_path(env_path, all_env_names),
                env={"kind": "uv-venv", "path": env_path},
                exists=False,
            )
        elif env_path.endswith(".yml") or env_path.endswith(".yaml"):
            # This is probably a Conda env
            with open(env_path) as f:
                env_spec = calkit.ryaml.load(f)
            if "dependencies" not in env_spec:
                raise ValueError(
                    f"Could not detect environment from: {name_or_path}"
                )
            return EnvDetectResult(
                name=env_spec.get(
                    "name", name_from_path(env_path, all_env_names)
                ),
                env={"kind": "conda", "path": env_path},
                exists=False,
            )
        elif env_path.endswith("pyproject.toml"):
            # This is a uv project env
            return EnvDetectResult(
                name=name_from_path(env_path, all_env_names),
                env={
                    "kind": "uv",
                    "path": env_path,
                },
                exists=False,
            )
        elif env_path.endswith("pixi.toml"):
            # This is a pixi env
            pass  # TODO
        elif env_path.endswith("Project.toml"):
            # This is a Julia env
            pass  # TODO
        elif "dockerfile" in env_path.lower():
            # This is a Docker env
            pass  # TODO
    raise ValueError(f"Environment could not be detected from: {name_or_path}")


def env_from_name_and_or_path(
    name: str | None, path: str | None, ck_info: dict | None = None
) -> EnvDetectResult:
    """Detect an environment from its name and/or path."""
    if ck_info is None:
        ck_info = calkit.load_calkit_info()
    envs = ck_info.get("environments", {})
    if name and name in envs:
        env = envs[name]
        if path and env.get("path") != path:
            raise ValueError(
                f"Environment '{name}' exists but has a different path "
                f"('{env.get('path')}') than provided ('{path}')"
            )
        return EnvDetectResult(name=name, env=envs[name], exists=True)
    if path:
        res = env_from_name_or_path(
            name_or_path=path, ck_info=ck_info, path_only=True
        )
        if name:
            res.name = name
        return res
    raise ValueError(
        f"Environment could not be detected from name: {name} "
        f"and/or path: {path}"
    )
