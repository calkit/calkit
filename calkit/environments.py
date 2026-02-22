"""Functionality related to environments."""

import glob
import hashlib
import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import cast

import toml
import yaml
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
DEFAULT_PYTHON_VERSION = "3.14"
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


def language_from_env(env: dict) -> str | None:
    kind = env.get("kind")
    if kind == "julia":
        return "julia"
    if kind == "renv":
        return "r"
    if kind == "matlab":
        return "matlab"
    if kind in ["conda", "pixi", "uv", "uv-venv", "venv"]:
        return "python"
    if kind == "docker" and "texlive" in env.get("image", "").lower():
        return "latex"
    return None


def _get_julia_version() -> str:
    """Detect the active Julia version.

    Returns
    -------
    str
        Julia version string (e.g., "1.10.1"). Defaults to "1.10" if
        detection fails.
    """
    try:
        result = subprocess.run(
            ["julia", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Parse output like "julia version 1.10.1"
            output = result.stdout.strip()
            # Extract version number
            parts = output.split()
            for part in parts:
                # Check if this part looks like a version
                if part and part[0].isdigit():
                    # Return major.minor version
                    version_parts = part.split(".")
                    if len(version_parts) >= 2:
                        return f"{version_parts[0]}.{version_parts[1]}"
        return "1.10"
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        # If Julia is not available or detection fails, default to 1.10
        return "1.10"


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
    elif env_kind == "renv":
        env_path = env.get("path")
        if env_path is None:
            raise ValueError(
                "renv environments require a path pointing to DESCRIPTION"
            )
        env_fname = os.path.basename(env_path)
        if not env_fname == "DESCRIPTION":
            raise ValueError(
                "renv environments require a path pointing to DESCRIPTION"
            )
        # Replace DESCRIPTION with renv.lock
        env_dir = os.path.dirname(env_path)
        lock_fpath = os.path.join(env_dir, "renv.lock")
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


class EnvForStageResult(BaseModel):
    """Result of detecting or creating an environment for a stage."""

    name: str
    env: dict
    exists: bool
    spec_path: str | None = None
    spec_content: str | None = None
    dependencies: list[str] = []
    created_from_dependencies: bool = False


def make_env_name(path: str, all_env_names: list[str], kind: str) -> str:
    """Generate a unique environment name based on path, existing
    names, and kind.

    Parameters
    ----------
    path : str
        Path to the environment spec file.
    all_env_names : list[str]
        List of existing environment names.
    kind : str
        Environment kind (e.g., "uv-venv", "conda", "renv", "julia").

    Returns
    -------
    str
        A unique environment name.
    """
    dirname = os.path.basename(os.path.dirname(path))
    # If this is the first env in the project, call it main
    if not all_env_names:
        return dirname or "main"
    # Name based on dirname if possible
    if dirname and dirname not in all_env_names:
        return dirname
    # Try a name based on the dirname and kind
    if dirname and dirname in all_env_names:
        name = f"{dirname}-{kind}"
        if name not in all_env_names:
            return name
    # Otherwise increment a number after the kind
    n = 1
    name = f"{kind}{n}"
    while name in all_env_names:
        n += 1
        name = f"{kind}{n}"
    return name


def env_from_name_or_path(
    name_or_path: str | None = None,
    ck_info: dict | None = None,
    path_only: bool = False,
    language: str | None = None,
) -> EnvDetectResult:
    """Get an environment from its name or path.

    Names take precedence.

    Parameters
    ----------
    name_or_path : str | None
        Name or path of the environment. If None and language is provided,
        will search for or create a docker environment for that language.
    ck_info : dict | None
        Calkit info dict. If None, will be loaded from calkit.yaml.
    path_only : bool
        Only match on path, not name.
    language : str | None
        Language/tool to detect docker environment for (e.g., "latex").
        Only used if name_or_path is None.

    Returns
    -------
    EnvDetectResult
        Environment detection result.
    """
    # Load config and environment list
    if ck_info is None:
        ck_info = calkit.load_calkit_info()
    envs = ck_info.get("environments", {})
    all_env_names = list(envs.keys())
    # Handle language-based environment detection
    if name_or_path is None and language is not None:
        # Look for a docker environment matching the language
        for env_name, env in envs.items():
            if env.get("kind") == "docker":
                image = env.get("image", "").lower()
                # Check if this looks like a language environment
                if language.lower() in image or f"{language}mk" in image:
                    return EnvDetectResult(name=env_name, env=env, exists=True)
        # Only create default docker environment for latex
        if language.lower() == "latex":
            env_name = "latex"
            return EnvDetectResult(
                name=env_name,
                env={
                    "kind": "docker",
                    "image": "texlive/texlive:latest-full",
                },
                exists=False,
            )
        # For shell language, use _system environment
        if language.lower() == "shell":
            return EnvDetectResult(
                name="_system",
                env={"kind": "system"},
                exists=True,
            )
        # For other languages, try to detect a default environment
        default_env = detect_default_env(ck_info=ck_info, language=language)
        if default_env:
            return default_env
        raise ValueError(
            f"Could not find or create environment for language: {language}"
        )
    # Require either name_or_path or language
    if name_or_path is None:
        raise ValueError("Either name_or_path or language must be provided")
    # Check if environment exists by name or path
    for env_name, env in envs.items():
        if (not path_only and env_name == name_or_path) or env.get(
            "path"
        ) == name_or_path:
            return EnvDetectResult(name=env_name, env=env, exists=True)
    # Handle special _system environment
    if name_or_path == "_system":
        return EnvDetectResult(
            name="_system",
            env={"kind": "system"},
            exists=True,
        )
    # Check if name_or_path is a file and detect environment type
    env_path = name_or_path
    if os.path.isfile(env_path):
        if env_path.endswith("requirements.txt"):
            # TODO: Detect if uv is installed, and use a plain venv if not
            return EnvDetectResult(
                name=make_env_name(env_path, all_env_names, kind="uv-venv"),
                env={
                    "kind": "uv-venv",
                    "path": env_path,
                    "python": DEFAULT_PYTHON_VERSION,
                    "prefix": os.path.join(
                        os.path.split(env_path)[0], ".venv"
                    ),
                },
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
                    "name",
                    make_env_name(env_path, all_env_names, kind="conda"),
                ),
                env={"kind": "conda", "path": env_path},
                exists=False,
            )
        elif env_path.endswith("pyproject.toml"):
            # This is a uv project env
            return EnvDetectResult(
                name=make_env_name(env_path, all_env_names, kind="uv"),
                env={
                    "kind": "uv",
                    "path": env_path,
                },
                exists=False,
            )
        elif env_path.endswith("pixi.toml"):
            # This is a pixi env
            return EnvDetectResult(
                name=make_env_name(env_path, all_env_names, kind="pixi"),
                env={
                    "kind": "pixi",
                    "path": env_path,
                },
                exists=False,
            )
        elif env_path.endswith("Project.toml"):
            # This is a Julia env
            return EnvDetectResult(
                name=make_env_name(env_path, all_env_names, kind="julia"),
                env={
                    "kind": "julia",
                    "path": env_path,
                    "julia": _get_julia_version(),
                },
                exists=False,
            )
        elif env_path.endswith("DESCRIPTION"):
            # This is an R renv environment
            return EnvDetectResult(
                name=make_env_name(env_path, all_env_names, kind="renv"),
                env={"kind": "renv", "path": env_path},
                exists=False,
            )
        elif "dockerfile" in env_path.lower():
            # This is a Docker env
            project_name = calkit.detect_project_name(prepend_owner=False)
            env_name = make_env_name(env_path, all_env_names, kind="docker")
            image_name = f"{project_name}-{env_name}"
            return EnvDetectResult(
                name=env_name,
                env={
                    "kind": "docker",
                    "path": env_path,
                    "image": image_name,
                },
                exists=False,
            )
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
    # If we have neither name nor path, we can only detect the environment
    # if there's only one
    default = detect_default_env(ck_info=ck_info)
    if default:
        return default
    raise ValueError(
        f"Environment could not be detected from name: {name} "
        f"and/or path: {path}"
    )


def env_from_notebook_path(
    notebook_path: str, ck_info: dict | None = None
) -> EnvDetectResult:
    """Detect an environment for a notebook based on its path.

    First we look in pipeline stages, then in the notebooks list.
    """
    if ck_info is None:
        ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    envs = ck_info.get("environments", {})
    for stage in stages.values():
        if (
            stage.get("kind") == "jupyter-notebook"
            and stage.get("notebook_path") == notebook_path
        ):
            env_name = stage.get("environment")
            if env_name:
                env = envs.get(env_name)
                if env:
                    return EnvDetectResult(name=env_name, env=env, exists=True)
    for nb in ck_info.get("notebooks", []):
        if nb.get("path") == notebook_path:
            env_name = nb.get("environment")
            if env_name:
                env = envs.get(env_name)
                if env:
                    return EnvDetectResult(name=env_name, env=env, exists=True)
    # Fall back to default env if possible
    default = detect_default_env(ck_info=ck_info)
    if default:
        return default
    raise ValueError(
        f"Environment could not be detected for notebook path: {notebook_path}"
    )


def detect_default_env(
    ck_info: dict | None = None, language: str | None = None
) -> EnvDetectResult | None:
    """Detect a default environment for the project.

    First, if the project has a single environment, we use that. Otherwise,
    we look for a single typical env spec file.

    Parameters
    ----------
    ck_info : dict | None
        Calkit info dict. If None, will be loaded from calkit.yaml.
    language : str | None
        Language to filter environments by when multiple environments exist.
    """
    if ck_info is None:
        ck_info = calkit.load_calkit_info()
    envs = ck_info.get("environments", {})
    if len(envs) == 1:
        env_name, env = next(iter(envs.items()))
        return EnvDetectResult(name=env_name, env=env, exists=True)
    elif len(envs) > 1:
        return
    # Look for typical env spec files in order
    # There must only be one, however, otherwise the default is ambiguous
    # Filter by language if provided
    if language:
        language_lower = language.lower()
        if language_lower == "python":
            env_spec_paths = [
                "pyproject.toml",
                "requirements.txt",
                "environment.yml",
                "pixi.toml",
            ]
        elif language_lower == "julia":
            env_spec_paths = ["Project.toml"]
        elif language_lower == "r":
            env_spec_paths = ["DESCRIPTION", "environment.yml", "pixi.toml"]
        elif language_lower == "shell":
            env_spec_paths = ["Dockerfile"]
        elif language_lower == "matlab":
            env_spec_paths = ["Dockerfile"]
        else:
            # For other languages, use generic list
            env_spec_paths = [
                "pyproject.toml",
                "requirements.txt",
                "environment.yml",
                "Dockerfile",
                "Project.toml",
                "renv.lock",
                "pixi.toml",
            ]
    else:
        # No language specified, use generic list
        env_spec_paths = [
            "pyproject.toml",
            "requirements.txt",
            "environment.yml",
            "Dockerfile",
            "Project.toml",
            "DESCRIPTION",
            "pixi.toml",
        ]
    present = os.listdir(".")
    present_env_specs = [p for p in env_spec_paths if p in present]
    if len(present_env_specs) == 1:
        return env_from_name_or_path(
            present_env_specs[0], ck_info=ck_info, path_only=True
        )


def create_python_requirements_content(dependencies: list[str]) -> str:
    """Generate requirements.txt file content from a list of dependencies.

    Parameters
    ----------
    dependencies : list[str]
        List of package names.

    Returns
    -------
    str
        The requirements.txt file content.
    """
    return "\n".join(dependencies) if dependencies else ""


def create_uv_pyproject_content(
    dependencies: list[str],
    project_name: str | None = None,
    python_version: str = DEFAULT_PYTHON_VERSION,
) -> str:
    """Generate a minimal pyproject.toml for a uv environment.

    Parameters
    ----------
    dependencies : list[str]
        List of package names.
    project_name : str | None
        Name of the project. If None, uses the detected project name.
    python_version : str
        Python version to include in requires-python.

    Returns
    -------
    str
        The pyproject.toml file content.
    """
    if project_name is None:
        project_name = calkit.detect_project_name(prepend_owner=False)
    content = "[project]\n"
    content += f'name = "{project_name}"\n'
    content += 'version = "0.1.0"\n'
    content += f'requires-python = ">={python_version}"\n'
    if dependencies:
        content += "dependencies = [\n"
        for dep in sorted(dependencies):
            content += f'  "{dep}",\n'
        content += "]\n"
    return content


def _resolve_julia_package_uuids(
    package_names: list[str],
) -> dict[str, str]:
    """Resolve Julia package names to their UUIDs using Pkg registry.

    Parameters
    ----------
    package_names : list[str]
        List of Julia package names to resolve.

    Returns
    -------
    dict[str, str]
        Dictionary mapping package names to their UUIDs.
        If a package UUID cannot be resolved, it is omitted.
    """
    if not package_names:
        return {}
    # Create Julia script to query Pkg registry for UUIDs
    # This safely handles packages that don't exist
    julia_code = """
using Pkg
using Pkg.Registry

packages = split(ARGS[1], ",")
registries = Pkg.Registry.reachable_registries()
if isempty(registries)
    Pkg.Registry.add("General")
    registries = Pkg.Registry.reachable_registries()
end

for pkg in packages
    entry = nothing
    for reg in registries
        entry = Pkg.Registry.find(reg, pkg)
        if entry !== nothing
            println(pkg * "=" * string(entry.uuid))
            break
        end
    end
end
"""
    try:
        # Write Julia script to temp file since passing long code via
        # command line can be problematic
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".jl",
            delete=False,
        ) as f:
            f.write(julia_code)
            script_path = f.name
        # Run Julia with the script
        result = subprocess.run(
            [
                "julia",
                script_path,
                ",".join(package_names),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        # Clean up temp file
        try:
            os.unlink(script_path)
        except FileNotFoundError:
            pass
        if result.returncode != 0:
            # If Julia fails, return empty dict to fall back
            return {}
        # Parse output: each line is "package=uuid"
        uuids = {}
        for line in result.stdout.strip().split("\n"):
            if "=" in line:
                parts = line.strip().split("=", 1)
                if len(parts) == 2:
                    pkg, uuid = parts
                    uuids[pkg.strip()] = uuid.strip()
        return uuids
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        # If Julia is not available or times out, return empty dict
        return {}


def create_julia_project_file_content(
    dependencies: list[str],
    project_name: str = "environment",
) -> str:
    """Generate Julia Project.toml file content from a list of dependencies.

    Parameters
    ----------
    dependencies : list[str]
        List of package names.
    project_name : str
        Name of the Julia project.

    Returns
    -------
    str
        The Project.toml file content with [deps] section populated
        with UUIDs if Julia is available. Otherwise, includes package
        names in comments.
    """
    content = f'name = "{project_name}"\n'
    version = "0.1.0"
    content += f'version = "{version}"\n\n'
    if not dependencies:
        return content
    # Try to resolve UUIDs using Julia's Pkg registry
    uuids = _resolve_julia_package_uuids(dependencies)
    if uuids:
        # We have UUIDs, create proper [deps] section
        content += "[deps]\n"
        for pkg in sorted(dependencies):
            if pkg in uuids:
                content += f'{pkg} = "{uuids[pkg]}"\n'
        return content
    else:
        # Fallback: Julia not available or registry lookup failed
        # Include package names in comments for manual addition
        content += "[deps]\n"
        content += "# Dependencies (add with Julia's Pkg.add):\n"
        content += "# " + ", ".join(sorted(dependencies)) + "\n"
        return content


def create_r_description_content(dependencies: list[str]) -> str:
    """Generate R DESCRIPTION file content listing dependencies.

    This creates a minimal DESCRIPTION file that renv can work with.

    Parameters
    ----------
    dependencies : list[str]
        List of R package names.

    Returns
    -------
    str
        The DESCRIPTION file content.
    """
    content = """Package: CalkitProject
Version: 0.0.1
Title: Auto-generated R environment
"""
    if dependencies:
        if len(dependencies) == 1:
            content += f"Imports: {dependencies[0]}\n"
        else:
            # Format with first package on same line, rest indented
            content += f"Imports: {dependencies[0]},\n"
            for i, dep in enumerate(dependencies[1:], 1):
                if i < len(dependencies) - 1:
                    content += f"    {dep},\n"
                else:
                    content += f"    {dep}\n"
    return content


def extract_dependencies_from_spec_file(
    spec_path: str, language: str | None = None
) -> list[str]:
    """Extract dependencies from an environment spec file.

    Parameters
    ----------
    spec_path : str
        Path to the spec file (requirements.txt, Project.toml, etc.).
    language : str | None
        Language hint to help identify the format. If None, will be inferred
        from the file path.

    Returns
    -------
    list[str]
        List of package/dependency names.
    """
    if not os.path.exists(spec_path):
        return []
    try:
        with open(spec_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (IOError, UnicodeDecodeError):
        return []
    # Determine format from filename if not provided
    if language is None:
        if spec_path.endswith("requirements.txt"):
            language = "python-requirements"
        elif spec_path.endswith("pyproject.toml"):
            language = "python-pyproject"
        elif spec_path.endswith("Project.toml"):
            language = "julia"
        elif spec_path.endswith("DESCRIPTION"):
            language = "r"
        elif spec_path.endswith("environment.yml"):
            language = "conda"
    dependencies: list[str] = []
    if language in ["python-requirements"]:
        # Parse requirements.txt
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                # Extract package name (before any version specifiers)
                pkg = line.split("[")[0].split("==")[0].split(">=")[0]
                pkg = pkg.split("<=")[0].split(">")[0].split("<")[0]
                pkg = pkg.split("~=")[0].strip()
                if pkg:
                    dependencies.append(pkg)
    elif language == "python-pyproject":
        # Parse pyproject.toml to extract dependencies
        try:
            data = toml.loads(content)
            project_deps = data.get("project", {}).get("dependencies", [])
            for dep in project_deps:
                # Extract package name (before any version specifiers)
                pkg = dep.split("[")[0].split("==")[0].split(">=")[0]
                pkg = pkg.split("<=")[0].split(">")[0].split("<")[0]
                pkg = pkg.split("~=")[0].strip()
                if pkg:
                    dependencies.append(pkg)
        except Exception:
            pass
    elif language == "julia":
        # Parse Julia Project.toml for [deps] section
        try:
            data = toml.loads(content)
            # Package names are the keys in the [deps] section
            deps_section = data.get("deps", {})
            if isinstance(deps_section, dict):
                dependencies = list(deps_section.keys())
        except Exception:
            pass
    elif language == "r":
        # Parse R DESCRIPTION file for Imports/Depends fields,
        # correctly handling multi-line (continued) fields where
        # continuation lines start with whitespace.
        lines = content.splitlines()
        i = 0
        while i < len(lines):
            raw_line = lines[i]
            stripped = raw_line.lstrip()
            if stripped.startswith(("Imports:", "Depends:")):
                # Extract the text after the field name and colon
                _, after_colon = stripped.split(":", 1)
                pkg_chunks: list[str] = [after_colon.strip()]
                # Collect continuation lines that start with whitespace
                j = i + 1
                while j < len(lines) and (
                    lines[j].startswith(" ") or lines[j].startswith("\t")
                ):
                    pkg_chunks.append(lines[j].strip())
                    j += 1
                # Join all chunks into a single dependency string
                pkg_str = " ".join(pkg_chunks)
                # Split on commas to get individual package entries
                pkgs = [p.strip() for p in pkg_str.split(",") if p.strip()]
                for pkg in pkgs:
                    # Remove version specifications if present
                    pkg = pkg.split("(", 1)[0].strip()
                    if pkg:
                        dependencies.append(pkg)
                # Continue parsing from the first non-continuation line
                i = j
                continue
            i += 1
    elif language == "conda":
        # Parse conda environment.yml
        try:
            data = yaml.safe_load(content)
            deps = data.get("dependencies", [])
            for dep in deps:
                if isinstance(dep, str):
                    # Extract package name (before version spec)
                    pkg = dep.split("==")[0].split(">=")[0].split("<=")[0]
                    pkg = pkg.split("=")[0].strip()
                    if pkg:
                        dependencies.append(pkg)
                elif isinstance(dep, dict):
                    # Handle pip dependencies nested as {pip: [...]}
                    pip_deps = dep.get("pip", [])
                    for pip_dep in pip_deps:
                        if isinstance(pip_dep, str):
                            pkg = (
                                pip_dep.split("==")[0]
                                .split(">=")[0]
                                .split("<=")[0]
                                .split("[")[0]
                                .strip()
                            )
                            if pkg:
                                dependencies.append(pkg)
        except Exception:
            pass
    # Remove duplicates and sort
    return sorted(list(set(dependencies)))


def env_has_superset_dependencies(
    env: dict,
    required_deps: list[str],
    env_spec_path: str | None = None,
    strict: bool = False,
) -> bool:
    """Check if an environment has a superset of required dependencies.

    Parameters
    ----------
    env : dict
        Environment dict from calkit.yaml with 'kind' and 'path' keys.
    required_deps : list[str]
        List of required dependencies to check for.
    env_spec_path : str | None
        Path to the environment spec file. If None, will use env.get("path").
    strict : bool
        If True, require the spec file to exist and have extractable
        dependencies. If False, be optimistic when spec file doesn't exist.

    Returns
    -------
    bool
        True if the environment contains all required dependencies,
        False otherwise.
    """
    if not required_deps:
        # No dependencies to check, so any environment works
        return True
    if env_spec_path is None:
        env_spec_path = env.get("path")
    if not env_spec_path:
        # No path to check
        if strict:
            return False
        return True
    if not os.path.exists(env_spec_path):
        # Spec file doesn't exist
        if strict:
            # Strict mode: can't verify, so reject
            return False
        # Optimistic mode: assume it might work
        return True
    # Extract dependencies from the environment's spec file
    env_deps = extract_dependencies_from_spec_file(env_spec_path)
    if not env_deps:
        # Couldn't extract dependencies (or file is empty)
        if strict:
            # Strict mode: can't verify, so reject
            return False
        # Optimistic mode: assume it might work
        return True
    # Check if env_deps is a superset of required_deps
    # (case-insensitive comparison for package names)
    env_deps_lower = {dep.lower() for dep in env_deps}
    required_deps_lower = {dep.lower() for dep in required_deps}
    return required_deps_lower.issubset(env_deps_lower)


def detect_env_for_stage(
    stage: dict,
    environment: str | None = None,
    ck_info: dict | None = None,
    language: str | None = None,
) -> EnvForStageResult:
    """Detect or create an environment for a pipeline stage.

    This function first attempts to detect an existing environment. If that
    fails, it detects dependencies from the stage and creates an environment
    spec file.

    Parameters
    ----------
    stage : dict
        The pipeline stage dict with 'kind' and script/notebook paths.
    environment : str | None
        Optional environment name or path to use. If None, will be detected.
    ck_info : dict | None
        Calkit info dict. If None, will be loaded from calkit.yaml.
    language : str | None
        Language hint for environment detection.

    Returns
    -------
    EnvForStageResult
        Result containing environment info, spec path, content,
        and dependencies.
    """
    from calkit.detect import (
        detect_dependencies_from_notebook,
        detect_julia_dependencies,
        detect_python_dependencies,
        detect_r_dependencies,
        language_from_notebook,
    )

    if ck_info is None:
        ck_info = calkit.load_calkit_info()
    # Get existing environment names
    envs = ck_info.get("environments", {})
    all_env_names = list(envs.keys())
    # 1) If stage has an environment, use that
    if environment is not None:
        res = env_from_name_or_path(
            name_or_path=environment, ck_info=ck_info, language=language
        )
        return EnvForStageResult(
            name=res.name,
            env=res.env,
            exists=res.exists,
            spec_path=res.env.get("path"),
            dependencies=[],
            created_from_dependencies=False,
        )
    # Infer stage language if not provided
    stage_kind = stage.get("kind")
    stage_language = language
    if stage_language is None:
        if stage_kind == "jupyter-notebook":
            stage_language = (
                language_from_notebook(stage["notebook_path"]) or "python"
            )
        elif stage_kind == "python-script":
            stage_language = "python"
        elif stage_kind == "r-script":
            stage_language = "r"
        elif stage_kind == "julia-script":
            stage_language = "julia"
        elif stage_kind == "latex":
            stage_language = "latex"
        elif stage_kind in ["matlab-script", "matlab-command"]:
            stage_language = "matlab"
        elif stage_kind in ["shell-script", "shell-command"]:
            stage_language = "shell"
    language_kinds = {
        "python": ["uv", "uv-venv", "venv", "conda", "pixi"],
        "r": ["renv", "conda", "pixi"],
        "julia": ["julia"],
        "matlab": ["matlab"],
        "latex": ["docker"],
        "shell": ["system"],
    }
    preferred_kinds = (
        language_kinds.get(stage_language, []) if stage_language else []
    )
    is_first_env_for_language = not any(
        env.get("kind") in preferred_kinds for env in envs.values()
    )
    # Stages with analyzable content where we should check dependencies before
    # reusing existing environments
    analyzable_stages = {
        "jupyter-notebook",
        "python-script",
        "r-script",
        "julia-script",
        "shell-script",
    }
    # Initialize detected_dependencies so it's available throughout function
    detected_dependencies: list[str] = []
    # For analyzable stages, detect dependencies and check if existing
    # environments satisfy them
    if stage_language and stage_kind in analyzable_stages:
        if stage_kind == "python-script":
            detected_dependencies = detect_python_dependencies(
                script_path=stage["script_path"]
            )
        elif stage_kind == "r-script":
            detected_dependencies = detect_r_dependencies(
                script_path=stage["script_path"]
            )
        elif stage_kind == "julia-script":
            detected_dependencies = detect_julia_dependencies(
                script_path=stage["script_path"]
            )
        elif stage_kind == "jupyter-notebook":
            notebook_lang = language_from_notebook(stage["notebook_path"])
            detected_dependencies = detect_dependencies_from_notebook(
                stage["notebook_path"], language=notebook_lang
            )
        elif stage_kind == "matlab-script":
            # MATLAB detection if needed
            detected_dependencies = []
        elif stage_kind == "shell-script":
            # Shell script detection if needed
            detected_dependencies = []

        # Check if any existing environment has all these dependencies
        matching_envs = [
            (name, env)
            for name, env in envs.items()
            if env.get("kind") in preferred_kinds
        ]
        if matching_envs and detected_dependencies:
            # Check if any matching environment has all required dependencies
            # Use strict mode: only reuse if we can verify the deps are satisfied
            for env_name, env in sorted(
                matching_envs, key=lambda item: item[0]
            ):
                if env_has_superset_dependencies(
                    env, detected_dependencies, strict=True
                ):
                    env_name = cast(str, env_name)
                    return EnvForStageResult(
                        name=env_name,
                        env=env,
                        exists=True,
                        spec_path=env.get("path"),
                        dependencies=detected_dependencies,
                        created_from_dependencies=False,
                    )
            # No existing environment has verified dependencies, fall through to create
        # If no matching environment found or no dependencies detected,
        # fall through to create one from dependencies
    # 2) If there is already an environment for the stage language (for
    # non-analyzable stages or analyzable stages with no match), use that
    if stage_language and stage_kind not in analyzable_stages:
        matching_envs = [
            (name, env)
            for name, env in envs.items()
            if env.get("kind") in preferred_kinds
        ]
        if matching_envs:
            env_name, env = sorted(matching_envs, key=lambda item: item[0])[0]
            env_name = cast(str, env_name)
            return EnvForStageResult(
                name=env_name,
                env=env,
                exists=True,
                spec_path=env.get("path"),
                dependencies=[],
                created_from_dependencies=False,
            )
        if stage_language == "matlab":
            return EnvForStageResult(
                name="_system",
                env={"kind": "system"},
                exists=True,
                spec_path=None,
                dependencies=[],
                created_from_dependencies=False,
            )
    # 3) If a typical env spec exists for the stage language, use that
    # (fallback for analyzable stages if no existing environment matched)
    if stage_language:
        if stage_language == "latex":
            res = env_from_name_or_path(
                name_or_path=None,
                ck_info=ck_info,
                language=stage_language,
            )
            return EnvForStageResult(
                name=res.name,
                env=res.env,
                exists=res.exists,
                spec_path=res.env.get("path"),
                dependencies=[],
                created_from_dependencies=False,
            )
        spec_candidates = {
            "python": [
                "pyproject.toml",
                "requirements.txt",
                "environment.yml",
                "env/*.yml",
                "envs/*.yml",
                "pixi.toml",
            ],
            "r": [
                "DESCRIPTION",
                "environment.yml",
                "env/*.yml",
                "envs/*.yml",
                "pixi.toml",
            ],
            "julia": ["Project.toml"],
            "shell": ["Dockerfile"],
        }
        for spec_path in spec_candidates.get(stage_language, []):
            if "*" in spec_path:
                matches = sorted(glob.glob(spec_path))
                if matches:
                    spec_path = matches[0]
                else:
                    continue
            if os.path.isfile(spec_path):
                res = env_from_name_or_path(
                    name_or_path=spec_path,
                    ck_info=ck_info,
                    language=stage_language,
                )
                # For analyzable stages with detected dependencies, verify the
                # spec file has all required packages before reusing
                if stage_kind in analyzable_stages:
                    # Detect dependencies for this stage if not already done
                    if not detected_dependencies:
                        if stage_kind == "python-script":
                            detected_dependencies = detect_python_dependencies(
                                script_path=stage["script_path"]
                            )
                        elif stage_kind == "r-script":
                            detected_dependencies = detect_r_dependencies(
                                script_path=stage["script_path"]
                            )
                        elif stage_kind == "julia-script":
                            detected_dependencies = detect_julia_dependencies(
                                script_path=stage["script_path"]
                            )
                        elif stage_kind == "jupyter-notebook":
                            notebook_lang = language_from_notebook(
                                stage["notebook_path"]
                            )
                            detected_dependencies = (
                                detect_dependencies_from_notebook(
                                    stage["notebook_path"],
                                    language=notebook_lang,
                                )
                            )
                    # Only reuse if it has all the dependencies (strict mode)
                    if (
                        detected_dependencies
                        and not env_has_superset_dependencies(
                            res.env,
                            detected_dependencies,
                            spec_path,
                            strict=True,
                        )
                    ):
                        # This spec file doesn't have all deps, try next
                        # candidate
                        continue
                return EnvForStageResult(
                    name=res.name,
                    env=res.env,
                    exists=res.exists,
                    spec_path=res.env.get("path"),
                    dependencies=[],
                    created_from_dependencies=False,
                )
    dependencies: list[str] = []
    spec_path: str | None = None
    spec_content: str | None = None
    env_name: str | None = None
    env_dict: dict = {}
    # Detect dependencies based on stage kind
    if stage["kind"] == "python-script":
        dependencies = detect_python_dependencies(
            script_path=stage["script_path"]
        )
        project_name = calkit.detect_project_name(prepend_owner=False)
        # Generate unique environment name
        if is_first_env_for_language:
            temp_path = "pyproject.toml"
            env_name = make_env_name(temp_path, all_env_names, kind="uv")
            spec_path = "pyproject.toml"
            spec_content = create_uv_pyproject_content(dependencies)
            env_dict = {
                "kind": "uv",
                "path": spec_path,
            }
        else:
            temp_path = ".calkit/envs/py/pyproject.toml"
            env_name = make_env_name(temp_path, all_env_names, kind="uv")
            spec_path = f".calkit/envs/{env_name}/pyproject.toml"
            spec_content = create_uv_pyproject_content(
                dependencies,
                project_name=f"{project_name}-{env_name}",
            )
            env_dict = {
                "kind": "uv",
                "path": spec_path,
            }
    elif stage["kind"] == "r-script":
        dependencies = detect_r_dependencies(script_path=stage["script_path"])
        # Generate unique environment name
        if is_first_env_for_language:
            temp_path = "DESCRIPTION"
            env_name = make_env_name(temp_path, all_env_names, kind="renv")
            spec_path = "DESCRIPTION"
        else:
            temp_path = ".calkit/envs/r/DESCRIPTION"
            env_name = make_env_name(temp_path, all_env_names, kind="renv")
            spec_path = f".calkit/envs/{env_name}/DESCRIPTION"
        spec_content = create_r_description_content(dependencies)
        env_dict = {
            "kind": "renv",
            "path": spec_path,
        }
    elif stage["kind"] == "julia-script":
        dependencies = detect_julia_dependencies(
            script_path=stage["script_path"]
        )
        project_name = calkit.detect_project_name(prepend_owner=False)
        # Generate unique environment name
        if is_first_env_for_language:
            temp_path = "Project.toml"
            env_name = make_env_name(temp_path, all_env_names, kind="julia")
            spec_path = "Project.toml"
            julia_env_name = project_name
        else:
            temp_path = ".calkit/envs/julia/Project.toml"
            env_name = make_env_name(temp_path, all_env_names, kind="julia")
            spec_path = f".calkit/envs/{env_name}/Project.toml"
            julia_env_name = f"{project_name}-{env_name}"
        spec_content = create_julia_project_file_content(
            dependencies, project_name=julia_env_name
        )
        env_dict = {
            "kind": "julia",
            "path": spec_path,
            "julia": _get_julia_version(),
        }
    elif stage["kind"] == "jupyter-notebook":
        notebook_lang = language_from_notebook(stage["notebook_path"])
        dependencies = detect_dependencies_from_notebook(
            stage["notebook_path"], language=notebook_lang
        )
        if notebook_lang == "python" or notebook_lang is None:
            project_name = calkit.detect_project_name(prepend_owner=False)
            # Add ipykernel for Jupyter notebook support
            if "ipykernel" not in dependencies:
                dependencies.append("ipykernel")
            # Generate unique environment name
            if is_first_env_for_language:
                temp_path = "pyproject.toml"
                env_name = make_env_name(temp_path, all_env_names, kind="uv")
                spec_path = "pyproject.toml"
                spec_content = create_uv_pyproject_content(dependencies)
                env_dict = {
                    "kind": "uv",
                    "path": spec_path,
                }
            else:
                temp_path = ".calkit/envs/py/pyproject.toml"
                env_name = make_env_name(temp_path, all_env_names, kind="uv")
                spec_path = f".calkit/envs/{env_name}/pyproject.toml"
                spec_content = create_uv_pyproject_content(
                    dependencies,
                    project_name=f"{project_name}-{env_name}",
                )
                env_dict = {
                    "kind": "uv",
                    "path": spec_path,
                }
        elif notebook_lang == "r":
            # Add IRkernel for Jupyter notebook support
            if "IRkernel" not in dependencies:
                dependencies.append("IRkernel")
            # Generate unique environment name
            if is_first_env_for_language:
                temp_path = "DESCRIPTION"
                env_name = make_env_name(temp_path, all_env_names, kind="renv")
                spec_path = "DESCRIPTION"
            else:
                temp_path = ".calkit/envs/r/DESCRIPTION"
                env_name = make_env_name(temp_path, all_env_names, kind="renv")
                spec_path = f".calkit/envs/{env_name}/DESCRIPTION"
            spec_content = create_r_description_content(dependencies)
            env_dict = {
                "kind": "renv",
                "path": spec_path,
            }
        elif notebook_lang == "julia":
            # Add IJulia for Jupyter notebook support
            if "IJulia" not in dependencies:
                dependencies.append("IJulia")
            project_name = calkit.detect_project_name(prepend_owner=False)
            # Generate unique environment name
            if is_first_env_for_language:
                temp_path = "Project.toml"
                env_name = make_env_name(
                    temp_path, all_env_names, kind="julia"
                )
                spec_path = "Project.toml"
                julia_env_name = project_name
            else:
                temp_path = ".calkit/envs/julia/Project.toml"
                env_name = make_env_name(
                    temp_path, all_env_names, kind="julia"
                )
                spec_path = f".calkit/envs/{env_name}/Project.toml"
                julia_env_name = f"{project_name}-{env_name}"
            spec_content = create_julia_project_file_content(
                dependencies, project_name=julia_env_name
            )
            env_dict = {
                "kind": "julia",
                "path": spec_path,
                "julia": _get_julia_version(),
            }
    if not spec_path or not env_name:
        raise ValueError(
            f"Could not create environment for stage kind: {stage.get('kind')}"
        )
    return EnvForStageResult(
        name=env_name,
        env=env_dict,
        exists=False,
        spec_path=spec_path,
        spec_content=spec_content,
        dependencies=dependencies,
        created_from_dependencies=True,
    )
