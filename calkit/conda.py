"""Functionality for working with conda environments."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import warnings
from pathlib import Path
from typing import cast

import toml
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel

import calkit
from calkit import ryaml

# Typical conda/mamba installation directories to search
POSSIBLE_CONDA_DIRS = [
    # User home installations
    "~/miniconda3",
    "~/miniforge3",
    "~/mambaforge",
    "~/anaconda3",
    "~/conda",
    "~/Miniconda3",
    "~/Miniforge3",
    "~/Mambaforge",
    "~/Anaconda3",
    # Windows AppData installations
    "~/AppData/Local/miniconda3",
    "~/AppData/Local/miniforge3",
    "~/AppData/Local/mambaforge",
    "~/AppData/Local/anaconda3",
    "~/AppData/Local/conda",
    "~/AppData/Local/Continuum/miniconda3",
    "~/AppData/Local/Continuum/anaconda3",
    # System-wide installations (Unix)
    "/opt/miniconda3",
    "/opt/miniforge3",
    "/opt/mambaforge",
    "/opt/anaconda3",
    "/opt/conda",
    "/usr/local/miniconda3",
    "/usr/local/miniforge3",
    "/usr/local/mambaforge",
    "/usr/local/anaconda3",
    "/usr/local/conda",
    # System-wide installations (Windows)
    "C:/ProgramData/miniconda3",
    "C:/ProgramData/miniforge3",
    "C:/ProgramData/mambaforge",
    "C:/ProgramData/anaconda3",
    "C:/tools/miniconda3",
    "C:/tools/miniforge3",
    "C:/tools/mambaforge",
    "C:/tools/anaconda3",
    "C:/Miniconda3",
    "C:/Miniforge3",
    "C:/Mambaforge",
    "C:/Anaconda3",
]


def _find_exe(exe_name: str) -> str | None:
    """Find the absolute path to a conda or mamba executable."""
    # First check if it's on the PATH
    exe = shutil.which(exe_name)
    if exe is not None:
        return exe
    # If not on the path, search typical locations
    possible_locations = []
    for base_dir in POSSIBLE_CONDA_DIRS:
        expanded_dir = os.path.expanduser(base_dir)
        # Windows locations (Library/bin for .BAT files, Scripts for .exe)
        possible_locations.append(
            os.path.join(expanded_dir, "Library", "bin", f"{exe_name}.BAT")
        )
        possible_locations.append(
            os.path.join(expanded_dir, "Library", "bin", f"{exe_name}.exe")
        )
        possible_locations.append(
            os.path.join(expanded_dir, "Scripts", f"{exe_name}.exe")
        )
        possible_locations.append(
            os.path.join(expanded_dir, "Scripts", f"{exe_name}.BAT")
        )
        # Unix locations
        possible_locations.append(os.path.join(expanded_dir, "bin", exe_name))
        possible_locations.append(
            os.path.join(expanded_dir, "condabin", exe_name)
        )
    for loc in possible_locations:
        if os.path.isfile(loc) and os.access(loc, os.X_OK):
            return loc
    return None


def find_conda_exe() -> str | None:
    """Find the absolute path to the Conda executable."""
    return _find_exe("conda")


def find_mamba_exe() -> str | None:
    """Find the absolute path to the Mamba executable."""
    return _find_exe("mamba")


def _editable_package_name_from_dir(dir_path: str) -> str:
    """Get the package name from a directory containing ``setup.py`` or
    ``pyproject.toml``.
    """
    if os.path.isfile(os.path.join(dir_path, "setup.py")):
        # Read setup.py to get the package name
        with open(os.path.join(dir_path, "setup.py")) as f:
            setup_contents = f.read()
        match = re.search(r"name\s*=\s*['\"]([^'\"]+)['\"]", setup_contents)
        if match:
            return match.group(1)
    elif os.path.isfile(os.path.join(dir_path, "pyproject.toml")):
        # Read pyproject.toml to get the package name
        with open(os.path.join(dir_path, "pyproject.toml")) as f:
            try:
                pyproject = toml.load(f)
            except Exception as e:
                raise type(e)(
                    f"Failed to load pyproject.toml from {dir_path}; "
                    "check that it is valid TOML"
                ) from e
        if "project" in pyproject:
            if "name" in pyproject["project"]:
                return pyproject["project"]["name"]
    raise ValueError(f"Could not determine package name from {dir_path}")


def _run_pip_freeze(env_prefix: str) -> list[str]:
    """Run pip freeze inside a conda env and return the list of packages.

    Uses the env's pip executable directly (avoids ``conda run``, which can
    touch the env directory and invalidate the stored mtime check).
    This captures git URLs and exact refs that ``conda env export`` drops.
    """
    if sys.platform == "win32":
        pip_exe = os.path.join(env_prefix, "Scripts", "pip.exe")
    else:
        pip_exe = os.path.join(env_prefix, "bin", "pip")
    if not os.path.isfile(pip_exe):
        return []
    output = subprocess.check_output([pip_exe, "freeze"]).decode()
    return [
        line.strip()
        for line in output.splitlines()
        if line.strip() and not line.startswith("#")
    ]


_GIT_RE = re.compile(r"\s*@\s*git\+", re.IGNORECASE)


def _pkg_name_from_dep(dep: str) -> str:
    """Extract the normalized package name from a pip/conda dep string."""
    name = _GIT_RE.split(dep)[0]
    name = re.split(r"[@=<>]", name)[0]
    return name.strip().lower()


def _enrich_pip_deps_from_freeze(
    pip_deps: list[str],
    pip_freeze: list[str],
) -> list[str]:
    """Replace pip dep entries with pip freeze versions when available.

    Preserves git URLs and exact refs that conda env export drops.
    Editable installs in pip_deps are kept unchanged.
    """
    freeze_by_name = {
        _pkg_name_from_dep(line): line
        for line in pip_freeze
        if not line.startswith("-e ") and "@ file://" not in line
    }
    result = []
    for dep in pip_deps:
        if dep.startswith("-e ") or dep.startswith("--editable "):
            result.append(dep)
            continue
        name = _pkg_name_from_dep(dep)
        result.append(freeze_by_name.get(name, dep))
    return result


def _normalize_git_dep_url(dep: str) -> str:
    """Extract and normalize the git URL+ref from a dep string for comparison.

    Returns the lowercased URL with .git suffix removed.
    """
    parts = _GIT_RE.split(dep, maxsplit=1)
    if len(parts) < 2:
        return ""
    url = parts[1].strip().lower()
    if url.endswith(".git"):
        url = url[:-4]
    return url.rstrip("/")


def _check_single(
    req: str, actual: str, env_spec_dir: str, conda: bool = False
) -> bool:
    """Helper function for checking actual versions against requirements.

    Note that this also doesn't check optional dependencies.
    """
    # If this is an editable install it needs to be handled specially
    # It also needs to be relative to the env spec dir
    editable = False
    if req.startswith("-e ") or req.startswith("--editable "):
        req = req.split(" ", 1)[1]
        if "#" in req:
            req = req.split("#", 1)[0]
        req = req.strip()
        # Create path relative to env spec dir
        req = os.path.join(env_spec_dir, req)
        req = _editable_package_name_from_dir(req)
        editable = True
    # Handle git-based requirements — both legacy "pkg@git+url" and PEP 508
    # "pkg @ git+url" forms.
    req_is_git = bool(_GIT_RE.search(req))
    actual_is_git = bool(_GIT_RE.search(actual))
    if req_is_git and actual_is_git:
        # Both sides have git URLs: compare normalized URL+ref directly.
        # A short SHA in the spec matches a full SHA in the installed dep when
        # the full SHA starts with the short one.
        req_url = _normalize_git_dep_url(req)
        actual_url = _normalize_git_dep_url(actual)
        if req_url and actual_url:
            req_base, _, req_ref = req_url.rpartition("@")
            actual_base, _, actual_ref = actual_url.rpartition("@")
            if req_base != actual_base:
                return False
            return actual_ref.startswith(req_ref) or req_ref.startswith(
                actual_ref
            )
        # Fallback: compare names only
        return _pkg_name_from_dep(req) == _pkg_name_from_dep(actual)
    if req_is_git:
        req = _GIT_RE.split(req)[0].strip()
    req_name = re.split("[=<>]", req)[0].strip()
    req_spec = req.removeprefix(req_name).strip().replace(" ", "")
    if "[" in req_name:
        warnings.warn(f"Cannot check optional dependencies for {req_name}")
        # Remove optional dependencies
        req_name = req_name.split("[")[0].strip()
    if conda and req_spec.startswith("="):
        req_spec = "=" + req_spec
        if not req_spec.endswith(".*"):
            # Check that the requirement spec is all numbers and dots and add
            # an asterisk if it's missing, since conda treats "package=1.2" as
            # "package=1.2.*"
            numbers_and_dots = re.match(r"^[0-9.]+$", req_spec[2:])
            if numbers_and_dots and len(req_spec.split(".")) < 3:
                req_spec += ".*"
    if actual_is_git:
        # Spec has no git URL but installed dep does; name match is sufficient
        actual = _GIT_RE.split(actual)[0].strip()
    actual_parts = re.split("[=<>]+", actual, maxsplit=1)
    actual_name = actual_parts[0]
    actual_vers = actual_parts[1] if len(actual_parts) > 1 else ""
    if actual_name.strip().lower() != req_name.lower():
        return False
    if req_is_git or actual_is_git:
        return True
    actual_spec = actual.removeprefix(actual_name)
    if conda and actual_spec.startswith("="):
        actual_spec = "=" + actual_spec
    try:
        version = Version(actual_vers)
    except InvalidVersion:
        warnings.warn(
            f"Cannot properly check {actual_name} version {actual_vers}"
        )
        # TODO: Check exact version only
        return True
    spec = SpecifierSet(req_spec)
    return spec.contains(version, prereleases=editable)


def _check_list(
    req: str, actual: list[str], env_spec_dir: str, conda: bool = False
) -> bool:
    """Check a requirement against a list of installed packages."""
    # If req has a channel prefix, we can strip that off
    if "::" in req:
        req = req.split("::", 1)[1]
    for installed in actual:
        if not isinstance(installed, str):
            raise ValueError(
                f"Expected installed package to be a string, got {installed}"
            )
        if _check_single(
            req, installed, env_spec_dir=env_spec_dir, conda=conda
        ):
            return True
    return False


def _split_env_dependencies(
    dependencies: list[str | dict[str, str | list[str]]],
) -> tuple[list[str], list[str]]:
    """Split an environment dependency list into conda and pip deps.

    Conda environment files commonly include both the plain ``"pip"`` package
    marker and a nested ``{"pip": [...]}`` section. This helper normalizes the
    latter so callers do not need to assume it is the final list entry or that
    the pip section is already represented as a list.
    """
    conda_deps = []
    pip_deps = []
    for dep in dependencies:
        if isinstance(dep, dict):
            dep_pip = dep.get("pip", [])
            if isinstance(dep_pip, str):
                dep_pip = [dep_pip]
            elif dep_pip is None:
                dep_pip = []
            pip_deps.extend(dep_pip)
        else:
            conda_deps.append(dep)
    return conda_deps, pip_deps


def _get_pip_dependency_list(
    dependencies: list[str | dict[str, str | list[str]]],
) -> list[str]:
    """Return a mutable pip dependency list from an env dependency list."""
    for dep in dependencies:
        if isinstance(dep, dict) and "pip" in dep:
            dep_pip = dep["pip"]
            if isinstance(dep_pip, str):
                dep["pip"] = [dep_pip]
            elif dep_pip is None:
                dep["pip"] = []
            return cast(list[str], dep["pip"])
    return []


class EnvCheckResult(BaseModel):
    env_exists: bool | None = None
    env_needs_export: bool | None = None
    env_needs_rebuild: bool | None = None


def check_env(
    env_fpath: str = "environment.yml",
    log_func=None,
    lock_fpath: str | None = None,
    alt_lock_fpaths: list[str] = [],
    alt_lock_fpaths_delete: list[str] = [],
    relaxed: bool = False,
    verbose: bool = True,
) -> EnvCheckResult:
    """Check that a conda environment matches its spec.

    If it doesn't match, recreate it.

    Note that this only works with exact or no version specification.
    Using greater than and less than operators is not supported.

    If ``relaxed`` is enabled, dependencies can exist in either the conda or
    pip category.
    """
    if log_func is None:
        log_func = calkit.logger.info
    log_func(f"Checking conda env defined in {env_fpath}")
    # Determine which lock file to use for creating the environment
    lock_to_use_for_creation = None
    used_legacy_lock = None
    if lock_fpath and not os.path.isfile(lock_fpath):
        # Try alternative lock files first
        for alt_fpath in alt_lock_fpaths:
            if os.path.isfile(alt_fpath):
                lock_to_use_for_creation = alt_fpath
                log_func(
                    f"Found alternative lock file for creation: {alt_fpath}"
                )
                break
        # Try legacy lock files
        for legacy_fpath in alt_lock_fpaths_delete:
            if os.path.isfile(legacy_fpath):
                lock_to_use_for_creation = legacy_fpath
                used_legacy_lock = legacy_fpath
                log_func(
                    f"Using legacy lock file for creation: {legacy_fpath}"
                )
                break
    elif lock_fpath and os.path.isfile(lock_fpath):
        lock_to_use_for_creation = lock_fpath
        log_func(f"Using existing lock file for creation: {lock_fpath}")
    # Make sure the lock file has the correct env name in it
    if lock_to_use_for_creation:
        with open(lock_to_use_for_creation) as f:
            lock_spec = ryaml.load(f)
        lock_env_name = lock_spec.get("name")
        if lock_env_name is not None:
            with open(env_fpath) as f:
                env_spec = ryaml.load(f)
            env_spec_env_name = env_spec.get("name")
            if (
                env_spec_env_name is not None
                and lock_env_name != env_spec_env_name
            ):
                log_func(
                    f"Lock file {lock_to_use_for_creation} has env name "
                    f"{lock_env_name}, which does not match env spec "
                    f"name {env_spec_env_name}; deleting mismatched lock file "
                    "and ignoring it for creation"
                )
                if os.path.isfile(lock_to_use_for_creation):
                    os.remove(lock_to_use_for_creation)
                lock_to_use_for_creation = None
    res = EnvCheckResult()
    early_pip_freeze: list[str] = []
    if verbose:
        log_func("Getting conda info")
    conda_exe = find_conda_exe()
    if conda_exe is None:
        raise RuntimeError("Cannot find Conda executable")
    info = json.loads(subprocess.check_output([conda_exe, "info", "--json"]))
    root_prefix = info["root_prefix"]
    envs_dir = os.path.join(root_prefix, "envs")
    mamba_exe = find_mamba_exe()
    if mamba_exe is not None:
        # Use mamba by default because it's faster and produces less output
        conda_name = mamba_exe
    else:
        conda_name = conda_exe
    if verbose:
        log_func(f"Getting env list from {conda_name}")
    envs = json.loads(
        subprocess.check_output([conda_name, "env", "list", "--json"]).decode()
    )["envs"]
    # Get existing env names for those in the envs directory
    existing_env_names = [
        os.path.basename(env) for env in envs if env.startswith(envs_dir)
    ]
    # Get a list of environments defined by prefix instead of name
    env_prefixes = [e for e in envs if not e.startswith(root_prefix)]
    with open(env_fpath) as f:
        env_spec = ryaml.load(f)
    env_name = env_spec["name"]
    prefix = env_spec.get("prefix")
    prefix_orig = prefix
    if prefix is not None:
        prefix = os.path.abspath(prefix)
        env_prefix_path = prefix
        env_check_fpath = os.path.join(prefix, "env-export.yml")
    else:
        env_prefix_path = os.path.join(envs_dir, env_name)
        env_check_fpath = os.path.join(
            os.path.expanduser("~"),
            ".calkit",
            "conda-env-checks",
            env_name + ".yml",
        )
    env_check_dir = os.path.dirname(env_check_fpath)
    os.makedirs(env_check_dir, exist_ok=True)
    env_spec_dir = os.path.dirname(os.path.abspath(env_fpath))
    spec_pip_deps = _get_pip_dependency_list(env_spec["dependencies"])
    spec_has_git_pip = any(_GIT_RE.search(d) for d in spec_pip_deps)
    # Create env export command, which will be used later
    export_cmd = [
        conda_exe,  # Mamba output is slightly different
        "env",
        "export",
        "--no-builds",
        "--json",
    ]
    # Create with conda since newer mamba versions create a strange
    # "Library" subdirectory, at least on Windows
    # Use lock file for creation if available, otherwise use env spec
    create_file = (
        lock_to_use_for_creation if lock_to_use_for_creation else env_fpath
    )
    create_cmd = [conda_exe, "env", "create", "-y", "-f", create_file]
    if prefix is not None:
        export_cmd += ["--prefix", prefix]
        create_cmd += ["--prefix", prefix]
    else:
        export_cmd += ["-n", env_name]
    # Check if env even exists
    # If env has a prefix defined, it will be identified by that
    if env_name not in existing_env_names and prefix not in env_prefixes:
        log_func(f"Environment {env_name} doesn't exist; creating")
        res.env_exists = False
        # Environment doesn't exist, so create it
        try:
            subprocess.check_call(create_cmd)
            # Delete legacy lock file after successful creation
            if used_legacy_lock:
                try:
                    os.remove(used_legacy_lock)
                    log_func(
                        "Deleted legacy lock file after use: "
                        f"{used_legacy_lock}"
                    )
                except Exception as e:
                    log_func(
                        f"Failed to delete legacy lock file "
                        f"{used_legacy_lock}: {e}"
                    )
        except subprocess.CalledProcessError:
            # If creation from lock file failed, try from env spec
            if create_file != env_fpath:
                log_func(
                    "Failed to create from lock file, trying from env spec"
                )
                create_cmd = [
                    conda_exe,
                    "env",
                    "create",
                    "-y",
                    "-f",
                    env_fpath,
                ]
                if prefix is not None:
                    create_cmd += ["--prefix", prefix]
                subprocess.check_call(create_cmd)
            else:
                raise
        env_needs_rebuild = False
        env_needs_export = True
    else:
        res.env_exists = True
        env_needs_export = False
        # Environment does exist, so check it
        if os.path.isfile(env_check_fpath):
            log_func(f"Found env check file at {env_check_fpath}")
            # Open up the env check result file
            with open(env_check_fpath) as f:
                env_check = ryaml.load(f)
            # Check the prefix mtime saved to that file against the actual
            # prefix mtime
            # If they match, the environment saved in env_check is still
            # valid, so we don't need to re-export
            existing_mtime = env_check["mtime"]
            current_mtime = os.path.getmtime(
                os.path.normpath(env_check["prefix"])
            )
            log_func(f"Env check mtime: {existing_mtime}")
            log_func(f"Env dir mtime: {current_mtime}")
            env_needs_export = existing_mtime != current_mtime
        else:
            log_func(f"Env check file at {env_check_fpath} does not exist")
            env_needs_export = True
        if env_needs_export:
            log_func(f"Exporting existing env to {env_check_fpath}")
            env_check = json.loads(
                subprocess.check_output(export_cmd).decode()
            )
            env_check["mtime"] = os.path.getmtime(
                os.path.normpath(env_check["prefix"])
            )
        # If the spec has git pip deps, enrich the in-memory env_check pip
        # section so that git refs are compared correctly during the dep check
        # rather than falling back to name-only matching.
        if spec_has_git_pip:
            log_func("Running pip freeze to enrich git dep comparison")
            try:
                early_pip_freeze = _run_pip_freeze(env_prefix_path)
            except Exception as e:
                log_func(
                    f"pip freeze failed; git dep URLs may be missing: {e}"
                )
            if early_pip_freeze:
                check_pip = _get_pip_dependency_list(env_check["dependencies"])
                enriched_check_pip = _enrich_pip_deps_from_freeze(
                    check_pip, early_pip_freeze
                )
                for dep_entry in env_check["dependencies"]:
                    if isinstance(dep_entry, dict) and "pip" in dep_entry:
                        dep_entry["pip"] = enriched_check_pip
                        break
        # Determine if the env matches
        env_needs_rebuild = False
        existing_conda_deps, existing_pip_deps = _split_env_dependencies(
            env_check["dependencies"]
        )
        required_conda_deps, required_pip_deps = _split_env_dependencies(
            env_spec["dependencies"]
        )
        if relaxed:
            log_func("Running in relaxed mode; combining pip and conda deps")
            for dep in existing_pip_deps:
                existing_conda_deps.append(dep.replace("==", "="))
            for dep in required_pip_deps:
                required_conda_deps.append(dep.replace("==", "="))
        log_func("Checking conda dependencies")
        for dep in required_conda_deps:
            is_okay = _check_list(
                req=dep,
                actual=existing_conda_deps,
                env_spec_dir=env_spec_dir,
                conda=True,
            )
            if not is_okay:
                log_func(f"Found missing dependency: {dep}")
                env_needs_rebuild = True
                break
        if not env_needs_rebuild and not relaxed:
            log_func("Checking pip dependencies")
            for dep in required_pip_deps:
                is_okay = _check_list(
                    req=dep,
                    actual=existing_pip_deps,
                    env_spec_dir=env_spec_dir,
                    conda=False,
                )
                if not is_okay:
                    env_needs_rebuild = True
                    log_func(f"Found missing dependency: {dep}")
                    break
    if env_needs_rebuild:
        res.env_needs_rebuild = True
        log_func(f"Rebuilding {env_name} since it does not match spec")
        # Always rebuild from env spec file, not lock file
        rebuild_cmd = [
            conda_exe,
            "env",
            "create",
            "-y",
            "-f",
            env_fpath,
        ]
        if prefix is not None:
            rebuild_cmd += ["--prefix", prefix]
        subprocess.check_call(rebuild_cmd)
        env_needs_export = True
        # Delete legacy lock file after successful rebuild from spec
        if used_legacy_lock:
            try:
                os.remove(used_legacy_lock)
                log_func(
                    "Deleted legacy lock file after rebuild: "
                    f"{used_legacy_lock}"
                )
            except Exception as e:
                log_func(
                    "Failed to delete legacy lock file "
                    f"{used_legacy_lock}: {e}"
                )
    else:
        log_func(f"Environment {env_name} matches spec")
        res.env_needs_rebuild = False
        # Delete legacy lock file since environment is up-to-date
        if used_legacy_lock:
            try:
                os.remove(used_legacy_lock)
                log_func(
                    "Deleted legacy lock file (env matches spec): "
                    f"{used_legacy_lock}"
                )
            except Exception as e:
                log_func(
                    "Failed to delete legacy lock file "
                    f"{used_legacy_lock}: {e}"
                )
    # If the env was rebuilt, export the env check
    res.env_needs_export = env_needs_export
    # Determine whether we need pip freeze output for enriching the stored
    # env check and lock file with exact git URLs/refs.
    needs_pip_freeze = (
        env_needs_export
        or not res.env_exists
        or res.env_needs_rebuild
        or spec_has_git_pip
    )
    pip_freeze: list[str] = []
    if needs_pip_freeze:
        # Reuse the early freeze captured before dep check when possible so
        # we don't run pip twice; fall back to a fresh run after a rebuild.
        if early_pip_freeze and not res.env_needs_rebuild:
            pip_freeze = early_pip_freeze
        else:
            log_func("Running pip freeze to capture git deps")
            try:
                pip_freeze = _run_pip_freeze(env_prefix_path)
            except Exception as e:
                log_func(
                    f"pip freeze failed; git dep URLs may be missing: {e}"
                )
    if env_needs_export:
        log_func(f"Exporting existing env to {env_check_fpath}")
        env_check = json.loads(subprocess.check_output(export_cmd).decode())
        env_check["mtime"] = os.path.getmtime(
            os.path.normpath(env_check["prefix"])
        )
        if pip_freeze:
            check_pip = _get_pip_dependency_list(env_check["dependencies"])
            enriched = _enrich_pip_deps_from_freeze(check_pip, pip_freeze)
            for dep_entry in env_check["dependencies"]:
                if isinstance(dep_entry, dict) and "pip" in dep_entry:
                    dep_entry["pip"] = enriched
                    break
        with open(env_check_fpath, "w") as f:
            ryaml.dump(env_check, f)
    if lock_fpath is None:
        fname, ext = os.path.splitext(env_fpath)
        lock_fpath = fname + "-lock" + ext
    if (
        not res.env_exists
        or res.env_needs_rebuild
        or not os.path.isfile(lock_fpath)
    ):
        log_func(f"Exporting lock file to {lock_fpath}")
        env_export = json.loads(
            subprocess.check_output(
                [a for a in export_cmd if a != "--no-builds"]
            ).decode()
        )
        # Remove prefix from env export since it will be an absolute path
        _ = env_export.pop("prefix")
        # Remove name if prefix is set, since that will be the prefix
        if prefix is not None:
            _ = env_export.pop("name")
            env_export["prefix"] = prefix_orig
        # If we have any editable installs, convert them back to editable from
        # their exported package names
        # Note that this needs to be relative to the env lock directory,
        # since that's how pip will interpret it
        editable_pip_deps = {}
        required_pip_deps = _get_pip_dependency_list(env_spec["dependencies"])
        for dep in required_pip_deps:
            if dep.startswith("-e ") or dep.startswith("--editable "):
                dir_path = dep.split(" ", 1)[1]
                if "#" in dir_path:
                    dir_path = dir_path.split("#", 1)[0]
                dir_path = dir_path.strip()
                dir_path = os.path.join(env_spec_dir, dir_path)
                pkg_name = _editable_package_name_from_dir(dir_path)
                if verbose:
                    log_func(
                        f"Found editable pip dependency '{pkg_name}' "
                        f"at '{dir_path}'"
                    )
                editable_pip_deps[pkg_name] = dir_path
        export_pip_deps = _get_pip_dependency_list(env_export["dependencies"])
        if export_pip_deps:
            # Enrich with pip freeze to preserve git URLs, then fix editable paths
            if pip_freeze:
                export_pip_deps = _enrich_pip_deps_from_freeze(
                    export_pip_deps, pip_freeze
                )
            for i, dep in enumerate(export_pip_deps):
                dep_name = _pkg_name_from_dep(dep)
                if dep_name in editable_pip_deps:
                    path_rel_to_project_root = editable_pip_deps[dep_name]
                    lock_dir = os.path.dirname(lock_fpath)
                    path_rel_to_lock = os.path.relpath(
                        path_rel_to_project_root, start=lock_dir
                    )
                    export_pip_deps[i] = (
                        "-e " + Path(path_rel_to_lock).as_posix()
                    )
            # Write the modified list back (enrichment returns a new list)
            for dep_entry in env_export["dependencies"]:
                if isinstance(dep_entry, dict) and "pip" in dep_entry:
                    dep_entry["pip"] = export_pip_deps
                    break
        out_dir = os.path.dirname(lock_fpath)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(lock_fpath, "w") as f:
            ryaml.dump(env_export, f)
    elif pip_freeze and spec_has_git_pip and os.path.isfile(lock_fpath):
        # The env matched the spec so no full re-export was done, but the
        # existing lock file may pre-date pip freeze enrichment. Update its
        # pip section in place — no conda env export needed.
        with open(lock_fpath) as f:
            lock_data = ryaml.load(f) or {}
        lock_pip = _get_pip_dependency_list(lock_data.get("dependencies", []))
        enriched = _enrich_pip_deps_from_freeze(lock_pip, pip_freeze)
        if enriched != lock_pip:
            log_func("Enriching existing lock file pip section with git URLs")
            for dep_entry in lock_data.get("dependencies", []):
                if isinstance(dep_entry, dict) and "pip" in dep_entry:
                    dep_entry["pip"] = enriched
                    break
            with open(lock_fpath, "w") as f:
                ryaml.dump(lock_data, f)
    return res
