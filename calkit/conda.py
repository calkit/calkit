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
from typing import Callable, cast

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
# Virtual packages to assume when solving for another OS
_VIRTUAL_PACKAGE_OVERRIDES = {
    "linux": ("CONDA_OVERRIDE_GLIBC", "2.28"),
    "osx": ("CONDA_OVERRIDE_OSX", "11.0"),
}


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


def _norm_pkg_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _local_pip_path(dep: str) -> str | None:
    """The path a pip dependency installs from, if it's a local one."""
    dep = dep.split("#", 1)[0].strip()
    editable = re.match(r"^(-e|--editable)[\s=]+", dep)
    target = dep[editable.end() :].strip() if editable else dep
    url = re.match(r"^(?:\S+\s*@\s*)?(file:\S+)$", target)
    if url:
        from urllib.parse import unquote, urlparse

        return unquote(urlparse(url[1]).path) or None
    is_path = target.startswith((".", "/", "~")) or re.match(
        r"^[A-Za-z]:[\\/]", target
    )
    if is_path or (editable and re.match(r"^\w+\+", target) is None):
        # Without extras, e.g., '.[dev]'
        return re.sub(r"\[[^\]]*\]$", "", target)
    return None


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


def _unparseable_version_satisfies(
    req_spec: str, actual_vers: str
) -> bool | None:
    """Check a requirement spec against a version string PEP 440 rejects.

    Returns ``True`` or ``False`` when every clause in ``req_spec`` is a plain
    equality or inequality (``==``, ``===`` or ``!=``), since those can be
    decided by comparing the version strings directly. Returns ``None`` when
    the spec needs version ordering (``<``, ``<=``, ``>``, ``>=``, ``~=``) or
    contains a wildcard, both of which need a parsed version.

    An empty spec means any version satisfies the requirement.

    The comparison is an exact string match: without a parsed version there is
    no zero-padding, so ``==1.0`` will not match an installed ``1.0.0``.
    """
    if not req_spec:
        return True
    clauses = [clause for clause in req_spec.split(",") if clause]
    for clause in clauses:
        for op in ("===", "==", "!="):
            if not clause.startswith(op):
                continue
            value = clause[len(op) :]
            if "*" in value:
                # Wildcards need normalised versions to expand.
                return None
            if (actual_vers == value) == (op == "!="):
                return False
            break
        else:
            # An ordering operator, or something unrecognized.
            return None
    return True


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
    # Split on the first version operator. "!" and "~" are in the class so
    # that "!=" and "~=" requirements yield the bare package name instead of a
    # name with the operator's leading character stuck to it.
    req_name = re.split("[=<>!~]", req)[0].strip()
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
    actual_parts = re.split("[=<>!~]+", actual, maxsplit=1)
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
        # An unparseable actual version (e.g. conda's "9e") can't go through
        # SpecifierSet, which needs a parsed version to order by. Equality
        # comparisons don't need ordering, so decide those from the version
        # strings directly.
        exact = _unparseable_version_satisfies(req_spec, actual_vers)
        if exact is None:
            # Ordering constraints and wildcards are genuinely undecidable
            # here. A bare package name accepts any version; a pinned
            # constraint we can't confirm counts as not satisfied rather than
            # silently passing.
            if not req_spec:
                warnings.warn(
                    f"Cannot properly check {actual_name} version "
                    f"{actual_vers}"
                )
                return True
            warnings.warn(
                f"Cannot properly check {actual_name} version {actual_vers} "
                f"against constraint '{req_spec}'"
            )
            return False
        if not exact:
            warnings.warn(
                f"Installed {actual_name} version {actual_vers} does not "
                f"satisfy '{req_spec}'"
            )
        return exact
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
    from calkit.environments import (
        env_spec_hash,
        read_env_spec_hash,
        write_env_spec_hash,
    )

    def lock_is_stale(fpath: str) -> bool:
        """Whether a lock was resolved from a spec other than this one."""
        recorded = read_env_spec_hash(fpath)
        return recorded is not None and recorded != spec_hash

    def versions(deps: list[str], sep: str) -> dict[str, str]:
        """Map normalized package names to the versions pinned in deps."""
        out = {}
        for dep in deps:
            parts = str(dep).split("::")[-1].split(sep)
            if len(parts) >= 2 and not _GIT_RE.search(str(dep)):
                name = re.sub(r"[-_.]+", "-", parts[0].strip()).lower()
                out[name] = parts[1].strip()
        return out

    if log_func is None:
        log_func = calkit.logger.info
    log_func(f"Checking conda env defined in {env_fpath}")
    spec_hash = env_spec_hash(env_fpath)
    recorded_hash = read_env_spec_hash(lock_fpath) if lock_fpath else None
    # A lock resolved from the current spec is an input, not re-exported
    lock_is_current = (
        lock_fpath is not None
        and os.path.isfile(lock_fpath)
        and recorded_hash == spec_hash
    )
    # Determine which lock file to use for creating the environment
    lock_to_use_for_creation = None
    used_legacy_lock = None
    if lock_fpath and not os.path.isfile(lock_fpath):
        # Try alternative lock files first
        for alt_fpath in alt_lock_fpaths:
            if os.path.isfile(alt_fpath) and not lock_is_stale(alt_fpath):
                lock_to_use_for_creation = alt_fpath
                log_func(
                    f"Found alternative lock file for creation: {alt_fpath}"
                )
                break
        # Try legacy lock files
        for legacy_fpath in alt_lock_fpaths_delete:
            if os.path.isfile(legacy_fpath) and not lock_is_stale(
                legacy_fpath
            ):
                lock_to_use_for_creation = legacy_fpath
                used_legacy_lock = legacy_fpath
                log_func(
                    f"Using legacy lock file for creation: {legacy_fpath}"
                )
                break
    elif lock_fpath and lock_is_stale(lock_fpath):
        # Resolved from an older spec, so creating from it would be wrong
        log_func(f"Ignoring lock file from an older spec: {lock_fpath}")
    elif lock_fpath and os.path.isfile(lock_fpath):
        lock_to_use_for_creation = lock_fpath
        log_func(f"Using existing lock file for creation: {lock_fpath}")
    # Make sure the lock file has the correct env name in it
    if lock_to_use_for_creation:
        with open(lock_to_use_for_creation, encoding="utf-8") as f:
            lock_spec = ryaml.load(f)
        lock_env_name = lock_spec.get("name")
        if lock_env_name is not None:
            with open(env_fpath, encoding="utf-8") as f:
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
    with open(env_fpath, encoding="utf-8") as f:
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
            if create_file == lock_fpath and lock_is_current:
                raise RuntimeError(
                    f"Failed to create the environment from its lock file "
                    f"({lock_fpath}), which matches the spec ({env_fpath}). "
                    "Creating it from the spec would leave it out of sync "
                    "with its lock; delete the lock file to re-resolve it, "
                    "which reruns stages that depend on it"
                )
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
        # Follow a lock relocked elsewhere, so every platform agrees
        if not env_needs_rebuild and lock_is_current:
            assert lock_fpath is not None
            with open(lock_fpath, encoding="utf-8") as f:
                lock_conda, lock_pip = _split_env_dependencies(
                    (ryaml.load(f) or {}).get("dependencies") or []
                )
            env_conda, env_pip = _split_env_dependencies(
                env_check["dependencies"]
            )
            have = versions(env_conda, "=") | versions(env_pip, "==")
            want = versions(lock_conda, "=") | versions(lock_pip, "==")
            differing = sorted(n for n, v in want.items() if have.get(n) != v)
            if differing:
                log_func(
                    "Environment differs from its lock file in "
                    f"{', '.join(differing)}"
                )
                env_needs_rebuild = True
    if env_needs_rebuild:
        res.env_needs_rebuild = True
        # From the lock while it matches the spec, else from the spec
        rebuild_fpath = lock_fpath if lock_is_current else env_fpath
        assert rebuild_fpath is not None
        log_func(f"Rebuilding {env_name} from {rebuild_fpath}")
        rebuild_cmd = [
            conda_exe,
            "env",
            "create",
            "-y",
            "-f",
            rebuild_fpath,
        ]
        if prefix is not None:
            rebuild_cmd += ["--prefix", prefix]
        try:
            subprocess.check_call(rebuild_cmd)
        except subprocess.CalledProcessError:
            if lock_is_current:
                raise RuntimeError(
                    f"Failed to rebuild the environment from its lock file "
                    f"({lock_fpath}), which matches the spec ({env_fpath}); "
                    "delete the lock file to re-resolve it, which reruns "
                    "stages that depend on it"
                )
            raise
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
    try:
        with open(lock_fpath, encoding="utf-8") as f:
            lock_before: str | None = f.read()
    except OSError:
        lock_before = None
    if not lock_is_current and (
        not res.env_exists
        or res.env_needs_rebuild
        or not os.path.isfile(lock_fpath)
        or lock_is_stale(lock_fpath)
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
        # Local packages are exported by name and version, which can't be
        # installed, so they're written as their paths, relative to the
        # lock's directory, since that's how pip will read them
        local_pip_deps: dict[str, tuple[str, bool]] = {}
        required_pip_deps = _get_pip_dependency_list(env_spec["dependencies"])
        for dep in required_pip_deps:
            local_path = _local_pip_path(dep)
            if local_path is None:
                continue
            editable = dep.startswith(("-e", "--editable"))
            dir_path = os.path.join(
                env_spec_dir, os.path.expanduser(local_path)
            )
            if os.path.isfile(dir_path) and dir_path.endswith(".whl"):
                pkg_name = os.path.basename(dir_path).split("-")[0]
            else:
                try:
                    pkg_name = _editable_package_name_from_dir(dir_path)
                except ValueError:
                    if editable:
                        raise
                    continue
            if verbose:
                log_func(
                    f"Found local pip dependency '{pkg_name}' at '{dir_path}'"
                )
            local_pip_deps[_norm_pkg_name(pkg_name)] = (dir_path, editable)
        export_pip_deps = _get_pip_dependency_list(env_export["dependencies"])
        if export_pip_deps:
            # Enrich with pip freeze to preserve git URLs, then fix local paths
            if pip_freeze:
                export_pip_deps = _enrich_pip_deps_from_freeze(
                    export_pip_deps, pip_freeze
                )
            for i, dep in enumerate(export_pip_deps):
                dep_name = _norm_pkg_name(_pkg_name_from_dep(dep))
                if dep_name not in local_pip_deps:
                    continue
                dir_path, editable = local_pip_deps[dep_name]
                rel = Path(
                    os.path.relpath(
                        dir_path, start=os.path.dirname(lock_fpath) or "."
                    )
                ).as_posix()
                if editable:
                    export_pip_deps[i] = "-e " + rel
                else:
                    # A bare name would be read as a package to download
                    export_pip_deps[i] = (
                        rel if rel.startswith(".") else "./" + rel
                    )
            # Write the modified list back (enrichment returns a new list)
            for dep_entry in env_export["dependencies"]:
                if isinstance(dep_entry, dict) and "pip" in dep_entry:
                    dep_entry["pip"] = export_pip_deps
                    break
        out_dir = os.path.dirname(lock_fpath)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(lock_fpath, "w", encoding="utf-8", newline="\n") as f:
            ryaml.dump(env_export, f)
    elif (
        not lock_is_current
        and pip_freeze
        and spec_has_git_pip
        and os.path.isfile(lock_fpath)
    ):
        # The env matched the spec so no full re-export was done, but the
        # existing lock file may pre-date pip freeze enrichment. Update its
        # pip section in place — no conda env export needed.
        with open(lock_fpath, encoding="utf-8") as f:
            lock_data = ryaml.load(f) or {}
        lock_pip = _get_pip_dependency_list(lock_data.get("dependencies", []))
        enriched = _enrich_pip_deps_from_freeze(lock_pip, pip_freeze)
        if enriched != lock_pip:
            log_func("Enriching existing lock file pip section with git URLs")
            for dep_entry in lock_data.get("dependencies", []):
                if isinstance(dep_entry, dict) and "pip" in dep_entry:
                    dep_entry["pip"] = enriched
                    break
            with open(lock_fpath, "w", encoding="utf-8", newline="\n") as f:
                ryaml.dump(lock_data, f)
    with open(lock_fpath, encoding="utf-8") as f:
        lock_changed = f.read() != lock_before
    # All platforms are relocked together, so they agree; an existing lock
    # that matches is adopted as is, and one with no record is only added to
    spec_changed = recorded_hash != spec_hash
    adopted = recorded_hash is None and not lock_changed
    if (lock_changed or spec_changed) and not adopted:
        write_cross_platform_locks(
            env_fpath=env_fpath,
            lock_fpath=lock_fpath,
            conda_exe=conda_exe,
            log_func=log_func,
            relock=spec_changed and recorded_hash is not None,
        )
    # Last, so an interrupted relock isn't taken as current
    write_env_spec_hash(lock_fpath, env_fpath)
    return res


def write_cross_platform_locks(
    env_fpath: str,
    lock_fpath: str,
    conda_exe: str,
    log_func: Callable[[str], object] | None = None,
    relock: bool = True,
) -> list[str]:
    """Solve a conda env's lock for every other platform, best effort.

    Stages depend on the lock directory, so a platform locked later would
    invalidate them. With ``relock``, e.g., after the spec changed, every
    platform is solved again and one that can't be is removed, since it
    would be stale; otherwise only missing ones are added.

    Each platform is solved with a dry run under ``CONDA_SUBDIR``, and pip
    dependencies with ``uv pip compile``. Versions are kept to this
    platform's lock where the platform has them, so results agree across
    machines; otherwise only the spec's direct dependencies are. A platform
    that can't be solved, e.g., with no network, or whose pip dependencies
    name local paths, is left for a machine of that kind to lock.

    Returns the paths written.
    """
    from calkit.environments import (
        CONDA_VENV_ARCHS,
        UV_PLATFORM_TARGETS,
        _conda_venv_platform,
    )

    log = log_func or calkit.logger.info

    def solve(arch: str, pins: list[str]) -> list | None:
        """Solve the conda part for a platform, or None if that fails."""
        cmd = [conda_exe, "create", "--dry-run", "--json", "-n", "calkit-lock"]
        if channels:
            cmd.append("--override-channels")
        for channel in channels:
            cmd += ["-c", channel]
        cmd += pinned_conda_deps
        # Pins constrain packages the solve needs without adding others
        solve_env = os.environ | {"CONDA_SUBDIR": arch}
        if pins:
            solve_env["CONDA_PINNED_PACKAGES"] = "&".join(pins)
        # Another OS's virtual packages can't be detected from here
        arch_os = arch.split("-")[0]
        if arch_os != here_os and arch_os in _VIRTUAL_PACKAGE_OVERRIDES:
            var, vers = _VIRTUAL_PACKAGE_OVERRIDES[arch_os]
            solve_env = {var: vers} | solve_env
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, env=solve_env
            )
            links: list = json.loads(out.stdout)["actions"]["LINK"]
            return links
        except (OSError, ValueError, KeyError, TypeError) as e:
            log(f"Could not solve {env_fpath} for {arch}: {e}")
            return None

    lock_dir, lock_name = os.path.split(lock_fpath)
    stem, ext = os.path.splitext(lock_name)
    here = _conda_venv_platform()
    written: list[str] = []
    # Only a per-platform lock, e.g., from 'calkit check env', has siblings
    if stem != here or not os.path.isfile(lock_fpath):
        return written
    with open(env_fpath, encoding="utf-8") as f:
        env_spec = ryaml.load(f)
    conda_deps, pip_deps = _split_env_dependencies(env_spec["dependencies"])
    # Git URLs resolve the same anywhere, but local paths and included
    # files may not
    unpinnable = [
        d
        for d in pip_deps
        if _local_pip_path(d) is not None
        or re.match(r"^(-r|-c|--requirement|--constraint)\b", d.strip())
    ]
    channels = list(env_spec.get("channels") or [])
    # Pin direct dependencies to what's installed here
    with open(lock_fpath, encoding="utf-8") as f:
        local_lock = ryaml.load(f) or {}
    local_conda, local_pip = _split_env_dependencies(
        local_lock.get("dependencies") or []
    )
    local_conda_vers = {}
    for dep in local_conda:
        parts = str(dep).split("::")[-1].split("=")
        if len(parts) >= 2:
            local_conda_vers[parts[0].lower()] = parts[1]
    local_pip_vers = {}
    local_pip_urls = {}
    for dep in local_pip:
        if _GIT_RE.search(dep):
            local_pip_urls[_norm_pkg_name(_pkg_name_from_dep(dep))] = dep
        elif "==" in dep:
            name, vers = dep.split("==", 1)
            local_pip_vers[_norm_pkg_name(name.strip())] = vers.strip()
    conda_pins = [f"{n}=={v}" for n, v in sorted(local_conda_vers.items())]
    pip_pins = [f"{n}=={v}" for n, v in sorted(local_pip_vers.items())]
    pinned_conda_deps = []
    for dep in conda_deps:
        dep = str(dep)
        channel, _, bare = dep.rpartition("::")
        name = re.split(r"[\s=<>!~\[]", bare, maxsplit=1)[0].lower()
        if "[" in bare or name not in local_conda_vers:
            pinned_conda_deps.append(dep)
            continue
        pinned = f"{name}=={local_conda_vers[name]}"
        pinned_conda_deps.append(f"{channel}::{pinned}" if channel else pinned)
    pinned_pip_deps = []
    for dep in pip_deps:
        pkg = re.split(r"[=<>!~;@\s]", dep.strip(), maxsplit=1)[0]
        name = _norm_pkg_name(pkg.split("[")[0])
        if dep in unpinnable:
            pinned_pip_deps.append(dep)
        elif name in local_pip_urls:
            pinned_pip_deps.append(local_pip_urls[name])
        elif name not in local_pip_vers:
            pinned_pip_deps.append(dep)
        else:
            pinned_pip_deps.append(f"{pkg}=={local_pip_vers[name]}")
    here_os = here.split("-")[0]
    for arch in CONDA_VENV_ARCHS:
        out_fpath = os.path.join(lock_dir, arch + ext)
        if arch == here or (not relock and os.path.isfile(out_fpath)):
            continue
        links = None
        if not pip_deps or not (
            unpinnable
            or shutil.which("uv") is None
            or arch not in UV_PLATFORM_TARGETS
        ):
            links = solve(arch, conda_pins)
            if links is None:
                links = solve(arch, [])
        else:
            log(
                f"Not locking for {arch}, since its pip dependencies can't "
                "be pinned from here"
            )
        pinned_pip = None
        if links is not None and pip_deps:
            python = next(
                (p["version"] for p in links if p["name"] == "python"), None
            )
            target = UV_PLATFORM_TARGETS[arch]
            pinned_pip = _compile_pip_deps(
                pinned_pip_deps, target, python, constraints=pip_pins
            )
            if pinned_pip is None:
                pinned_pip = _compile_pip_deps(pinned_pip_deps, target, python)
            if pinned_pip is None:
                log(f"Could not pin pip dependencies for {arch}")
                links = None
        if links is None:
            # A lock from an older spec would install the wrong env
            if relock and os.path.isfile(out_fpath):
                os.remove(out_fpath)
            continue
        dependencies: list = [
            f"{p['name']}={p['version']}={p['build_string']}"
            for p in sorted(links, key=lambda p: p["name"])
        ]
        if pinned_pip is not None:
            # Pip leaves alone what conda already installed
            from_conda = {_norm_pkg_name(p["name"]) for p in links}
            dependencies.append(
                {
                    "pip": [
                        line
                        for line in pinned_pip
                        if _norm_pkg_name(_pkg_name_from_dep(line))
                        not in from_conda
                    ]
                }
            )
        lock_data: dict = {"channels": channels, "dependencies": dependencies}
        if env_spec.get("prefix") is not None:
            lock_data["prefix"] = env_spec["prefix"]
        else:
            lock_data = {"name": env_spec["name"]} | lock_data
        os.makedirs(lock_dir or ".", exist_ok=True)
        with open(out_fpath, "w", encoding="utf-8", newline="\n") as f:
            ryaml.dump(lock_data, f)
        written.append(out_fpath)
    return written


def _compile_pip_deps(
    pip_deps: list[str],
    target: str,
    python: str | None,
    constraints: list[str] | None = None,
) -> list[str] | None:
    """Pin pip dependencies for another platform, or None if that fails."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        reqs = os.path.join(tmp, "requirements.in")
        with open(reqs, "w", encoding="utf-8") as f:
            f.write("\n".join(pip_deps) + "\n")
        cmd = [
            "uv",
            "pip",
            "compile",
            "--quiet",
            "--no-header",
            "--no-annotate",
            "--python-platform",
            target,
        ]
        if python is not None:
            cmd += ["--python-version", python]
        if constraints:
            constraints_fpath = os.path.join(tmp, "constraints.txt")
            with open(constraints_fpath, "w", encoding="utf-8") as f:
                f.write("\n".join(constraints) + "\n")
            cmd += ["-c", constraints_fpath]
        try:
            out = subprocess.check_output(cmd + [reqs], text=True)
        except (subprocess.CalledProcessError, OSError):
            return None
    return [
        line.strip()
        for line in out.splitlines()
        if line.strip() and not line.startswith("#")
    ]
